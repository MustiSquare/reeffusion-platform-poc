import csv
import gzip
import hashlib
import io
import json
import struct
from contextlib import closing
from datetime import datetime
from uuid import uuid4

import pytest
from botocore.exceptions import ClientError
from fastapi import HTTPException
from sqlalchemy.orm import sessionmaker

from app.services import survey_xyz_export as exports
from app.services.survey_replay import decode_detections, decode_sonar
from app.services.survey_archive import archive_surveys
from app.testing.fixtures import FakeObjectStore, in_memory_session
from app.models.tables import RawDataset
from test_survey_replay import recording, packet


class Store(FakeObjectStore):
    bucket = "test"

    @property
    def client(self):
        return self

    def get_bytes(self, key):
        if key not in self.objects:
            raise ClientError({"Error": {"Code": "NoSuchKey"}}, "GetObject")
        return self.objects[key]

    def head_object(self, Bucket, Key):
        return {"ContentLength": len(self.get_bytes(Key))}

    def get_object(self, Bucket, Key):
        return {"Body": io.BytesIO(self.get_bytes(Key)), **self.head_object(Bucket, Key)}

    def open_read(self, key):
        return closing(io.BytesIO(self.get_bytes(key)))

    def put_file(self, key, source, content_type):
        source.seek(0)
        self.put_bytes(key, source.read(), content_type)

    def abort_multipart_uploads(self, prefix):
        self.aborted_prefix = prefix

    def get_paginator(self, operation):
        return self

    def paginate(self, Bucket, Prefix):
        yield {"Contents": [{"Key": k} for k in self.objects if k.startswith(Prefix)]}


class Queue:
    """Atomic Redis operations used by the job protocol, with explicit expiry tests."""
    def __init__(self): self.values = {}
    def get(self, key): return self.values.get(key)
    def exists(self, key): return key in self.values
    def set(self, key, value, nx=False, ex=None):
        if nx and key in self.values: return False
        self.values[key] = value
        return True
    def eval(self, script, count, *args):
        keys, args = args[:count], args[count:]
        if self.get(keys[0]) != args[0]: return 0
        if "'del'" in script: self.values.pop(keys[0], None)
        elif count == 2: self.values[keys[1]] = args[1]
        elif "'set'" in script: self.values[keys[0]] = args[1]
        return 1


@pytest.fixture
def setup(monkeypatch):
    queue, storage, db = Queue(), Store(), in_memory_session()
    monkeypatch.setattr(exports, "client", queue)
    replay_id = str(uuid4())
    data = recording()
    raw = RawDataset(name="A cell", source="survey_replay", acquisition_started_at=datetime(2026, 7, 10),
                     metadata_json={"replay_id": replay_id, "survey_name": "Test reef", "source_name": "original.svlog",
                                    "source_sha256": hashlib.sha256(data).hexdigest()})
    db.add(raw); db.commit()
    storage.put_bytes(f"replays/{replay_id}/source.svlog", data)
    summary = archive_surveys(db)[0]
    yield db, storage, queue, summary, raw
    db.close()


def read_rows(text):
    return list(csv.DictReader(line for line in text.splitlines() if not line.startswith("#")))


@pytest.mark.parametrize("kwargs", [{}, {"angle": .6, "mount_z": .3, "altitude": 999000}])
def test_streamed_coordinates_match_playback_and_utm(kwargs):
    data = recording(**kwargs)
    output = io.StringIO()
    result = exports.write_csv(io.BytesIO(data), output, "input.svlog")
    point = read_rows(output.getvalue())[0]
    expected = decode_sonar(data, "input.svlog")["frames"][0]["points"][0]
    assert [float(point[k]) for k in ("x", "y", "z")] == pytest.approx(expected[:3], abs=.001)
    assert float(point["z"]) < 0
    assert result["crs"] == "EPSG:32605"
    assert not result["partial"]
    assert "# crs=EPSG:32605" in output.getvalue()
    assert "# vertical_datum=vehicle_origin_uncorrected" in output.getvalue()
    assert "# point_count=1" in output.getvalue()


def repeated_recording(pings=126, detections=4000):
    data = recording()
    from app.services.survey_replay import packets
    parsed = list(packets(io.BytesIO(data), []))
    start = b"".join(packet(k, p) for k, p in parsed[:3])
    point = bytearray(parsed[3][1][:80])
    struct.pack_into("<H", point, 8, detections)
    pair = packet(3104, point + parsed[3][1][80:] * detections) + packet(*parsed[4])
    return start + pair * pings


def test_all_repeated_detections_exceed_preview_limit(tmp_path):
    data = repeated_recording()
    with (tmp_path / "large.csv").open("w+", newline="") as output:
        meta = exports.write_csv(io.BytesIO(data), output, "repeated.svlog")
        assert meta["point_count"] == 504000
        assert not meta["partial"]
        output.seek(0)
        rows = (line for line in output if not line.startswith("#"))
        assert next(rows).strip() == "x,y,z"
        first = next(rows)
        assert all(row == first for row in rows)
    assert decode_sonar(data, "repeated.svlog")["point_count"] == 1


@pytest.mark.parametrize("suffix", [b"BR", packet(150, b"{"), packet(3104, b"short"), packet(10, {"timestamp": "2026-07-11T00:00:00Z"})])
def test_incomplete_and_unsupported_recordings_are_explicitly_partial(suffix):
    output = io.StringIO()
    result = exports.write_csv(io.BytesIO(recording() + suffix), output, "damaged.svlog")
    assert result["partial"] and result["warnings"]
    assert result["point_count"] == 1
    assert "# partial=true" in output.getvalue()


def test_gzip_damage_and_configured_limit_are_partial(monkeypatch):
    output = io.StringIO()
    assert exports.write_csv(io.BytesIO(gzip.compress(recording())[:-5]), output, "bad.svlz")["partial"]
    from app.services import survey_replay
    monkeypatch.setattr(survey_replay, "MAX_DECOMPRESSED", len(recording()) + 2)
    meta = decode_detections(recording() + packet(14, b"test"), "limited", lambda *p: None)
    assert meta["partial"] and any("limit" in warning for warning in meta["warnings"])


def test_no_navigation_and_empty_results_fail():
    for data in (b"", recording(version=0), recording(nav_age=10)):
        with pytest.raises(ValueError):
            exports.write_csv(io.BytesIO(data), io.StringIO(), "empty.svlog")


def test_worker_progress_cache_and_duplicate_requests(setup):
    db, storage, queue, summary, raw = setup
    jobs = []
    enqueue = lambda *args: jobs.append(args)
    assert exports.start_export(summary, db, storage, enqueue)["status"] == "queued"
    assert exports.start_export(summary, db, storage, enqueue)["status"] == "queued"
    assert len(jobs) == 1
    source, token = jobs[0]
    exports.run_export(source, token, storage, sessionmaker(bind=db.bind))
    result = exports.status(source, storage)
    assert result["status"] == "completed" and result["point_count"] == 1
    assert result["source_sha256"] == raw.metadata_json["source_sha256"]
    assert not queue.exists(exports.keys(source["replay_id"])[0])
    assert exports.start_export(summary, db, storage, enqueue) == result
    assert len(jobs) == 1
    assert "# point_count=1" in storage.get_bytes(result["object_key"]).decode()
    # A redelivered task cannot execute again or overwrite a finished result.
    original = dict(storage.objects)
    exports.run_export(source, token, storage, sessionmaker(bind=db.bind))
    assert storage.objects == original


def test_interruption_retry_and_deletion_protection(setup):
    from app.services.dataset_cleanup import delete_archived_survey
    db, storage, queue, summary, raw = setup
    jobs = []
    exports.start_export(summary, db, storage, lambda *args: jobs.append(args))
    original = dict(storage.objects)
    with pytest.raises(HTTPException) as error:
        delete_archived_survey(db, summary, storage)
    assert error.value.status_code == 409 and storage.objects == original
    source, stale_token = jobs[0]
    abandoned = exports.prefix(source["replay_id"]) + "/abandoned.csv"
    storage.put_bytes(abandoned, b"incomplete export")
    queue.values.pop(exports.keys(source["replay_id"])[0])  # Expired after a killed worker.
    assert exports.status(source, storage)["status"] == "failed"
    exports.start_export(summary, db, storage, lambda *args: jobs.append(args))
    assert len(jobs) == 2
    exports.run_export(source, stale_token, storage, sessionmaker(bind=db.bind))
    assert exports.status(source, storage)["status"] == "queued"
    exports.run_export(*jobs[1], storage, sessionmaker(bind=db.bind))
    assert exports.status(source, storage)["status"] == "completed"
    assert abandoned not in storage.objects
    assert storage.aborted_prefix == exports.prefix(source["replay_id"]) + "/"
    delete_archived_survey(db, summary, storage)
    assert not any(k.startswith(f"replays/{source['replay_id']}/") for k in storage.objects)


def test_worker_failure_releases_lease_and_allows_retry(setup, monkeypatch):
    db, storage, queue, summary, raw = setup
    jobs = []
    exports.start_export(summary, db, storage, lambda *args: jobs.append(args))
    source, token = jobs[0]
    original = storage.put_file
    monkeypatch.setattr(storage, "put_file", lambda *args: (_ for _ in ()).throw(OSError("disk or upload failure")))
    exports.run_export(source, token, storage, sessionmaker(bind=db.bind))
    assert exports.status(source, storage)["status"] == "failed"
    assert not queue.exists(exports.keys(source["replay_id"])[0])
    monkeypatch.setattr(storage, "put_file", original)
    exports.start_export(summary, db, storage, lambda *args: jobs.append(args))
    exports.run_export(*jobs[1], storage, sessionmaker(bind=db.bind))
    assert exports.status(source, storage)["status"] == "completed"


def test_missing_source_and_failed_queue(setup):
    db, storage, queue, summary, raw = setup
    source = exports.source_for(summary, db, storage)
    def fail(*args): raise RuntimeError("broker down")
    with pytest.raises(RuntimeError): exports.start_export(summary, db, storage, fail)
    assert not queue.exists(exports.keys(source["replay_id"])[0])
    storage.delete_key(source["source_key"])
    assert exports.start_export(summary, db, storage, fail)["status"] == "unavailable"


def test_cache_requires_matching_hash_version_policy_and_csv(setup, monkeypatch):
    db, storage, queue, summary, raw = setup
    jobs = []
    exports.start_export(summary, db, storage, lambda *args: jobs.append(args))
    exports.run_export(*jobs[0], storage, sessionmaker(bind=db.bind))
    source = jobs[0][0]
    cached = exports.cached_export(storage, source)
    assert cached
    assert exports.cached_export(storage, {**source, "source_sha256": "changed"}) is None
    monkeypatch.setattr(exports, "MAX_DECOMPRESSED", exports.MAX_DECOMPRESSED + 1)
    assert exports.cached_export(storage, source) is None
    monkeypatch.undo()
    storage.delete_key(cached["object_key"])
    assert exports.cached_export(storage, source) is None


def test_lease_loss_cannot_publish_or_release_replacement_job(setup, monkeypatch):
    db, storage, queue, summary, raw = setup
    jobs = []
    exports.start_export(summary, db, storage, lambda *args: jobs.append(args))
    source, token = jobs[0]
    lease = exports.keys(source["replay_id"])[0]
    original_write = exports.write_csv
    def lose_lease(*args, **kwargs):
        result = original_write(*args, **kwargs)
        queue.set(lease, "replacement")
        return result
    monkeypatch.setattr(exports, "write_csv", lose_lease)
    exports.run_export(source, token, storage, sessionmaker(bind=db.bind))
    assert queue.get(lease) == "replacement"
    assert exports.cached_export(storage, source) is None
    assert not any(k.endswith('.csv') for k in storage.objects)


def test_partial_download_endpoint_streams_headers_and_uses_current_name(setup, monkeypatch):
    import asyncio
    from app.api import survey
    db, storage, queue, summary, raw = setup
    source = exports.source_for(summary, db, storage)
    data = recording() + b"bad"
    storage.put_bytes(source["source_key"], data)
    raw.metadata_json = {**raw.metadata_json, "source_sha256": hashlib.sha256(data).hexdigest()}
    db.commit()
    summary = archive_surveys(db)[0]
    jobs = []
    exports.start_export(summary, db, storage, lambda *args: jobs.append(args))
    exports.run_export(*jobs[0], storage, sessionmaker(bind=db.bind))
    monkeypatch.setattr(survey, "store", lambda: storage)
    response = survey.xyz_export_download(summary["id"], db)
    assert "Test_reef_2026-07-10_xyz_partial.csv" in response.headers["content-disposition"]
    async def read():
        return b"".join([chunk async for chunk in response.body_iterator])
    data = asyncio.run(read())
    assert len(data) == int(response.headers["content-length"])
    assert b"# partial=true" in data and b"# point_count=1" in data
    assert len(read_rows(data.decode())) == 1
