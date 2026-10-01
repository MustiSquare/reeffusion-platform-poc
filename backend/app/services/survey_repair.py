"""Stream a whole recording to disk, stage corrected cells, then activate atomically.

Uses the XYZ export lease so export, repair and deletion cannot race. Generations
have distinct dataset IDs: annotations and old surfaces are never moved in place.
"""
import hashlib
import json
import math
import shutil
import sqlite3
import tempfile
import time
from pathlib import Path
from uuid import uuid4, UUID

from fastapi import HTTPException
from app.models.tables import RawDataset, ProcessedDataset, ProcessingJob
from app.services import survey_xyz_export as exports
from app.services.survey_replay import COORDINATE_VERSION, decode_detections


def visible(dataset):
    meta = getattr(dataset, "metadata_json", None) or getattr(dataset, "viewer_config_json", None) or {}
    return meta.get("generation_state", "active") == "active"


def replay_rows(db, replay_id, lock=False):
    query = db.query(RawDataset).filter(RawDataset.metadata_json["replay_id"].as_string() == replay_id).order_by(RawDataset.id)
    return (query.populate_existing().with_for_update() if lock else query).all()


def check_mutation(db, replay_id):
    if any((r.metadata_json or {}).get("repair_job") for r in replay_rows(db, replay_id, lock=True)):
        try:
            active = exports.client.exists(exports.keys(replay_id)[0])
        except Exception as exc:
            raise HTTPException(503, "Cannot check survey rebuild activity; retry shortly") from exc
        if active:
            raise HTTPException(409, "Wait for the survey rebuild or export to finish")


def state_key(replay_id):
    return f"survey-repair:{replay_id}:v{COORDINATE_VERSION}"


def update(replay_id, token, state):
    state = {**state, "coordinate_version": COORDINATE_VERSION}
    if not exports.client.eval("if redis.call('get',KEYS[1]) == ARGV[1] then redis.call('set',KEYS[2],ARGV[2],'EX',ARGV[3]); return 1 else return 0 end",
                               2, exports.keys(replay_id)[0], state_key(replay_id), token, json.dumps(state), exports.STATE_SECONDS):
        raise RuntimeError("Survey rebuild lease expired; retry")
    return state


def status(summary, db, storage):
    source = exports.source_for(summary, db, storage)
    if not source:
        return {"status": "unavailable", "reason": "Original recording unavailable; legacy coordinates cannot be repaired."}
    rows = replay_rows(db, source["replay_id"])
    completed = next(((r.metadata_json or {}).get("repair_result") for r in rows
                      if visible(r) and (r.metadata_json or {}).get("coordinate_version") == COORDINATE_VERSION
                      and (r.metadata_json or {}).get("repair_result")), None)
    if completed:
        return completed
    data = exports.client.get(state_key(source["replay_id"]))
    state = json.loads(data) if data else {"status": "idle", "coordinate_status": "legacy"}
    if state["status"] in ("queued", "preparing") and not exports.client.exists(exports.keys(source["replay_id"])[0]):
        return {**state, "status": "failed", "error": "Rebuild worker was interrupted. Previous results are retained; retry."}
    return state


def start(summary, db, storage, enqueue):
    source = exports.source_for(summary, db, storage)
    if not source:
        return status(summary, db, storage)
    rows = replay_rows(db, source["replay_id"], lock=True)
    if not rows:
        raise HTTPException(404, "Survey no longer exists")
    current = status(summary, db, storage)
    if current["status"] in ("completed", "queued", "preparing"):
        return current
    ids = [r.id for r in rows]
    active_jobs = db.query(ProcessingJob).filter(ProcessingJob.raw_dataset_id.in_(ids), ProcessingJob.status.notin_(["completed", "failed"])).all()
    raw_by_id = {r.id:r for r in rows}
    if any((raw_by_id[j.raw_dataset_id].metadata_json or {}).get("generation_state") != "staged" for j in active_jobs):
        raise HTTPException(409, "Wait for cell processing to finish before rebuilding")
    token = str(uuid4())
    if not exports.client.set(exports.keys(source["replay_id"])[0], token, nx=True, ex=exports.LEASE_SECONDS):
        raise HTTPException(409, "An export or rebuild is already active for this survey")
    try:
        state = update(source["replay_id"], token, {"status": "queued", "percent": 0, "stage": "Waiting for rebuild worker"})
        for raw in rows:
            raw.metadata_json = {**raw.metadata_json, "repair_job": token, "xyz_export_job": token}
        db.commit()
        source["sizes"] = sorted({r.metadata_json.get("block", {}).get("size", 50) for r in rows if visible(r)}) or [50]
        enqueue(source, token)
        return state
    except Exception:
        db.rollback()
        exports._release(source["replay_id"], token)
        raise


class DetectionBins:
    """Bounded 8192-detection batches into a disk-backed, 1 metre accumulator."""
    def __init__(self, path):
        self.db = sqlite3.connect(path)
        self.db.execute("PRAGMA cache_size=-8192")
        self.db.execute("CREATE TABLE bins (ix INTEGER, iy INTEGER, x REAL, y REAL, z REAL, n INTEGER, depth REAL, alt REAL, an INTEGER, low REAL, high REAL, PRIMARY KEY(ix,iy)) WITHOUT ROWID")
        self.batch = []
        self.duration = 0

    def add(self, x, y, z, depth, altitude, second):
        self.duration = max(self.duration, second)
        self.batch.append((math.floor(x), math.floor(y), x, y, z, 1, depth, altitude or 0, int(altitude is not None), altitude, altitude))
        if len(self.batch) >= 8192:
            self.flush()

    def flush(self):
        self.db.executemany("""INSERT INTO bins VALUES (?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(ix,iy) DO UPDATE SET
            x=x+excluded.x,y=y+excluded.y,z=z+excluded.z,n=n+1,depth=depth+excluded.depth,
            alt=alt+excluded.alt,an=an+excluded.an,
            low=CASE WHEN low IS NULL THEN excluded.low WHEN excluded.low IS NULL THEN low ELSE min(low,excluded.low) END,
            high=CASE WHEN high IS NULL THEN excluded.high WHEN excluded.high IS NULL THEN high ELSE max(high,excluded.high) END""", self.batch)
        self.db.commit()
        self.batch.clear()

    def cells(self, size):
        self.db.create_function("cell", 2, lambda x, s: math.floor(x/s))
        return self.db.execute("SELECT DISTINCT cell(ix,?),cell(iy,?) FROM bins ORDER BY 1,2", (size, size)).fetchall()

    def frame(self, column, row, size):
        points, vertical, soundings = [], [], []
        for ix, iy, sx, sy, sz, n, depth, alt, an, low, high in self.db.execute(
                "SELECT * FROM bins WHERE ix>=? AND ix<? AND iy>=? AND iy<?", (column*size, (column+1)*size, row*size, (row+1)*size)):
            x, y, z = sx/n, sy/n, sz/n
            points.append([x, y, z, 0, 0, n])
            soundings.append([x, y, z, depth/n, n])
            if an:
                vertical.append([x, y, alt, an, low, high])
        return {"t": 0, "points": points, "sounding_altitudes": soundings, "vertical_samples": vertical}

    def coverage(self, crs):
        """Run-length encoding retains every occupied metre square without sampling."""
        from pyproj import Transformer
        inverse = Transformer.from_crs(crs, 4326, always_xy=True)
        polygons, current, count = [], None, 0
        def emit(run):
            x0, x1, y = run
            polygons.append([list(inverse.transform(x,y0)) for x,y0 in
                             ((x0,y),(x1+1,y),(x1+1,y+1),(x0,y+1))])
        for ix, iy in self.db.execute("SELECT ix,iy FROM bins ORDER BY iy,ix"):
            count += 1
            if current and current[2] == iy and current[1]+1 == ix:
                current[1] = ix
            else:
                if current: emit(current)
                current = [ix,ix,iy]
        if current: emit(current)
        return {"polygons": polygons, "occupied_square_metres": count, "sampled": False,
                "source": "All valid detections: occupied 1 m squares", "coordinate_version": COORDINATE_VERSION}


def activate(db, replay_id, token, raw_ids, result, lease_token=None):
    rows = replay_rows(db, replay_id, lock=True)
    if lease_token is not None and not exports._renew(replay_id, lease_token):
        raise RuntimeError("Survey rebuild lease expired before activation")
    if not rows or not all((r.metadata_json or {}).get("repair_job") == token for r in rows if r.id not in raw_ids):
        raise RuntimeError("Survey rebuild was removed or superseded")
    retired_processed = set()
    for raw in rows:
        state = "active" if raw.id in raw_ids else "legacy"
        raw.metadata_json = {**raw.metadata_json, "generation_state": state, "repair_job": token,
                             **({"repair_result": result} if state == "active" else {})}
        for processed in db.query(ProcessedDataset).filter_by(raw_dataset_id=raw.id):
            processed.viewer_config_json = {**(processed.viewer_config_json or {}), "generation_state": state}
            if state == "legacy":
                retired_processed.add(processed.id)
    # Derived views keep their original annotations and surfaces as explicit legacy data.
    derived = db.query(ProcessedDataset).all()
    while True:
        dependants = {p.id for p in derived if retired_processed.intersection((p.viewer_config_json or {}).get("source_dataset_ids", []))}
        if dependants.issubset(retired_processed): break
        retired_processed.update(dependants)
    for processed in derived:
        if processed.id in retired_processed:
            processed.viewer_config_json = {**(processed.viewer_config_json or {}), "generation_state": "legacy"}
    db.commit()


def discard_interrupted_spools(replay_id):
    """Only the current lease owner calls this, before creating its new spool."""
    root = Path(tempfile.gettempdir()).resolve()
    prefix = f"survey-repair-{UUID(replay_id)}-"
    for candidate in root.glob(prefix + '*'):
        target = candidate.resolve()
        if candidate.is_symlink() or target.parent != root or not target.name.startswith(prefix):
            continue
        if target.is_dir():
            shutil.rmtree(target)
    return prefix


def run(source, task_token, storage, db_factory):
    from app.api.survey import BlockRequest, encode_block, persist_block
    from app.processing.pipeline import run_processing_pipeline
    replay_id, token = source["replay_id"], f"{task_token}:{uuid4()}"
    if not exports.client.eval("if redis.call('get',KEYS[1]) == ARGV[1] then redis.call('set',KEYS[1],ARGV[2],'EX',ARGV[3]); return 1 else return 0 end",
                               1, exports.keys(replay_id)[0], task_token, token, exports.LEASE_SECONDS):
        return
    try:
        with exports.heartbeat(replay_id, token) as check, tempfile.TemporaryDirectory(prefix=discard_interrupted_spools(replay_id)) as directory:
            bins = DetectionBins(directory + "/bins.sqlite")
            last_report = 0
            consumed = 0
            def report(percent, stage):
                nonlocal last_report
                check()
                if time.monotonic()-last_report > 1 or percent >= 99:
                    update(replay_id, token, {"status": "preparing", "percent": round(percent), "stage": stage})
                    last_report = time.monotonic()
            hasher = hashlib.sha256()
            class HashedReader:
                def __init__(self, stream): self.stream = stream
                def read(self, size):
                    nonlocal consumed
                    data = self.stream.read(size); hasher.update(data); consumed += len(data)
                    report(55*min(1,consumed/max(1,source["source_size"])), "Decoding complete recording to disk")
                    return data
            try:
                with storage.open_read(source["source_key"]) as stream:
                    reader = HashedReader(stream)
                    metadata = decode_detections(reader, source["source_name"], lambda *p: None, detailed_sink=bins.add)
                    # Hash even an undecodable suffix to verify the entire stored source.
                    while reader.read(1024*1024): pass
                bins.flush()
                digest = hasher.hexdigest()
                if source.get("source_sha256") and digest != source["source_sha256"]:
                    raise ValueError("Original recording checksum differs from archive")
                if not metadata["point_count"]:
                    raise ValueError("No valid detections recovered; previous results retained")
                replay = {**metadata, "id": replay_id, "source_sha256": digest, "name": source["name"],
                          "started_at": source.get("started_at") or metadata["started_at"],
                          "source_name": source["source_name"], "geometry_generation": f"full-v{COORDINATE_VERSION}-{task_token}"}
                cells = [(size, column, row) for size in source["sizes"] for column, row in bins.cells(size)]
                coverage_key = f"replays/{replay_id}/coordinates-v{COORDINATE_VERSION}/{task_token}/coverage.json"
                storage.put_bytes(coverage_key, json.dumps(bins.coverage(metadata["crs"]),separators=(',',':')).encode(), "application/json")
                raw_ids, sparse = set(), 0
                with db_factory() as db:
                    for index, (size, column, row) in enumerate(cells):
                        report(55+44*index/max(1,len(cells)), f"Rebuilding cell {index+1}/{len(cells)}")
                        frame = bins.frame(column, row, size)
                        replay["frames"] = [frame]
                        body = BlockRequest.model_construct(column=column, row=row, size=size, until=bins.duration)
                        _, points, data = encode_block(replay_id, body, replay)
                        saved = persist_block(replay_id, body, db, replay, points, data, overwrite=True, generation_state="staged", allow_sparse=True)
                        raw_ids.add(saved["dataset_id"])
                        if len(points)<4 or len({p[0] for p in points})<2 or len({p[1] for p in points})<2:
                            sparse += 1
                            continue
                        if saved.get("job_id") and db.get(ProcessingJob,saved["job_id"]).status == "completed":
                            continue
                        # Mark jobs from a lost repair delivery failed before retrying.
                        for old in db.query(ProcessingJob).filter_by(raw_dataset_id=saved["dataset_id"]).all():
                            if old.status not in ("completed","failed"):
                                old.status="failed"; old.error="Interrupted survey rebuild; retried"
                        job = ProcessingJob(raw_dataset_id=saved["dataset_id"], status="queued", progress=0)
                        db.add(job); db.commit()
                        run_processing_pipeline(db, job.id)
                    result = {"status": "completed", "percent": 100, "coordinate_version": COORDINATE_VERSION,
                              "point_count": metadata["point_count"], "cells": len(cells), "sparse_cells": sparse,
                              "partial": metadata["partial"], "warnings": metadata["warnings"], "skipped": metadata["skipped"]}
                    result["coverage_key"] = coverage_key
                    check()
                    if not exports._renew(replay_id, token): raise RuntimeError("Rebuild lease expired")
                    activate(db, replay_id, task_token, raw_ids, result, lease_token=token)
                    update(replay_id, token, result)
            finally:
                bins.db.close()
    except Exception as exc:
        try: update(replay_id, token, {"status": "failed", "error": f"{exc}. Previous results retained; retry."})
        except Exception: pass
        raise
    finally:
        exports._release(replay_id, token)
