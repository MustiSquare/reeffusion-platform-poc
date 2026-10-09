"""Full-recording XYZ exports: bounded disk spooling, durable manifests and leased jobs."""
import csv
import hashlib
import io
import json
import re
import shutil
import tempfile
import threading
import time
from contextlib import contextmanager
from uuid import uuid4, UUID

from botocore.exceptions import ClientError
from fastapi import HTTPException
from redis import Redis

from app.core.config import settings
from app.models.tables import RawDataset
from app.services.survey_replay import decode_detections, MAX_DECOMPRESSED, COORDINATE_VERSION

VERSION = 1
LEASE_SECONDS = 300
STATE_SECONDS = 7 * 86400
client = Redis.from_url(settings.redis_url, socket_connect_timeout=3, socket_timeout=3)
MISSING = {"NoSuchKey", "404", "NotFound"}


def keys(replay_id):
    return f"survey-xyz:{replay_id}:lease", f"survey-xyz:{replay_id}:state"


def prefix(replay_id):
    return f"replays/{UUID(replay_id)}/xyz-v{VERSION}-coordinates-v{COORDINATE_VERSION}"


def source_for(summary, db, storage):
    seen = set()
    for item in summary["raw"]:
        raw = db.get(RawDataset, item["id"])
        if raw is None:
            continue
        meta = raw.metadata_json or {}
        replay_id = meta.get("replay_id")
        if not replay_id or replay_id in seen:
            continue
        seen.add(replay_id)
        for extension in ("svlz", "svlog"):
            key = f"replays/{UUID(replay_id)}/source.{extension}"
            try:
                info = storage.client.head_object(Bucket=storage.bucket, Key=key)
            except ClientError as exc:
                if exc.response["Error"]["Code"] in MISSING:
                    continue
                raise
            return {"replay_id": replay_id, "source_key": key, "source_size": info["ContentLength"],
                    "source_sha256": meta.get("source_sha256"), "name": summary["name"],
                    "source_name": meta.get("source_name") or key,
                    "started_at": summary.get("started_at")}
    return None


def cached_export(storage, source):
    try:
        manifest = json.loads(storage.get_bytes(prefix(source["replay_id"]) + "/manifest.json"))
        if (manifest.get("format_version") != VERSION or
                manifest.get("coordinate_version") != COORDINATE_VERSION or
                manifest.get("decompressed_limit_bytes") != MAX_DECOMPRESSED or
                (source.get("source_sha256") and manifest.get("source_sha256") != source["source_sha256"])):
            return None
        storage.client.head_object(Bucket=storage.bucket, Key=manifest["object_key"])
        return manifest
    except ClientError as exc:
        if exc.response["Error"]["Code"] not in MISSING:
            raise
    return None


def discard_abandoned_exports(storage, replay_id):
    """A killed worker may leave multipart parts or a CSV without its manifest."""
    root = prefix(replay_id) + "/"
    storage.abort_multipart_uploads(root)
    keep = {root + "manifest.json"}
    try:
        keep.add(json.loads(storage.get_bytes(root + "manifest.json"))["object_key"])
    except ClientError as exc:
        if exc.response["Error"]["Code"] not in MISSING:
            raise
    for page in storage.client.get_paginator("list_objects_v2").paginate(Bucket=storage.bucket, Prefix=root):
        for item in page.get("Contents", []):
            if item["Key"] not in keep:
                storage.delete_key(item["Key"])


def status(source, storage):
    if source is None:
        return {"status": "unavailable", "reason": "The original SonarView recording is not available for this survey."}
    cached = cached_export(storage, source)
    if cached:
        return cached
    lease, state_key = keys(source["replay_id"])
    state = client.get(state_key)
    result = json.loads(state) if state else {"status": "idle"}
    if result["status"] in ("queued", "preparing") and not client.exists(lease):
        return {**result, "status": "failed", "error": "Export worker was interrupted or did not start. Retry the export."}
    if result["status"] == "completed":
        return {"status": "failed", "error": "The saved CSV is missing or outdated. Retry the export."}
    return result


def _renew(replay_id, token):
    return client.eval("if redis.call('get',KEYS[1]) == ARGV[1] then return redis.call('expire',KEYS[1],ARGV[2]) else return 0 end",
                       1, keys(replay_id)[0], token, LEASE_SECONDS)


def _release(replay_id, token):
    client.eval("if redis.call('get',KEYS[1]) == ARGV[1] then return redis.call('del',KEYS[1]) else return 0 end",
                1, keys(replay_id)[0], token)


def _update(replay_id, token, state):
    ok = client.eval("if redis.call('get',KEYS[1]) == ARGV[1] then redis.call('set',KEYS[2],ARGV[2],'EX',ARGV[3]); return 1 else return 0 end",
                     2, *keys(replay_id), token, json.dumps(state), STATE_SECONDS)
    if not ok:
        raise RuntimeError("Export lease expired; retry the export")


def start_export(summary, db, storage, enqueue):
    # Same row locks as deletion; publish the lease before releasing the rows.
    rows = db.query(RawDataset).filter(RawDataset.id.in_([r["id"] for r in summary["raw"]])).order_by(RawDataset.id).populate_existing().with_for_update().all()
    source = source_for(summary, db, storage)
    if source:
        from app.services.survey_repair import state_key
        repair_state = client.get(state_key(source["replay_id"]))
        if repair_state and json.loads(repair_state).get("status") in ("queued", "preparing") and client.exists(keys(source["replay_id"])[0]):
            raise HTTPException(409, "Wait for the survey rebuild to finish before exporting")
    current = status(source, storage)
    if current["status"] in ("unavailable", "completed", "queued", "preparing"):
        return current
    replay_id, token = source["replay_id"], str(uuid4())
    if not client.set(keys(replay_id)[0], token, nx=True, ex=LEASE_SECONDS):
        concurrent = status(source, storage)
        if concurrent['status'] in ('queued', 'preparing', 'completed'):
            return concurrent
        raise HTTPException(409, 'Wait for active raw-point preparation or survey rebuild to finish before exporting')
    try:
        state = {"status": "queued", "percent": 0, "stage": "Waiting for export worker", "point_count": 0}
        _update(replay_id, token, state)
        for raw in rows:
            if (raw.metadata_json or {}).get("replay_id") == replay_id:
                raw.metadata_json = {**raw.metadata_json, "xyz_export_job": token}
        db.commit()
        enqueue(source, token)
        return state
    except Exception:
        db.rollback()
        try:
            _update(replay_id, token, {"status": "failed", "error": "Could not queue the export. Retry."})
        finally:
            _release(replay_id, token)
        raise


def check_deletion(db, raw):
    """Called while holding the raw row lock; fail closed for tracked exports."""
    meta = raw.metadata_json or {}
    replay_id = meta.get("replay_id")
    if not replay_id:
        return
    tracked = meta.get("xyz_export_job") or any(
        (r.metadata_json or {}).get("replay_id") == replay_id and (r.metadata_json or {}).get("xyz_export_job")
        for r in db.query(RawDataset).all())
    if tracked:
        try:
            active = client.exists(keys(replay_id)[0])
        except Exception as exc:
            raise HTTPException(503, "Cannot check export activity; retry deletion when the queue is available") from exc
        if active:
            raise HTTPException(409, "Wait for the survey export, raw-point preparation or rebuild to finish before deleting this survey data")


@contextmanager
def heartbeat(replay_id, token):
    if not _renew(replay_id, token):
        raise RuntimeError("Export lease expired")
    stopped, lost = threading.Event(), threading.Event()
    def run():
        while not stopped.wait(15):
            try:
                if not _renew(replay_id, token):
                    lost.set()
                    return
            except Exception:
                lost.set()
                return
    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    def check():
        if lost.is_set():
            raise RuntimeError("Export worker lost its lease. Retry the export.")
    try:
        yield check
    finally:
        stopped.set()
        thread.join(timeout=5)


def download_name(name, started_at, partial):
    name = re.sub(r"[^\w.-]+", "_", name, flags=re.ASCII).strip("._")[:100] or "survey"
    date = (started_at or "undated")[:10]
    date = re.sub(r"[^0-9A-Za-z-]", "_", date)
    return f"{name}_{date}_xyz{'_partial' if partial else ''}.csv"


def write_csv(source, output, source_name, progress=None):
    """Two disk passes allow exact count/partial metadata ahead of streamed rows."""
    with tempfile.TemporaryFile(mode="w+", encoding="utf-8", newline="") as rows:
        writer = csv.writer(rows)
        metadata = decode_detections(source, source_name,
                                     lambda x, y, z: writer.writerow((format(x, '.9f'), format(y, '.9f'), format(z, '.9f'))),
                                     progress=progress)
        if not metadata["point_count"]:
            raise ValueError("No valid supported sonar detections were recovered; no XYZ CSV was produced. " + " ".join(metadata["warnings"]))
        metadata.update(format_version=VERSION, source_recording=source_name,
                        xy_units="metres", z_units="metres", vertical_convention="elevation_positive_up")
        output.write("# Full-survey individual sonar detections\n")
        for key, value in metadata.items():
            value = value.replace('\r', '\\r').replace('\n', '\\n') if isinstance(value, str) else json.dumps(value)
            output.write(f"# {key}={value}\n")
        output.write("# No draft, tide, MSL offset or vertical exaggeration applied.\n")
        output.write("# Provisional geometry: verify mounting and heading against SonarView.\n")
        output.write("x,y,z\n")
        rows.seek(0)
        shutil.copyfileobj(rows, output, length=1024 * 1024)
        return metadata


def run_export(source, token, storage, db_factory):
    replay_id = source["replay_id"]
    task_token = token
    token = f"{task_token}:{uuid4()}"
    # Only one delivery of a queued task may become the running worker.
    claimed = client.eval("if redis.call('get',KEYS[1]) == ARGV[1] then redis.call('set',KEYS[1],ARGV[2],'EX',ARGV[3]); return 1 else return 0 end",
                          1, keys(replay_id)[0], task_token, token, LEASE_SECONDS)
    if not claimed:
        return
    uploaded_key = None
    try:
        with heartbeat(replay_id, token) as check, tempfile.TemporaryFile() as original, tempfile.TemporaryFile() as result:
            discard_abandoned_exports(storage, replay_id)
            last_report = 0
            def report(percent, stage):
                nonlocal last_report
                check()
                if time.monotonic() - last_report > .5 or percent >= 98:
                    _update(replay_id, token, {"status": "preparing", "percent": round(percent), "stage": stage})
                    last_report = time.monotonic()
            digest, consumed = hashlib.sha256(), 0
            with storage.open_read(source["source_key"]) as stream:
                while chunk := stream.read(1024 * 1024):
                    original.write(chunk)
                    digest.update(chunk)
                    consumed += len(chunk)
                    report(25 * consumed / max(1, source["source_size"]), "Reading original recording")
            source_hash = digest.hexdigest()
            if source.get("source_sha256") and source_hash != source["source_sha256"]:
                raise ValueError("The original recording checksum differs from the archived source")
            original.seek(0)
            decoded = 0
            def advance(count):
                nonlocal decoded
                decoded += count
                report(25 + 65 * min(1, decoded / max(1, consumed)), "Decoding individual detections")
            text = io.TextIOWrapper(result, encoding="utf-8", newline="")
            try:
                manifest = write_csv(original, text, source["source_name"], progress=advance)
                text.flush()
            finally:
                text.detach()
            report(98, "Saving XYZ CSV")
            object_key = f"{prefix(replay_id)}/{source_hash}/{task_token}.csv"
            manifest.update(status="completed", percent=100, source_sha256=source_hash,
                            decompressed_limit_bytes=MAX_DECOMPRESSED, object_key=object_key,
                            size_bytes=result.tell())
            # Serialize publication with deletion, including uploads that outlive a lease.
            with db_factory() as db:
                rows = db.query(RawDataset).filter(RawDataset.metadata_json["replay_id"].as_string() == replay_id).order_by(RawDataset.id).with_for_update().all()
                if not any((r.metadata_json or {}).get("replay_id") == replay_id and
                           (r.metadata_json or {}).get("xyz_export_job") == task_token for r in rows):
                    raise RuntimeError("Survey was removed or this export was superseded")
                check()
                if not _renew(replay_id, token):
                    raise RuntimeError("Export lease expired")
                uploaded_key = object_key
                storage.put_file(object_key, result, "text/csv")
                check()
                storage.put_bytes(prefix(replay_id) + "/manifest.json", json.dumps(manifest).encode(), "application/json")
                uploaded_key = None
                db.commit()
                _update(replay_id, token, manifest)
    except Exception as exc:
        if uploaded_key:
            storage.delete_key(uploaded_key)
        try:
            _update(replay_id, token, {"status": "failed", "error": f"{exc}. Retry the export."})
        except Exception:
            pass  # An expired lease is reported as interrupted by status().
    finally:
        try:
            _release(replay_id, token)
        except Exception:
            pass
