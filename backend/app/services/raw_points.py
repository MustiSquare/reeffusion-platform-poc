"""Lossless-multiplicity raw detection index; bounded disk spooling and GPU chunks."""
import hashlib
import json
import math
import shutil
import struct
import tempfile
import time
from collections import OrderedDict
from pathlib import Path
from uuid import UUID, uuid4

import numpy as np
from botocore.exceptions import ClientError
from fastapi import HTTPException

from app.models.tables import RawDataset
from app.services import survey_xyz_export as exports
from app.services.survey_replay import COORDINATE_VERSION, MAX_DECOMPRESSED, decode_detections

VERSION = 1
CHUNK_POINTS = 100_000
OVERVIEW_POINTS = 2_000_000
TILE_SIZE = 25


def prefix(replay_id):
    return f"replays/{UUID(replay_id)}/raw-points-v{VERSION}-coordinates-v{COORDINATE_VERSION}"


def state_key(replay_id):
    return f"survey-raw-points:{replay_id}:state"


def update(replay_id, token, state):
    if not exports.client.eval("if redis.call('get',KEYS[1]) == ARGV[1] then redis.call('set',KEYS[2],ARGV[2],'EX',ARGV[3]); return 1 else return 0 end",
                               2, exports.keys(replay_id)[0], state_key(replay_id), token, json.dumps(state), exports.STATE_SECONDS):
        raise RuntimeError("Raw-point preparation lease expired; retry")
    return state


def cached(source, storage):
    if not source:
        return None
    try:
        result = json.loads(storage.get_bytes(prefix(source['replay_id']) + '/manifest.json'))
    except ClientError as exc:
        if exc.response['Error']['Code'] not in exports.MISSING:
            raise
        return None
    if (result.get('format_version') != VERSION or result.get('coordinate_version') != COORDINATE_VERSION
            or result.get('decompressed_limit_bytes') != MAX_DECOMPRESSED
            or (source.get('source_sha256') and result.get('source_sha256') != source['source_sha256'])):
        return None
    return result


def status(source, storage):
    if not source:
        return {'status': 'unavailable', 'reason': 'Original sonar recording unavailable.'}
    manifest = cached(source, storage)
    if manifest:
        return {k: v for k, v in manifest.items() if k not in ('chunks', 'overview')}
    data = exports.client.get(state_key(source['replay_id']))
    result = json.loads(data) if data else {'status': 'idle'}
    if result['status'] in ('queued', 'preparing') and not exports.client.exists(exports.keys(source['replay_id'])[0]):
        return {'status': 'failed', 'error': 'Raw-point worker interrupted. Retry preparation.'}
    if result['status'] == 'completed':
        return {'status': 'failed', 'error': 'Raw-point index outdated or missing. Retry preparation.'}
    return result


def start(summary, db, storage, enqueue):
    rows = db.query(RawDataset).filter(RawDataset.id.in_([r['id'] for r in summary['raw']])).order_by(RawDataset.id).populate_existing().with_for_update().all()
    source = exports.source_for(summary, db, storage)
    current = status(source, storage)
    if current['status'] in ('unavailable', 'completed', 'queued', 'preparing'):
        return current
    replay_id, token = source['replay_id'], str(uuid4())
    if not exports.client.set(exports.keys(replay_id)[0], token, nx=True, ex=exports.LEASE_SECONDS):
        raise HTTPException(409, 'Wait for the active survey export or rebuild to finish.')
    try:
        result = update(replay_id, token, {'status': 'queued', 'percent': 0, 'stage': 'Waiting for raw-point worker'})
        for row in rows:
            if (row.metadata_json or {}).get('replay_id') == replay_id:
                row.metadata_json = {**row.metadata_json, 'xyz_export_job': token}
        db.commit()
        enqueue(source, token)
        return result
    except Exception:
        db.rollback()
        try:
            update(replay_id, token, {'status': 'failed', 'error': 'Could not queue raw-point preparation. Retry.'})
        finally:
            exports._release(replay_id, token)
        raise


class TileSpool:
    def __init__(self, directory):
        self.directory = Path(directory)
        self.handles = OrderedDict()
        self.tiles = {}

    def add(self, x, y, z):
        tile = (math.floor(x / TILE_SIZE), math.floor(y / TILE_SIZE))
        info = self.tiles.setdefault(tile, {'count': 0, 'min': [x, y, z], 'max': [x, y, z]})
        info['count'] += 1
        for i, value in enumerate((x, y, z)):
            info['min'][i] = min(info['min'][i], value)
            info['max'][i] = max(info['max'][i], value)
        handle = self.handles.pop(tile, None)
        if handle is None:
            if len(self.handles) >= 64:
                self.handles.popitem(last=False)[1].close()
            handle = open(self.path(tile), 'ab', buffering=65536)
        self.handles[tile] = handle
        handle.write(struct.pack('<ddd', x, y, z))

    def path(self, tile):
        return self.directory / f'{tile[0]}_{tile[1]}.bin'

    def close(self):
        for handle in self.handles.values():
            handle.close()
        self.handles.clear()

    def publish(self, write, progress=lambda _: None):
        self.close()
        total = sum(t['count'] for t in self.tiles.values())
        if not total:
            raise ValueError('No valid supported sonar detections recovered')
        chunks, overview = [], []
        # Stratified systematic samples; each occupied tile gets representation.
        budget = min(total, OVERVIEW_POINTS)
        if len(self.tiles) > budget:
            raise ValueError('Too many occupied tiles for this overview format')
        remaining = budget - len(self.tiles)
        extra_total = total - len(self.tiles)
        cumulative_extra = 0
        for ti, (tile, info) in enumerate(sorted(self.tiles.items())):
            count = info['count']
            before = cumulative_extra * remaining // max(1, extra_total)
            cumulative_extra += count - 1
            take = 1 + cumulative_extra * remaining // max(1, extra_total) - before
            origin = [tile[0] * TILE_SIZE, tile[1] * TILE_SIZE, info['min'][2]]
            data = np.memmap(self.path(tile), dtype='<f8', mode='r', shape=(count, 3))
            def emit(points, label, target):
                ident = f'{ti}-{label}'
                payload = np.asarray(points - origin, dtype='<f4').tobytes()
                write(ident, payload)
                target.append({'id': ident, 'count': len(points), 'origin': origin,
                               'min': info['min'], 'max': info['max'], 'bytes': len(payload)})
            for offset in range(0, count, CHUNK_POINTS):
                emit(data[offset:offset + CHUNK_POINTS], str(offset // CHUNK_POINTS), chunks)
            indices = np.minimum(count - 1, np.floor((np.arange(take) + .5) * count / take).astype(np.int64))
            for offset in range(0, take, CHUNK_POINTS):
                emit(data[indices[offset:offset + CHUNK_POINTS]], f'overview-{offset // CHUNK_POINTS}', overview)
            del data
            progress((ti + 1) / len(self.tiles))
        return {'chunks': chunks, 'overview': overview, 'point_count': total,
                'overview_count': sum(c['count'] for c in overview),
                'min': [min(t['min'][i] for t in self.tiles.values()) for i in range(3)],
                'max': [max(t['max'][i] for t in self.tiles.values()) for i in range(3)]}


def run(source, task_token, storage, db_factory):
    replay_id = source['replay_id']
    token = f'{task_token}:{uuid4()}'
    if not exports.client.eval("if redis.call('get',KEYS[1]) == ARGV[1] then redis.call('set',KEYS[1],ARGV[2],'EX',ARGV[3]); return 1 else return 0 end",
                               1, exports.keys(replay_id)[0], task_token, token, exports.LEASE_SECONDS):
        return
    generation = None
    published = False
    try:
        temp_root = Path(tempfile.gettempdir()).resolve()
        temp_prefix = f'reef-raw-{UUID(replay_id)}-'
        for abandoned in temp_root.glob(temp_prefix + '*'):
            if abandoned.is_dir() and abandoned.resolve().parent == temp_root and time.time() - abandoned.stat().st_mtime > 2 * exports.LEASE_SECONDS:
                shutil.rmtree(abandoned)
        with exports.heartbeat(replay_id, token) as check, tempfile.TemporaryFile() as original, tempfile.TemporaryDirectory(prefix=temp_prefix) as directory:
            last_report = 0
            def report(percent, stage):
                nonlocal last_report
                check()
                if time.monotonic() - last_report > .5 or percent >= 99:
                    update(replay_id, token, {'status': 'preparing', 'percent': round(percent), 'stage': stage})
                    last_report = time.monotonic()
            # Remove only unpublished generations while holding the shared lease.
            old = cached(source, storage)
            root = prefix(replay_id) + '/'
            keep = old.get('generation') if old else None
            for page in storage.client.get_paginator('list_objects_v2').paginate(Bucket=storage.bucket, Prefix=root):
                for obj in page.get('Contents', []):
                    if obj['Key'] != root + 'manifest.json' and not (keep and obj['Key'].startswith(keep + '/')):
                        storage.delete_key(obj['Key'])
            digest, consumed = hashlib.sha256(), 0
            with storage.open_read(source['source_key']) as stream:
                while data := stream.read(1024 * 1024):
                    original.write(data)
                    digest.update(data)
                    consumed += len(data)
                    report(20 * consumed / max(1, source['source_size']), 'Reading original recording')
            source_hash = digest.hexdigest()
            if source.get('source_sha256') and source_hash != source['source_sha256']:
                raise ValueError('Original recording checksum mismatch')
            original.seek(0)
            spool = TileSpool(directory)
            decoded = 0
            def advance(count):
                nonlocal decoded
                decoded += count
                report(20 + 50 * min(1, decoded / max(1, consumed)), 'Indexing individual detections')
            try:
                metadata = decode_detections(original, source['source_name'], spool.add, progress=advance)
            finally:
                spool.close()
            generation = f'{prefix(replay_id)}/{source_hash}/{task_token}'
            def write(ident, payload):
                check()
                storage.put_bytes(f'{generation}/{ident}.bin', payload, 'application/octet-stream')
            index = spool.publish(write, lambda n: report(70 + 29 * n, 'Saving raw-point chunks'))
            if index['point_count'] != metadata['point_count']:
                raise ValueError('Detection index count mismatch')
            manifest = {**metadata, **index, 'status': 'completed', 'percent': 100,
                        'format_version': VERSION, 'source_sha256': source_hash, 'generation': generation,
                        'decompressed_limit_bytes': MAX_DECOMPRESSED, 'source_recording': source['source_name'],
                        'encoding': 'little-endian-float32-xyz-offsets', 'units': 'metres'}
            with db_factory() as db:
                rows = db.query(RawDataset).filter(RawDataset.metadata_json['replay_id'].as_string() == replay_id).order_by(RawDataset.id).with_for_update().all()
                if not any((r.metadata_json or {}).get('xyz_export_job') == task_token for r in rows):
                    raise RuntimeError('Survey removed or preparation superseded')
                check()
                if not exports._renew(replay_id, token):
                    raise RuntimeError('Raw-point lease expired')
                storage.put_bytes(root + 'manifest.json', json.dumps(manifest).encode(), 'application/json')
                published = True
                db.commit()
                update(replay_id, token, {'status': 'completed', 'percent': 100, 'point_count': index['point_count']})
    except Exception as exc:
        if generation and not published:
            storage.delete_prefix(generation + '/')
        try:
            update(replay_id, token, {'status': 'failed', 'error': f'{exc}. Retry preparation.'})
        except Exception:
            pass
    finally:
        try:
            exports._release(replay_id, token)
        except Exception:
            pass  # Lease expiry makes an interrupted attempt retryable.
