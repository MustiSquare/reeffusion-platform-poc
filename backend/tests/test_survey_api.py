from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.api import survey
from app.db.session import Base
from app.models.tables import RawDataset, ProcessedDataset, ProcessingJob


@pytest.fixture
def replay(monkeypatch):
    data = {"id": str(uuid4()), "name": "test.svlz", "crs": "EPSG:32605", "started_at": "2026-07-10T20:00:00+00:00",
            "source_sha256": "test", "warnings": [], "vertical_datum": "vehicle_origin_uncorrected",
            "frames": [{"t": 0, "points": [[1,1,-2,0,0,1],[2,1,-3,0,0,1],[1,2,-4,0,0,1],[2,2,-5,0,0,1]]},
                       {"t": 10, "points": [[3,3,-99,0,0,1]]}]}
    monkeypatch.setattr(survey, "load_replay", lambda _: data)
    return data


def test_export_contains_origin_and_no_future_points(replay):
    app = FastAPI(); app.include_router(survey.router)
    client = TestClient(app)
    result = client.post(f"/api/survey/replays/{replay['id']}/block.csv", json={"column":0,"row":0,"size":50,"until":0})
    assert result.status_code == 200
    assert "# projected_crs=EPSG:32605" in result.text
    assert "# origin_easting=0" in result.text
    assert all("-99" not in line for line in result.text.splitlines() if not line.startswith("#"))
    assert "x,y,z" in result.text


def test_invalid_size_and_empty_blocks_are_rejected(replay):
    app = FastAPI(); app.include_router(survey.router)
    client = TestClient(app)
    url = f"/api/survey/replays/{replay['id']}/block.csv"
    assert client.post(url,json={"column":0,"row":0,"size":0,"until":0}).status_code == 422
    assert client.post(url,json={"column":100,"row":100,"until":0}).status_code == 422


def test_identical_block_reuses_dataset_and_preserves_transform(replay, monkeypatch):
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    class Store:
        def put_bytes(self, *args): pass
    monkeypatch.setattr(survey, "store", Store)
    with Session(engine) as db:
        body = survey.BlockRequest(column=0,row=0,size=50,until=0)
        first = survey.import_block(replay["id"], body, db, None)
        second = survey.import_block(replay["id"], body, db, None)
        assert first["dataset_id"] == second["dataset_id"]
        assert second["existing"] is True
        assert db.query(RawDataset).count() == 1
        raw = db.get(RawDataset, first["dataset_id"])
        assert raw.coordinate_system_json["projected_crs"] == "EPSG:32605"
        assert raw.assets[0].file_name == "bathymetry_xyz.csv"


def test_map_cells_restore_only_completed_results_for_the_replay(replay):
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        ids=[]
        for until, status, replay_id in [(20,"completed",replay["id"]),(10,"completed",replay["id"]),(30,"failed",replay["id"]),(40,"completed",str(uuid4()))]:
            raw=RawDataset(source="survey_replay",metadata_json={"replay_id":replay_id,"block":{"column":1,"row":2,"size":50,"until":until}})
            db.add(raw);db.flush()
            processed=ProcessedDataset(raw_dataset_id=raw.id)
            db.add(processed);db.flush();ids.append(processed.id)
            db.add(ProcessingJob(raw_dataset_id=raw.id,status=status,result_processed_dataset_id=processed.id))
        db.commit()
        cells=survey.processed_blocks(replay["id"],db)
        assert len(cells)==1
        assert cells[0]["until"]==20
        assert cells[0]["result_processed_dataset_id"]==ids[0]


def test_reupload_same_recording_reuses_replay_and_legacy_match(replay, monkeypatch):
    from app.testing.fixtures import FakeObjectStore
    storage = FakeObjectStore()
    monkeypatch.setattr(survey, "store", lambda:storage)
    monkeypatch.setattr(survey, "decode_sonar", lambda data,name,**kwargs:dict(replay))
    first = survey.save_replay(b"same-recording", "one.svlz")
    second = survey.save_replay(b"same-recording", "renamed.svlz")
    assert first["id"] == second["id"]
    assert len(storage.objects) == 2
    assert survey.save_replay(b"different-recording", "one.svlz")["id"] != first["id"]
    engine = create_engine("sqlite://");Base.metadata.create_all(engine)
    with Session(engine) as db:
        raw = RawDataset(source="survey_replay",acquisition_started_at=survey.datetime.fromisoformat(replay["started_at"]),metadata_json={"source_sha256":first["source_sha256"],"replay_id":replay["id"]})
        db.add(raw);db.commit()
        assert survey.save_replay(b"same-recording", "one.svlz", db)["id"] == replay["id"]


def test_new_cell_snapshot_updates_existing_raw_and_retains_completed_snapshot(replay, monkeypatch):
    from app.testing.fixtures import FakeObjectStore
    storage=FakeObjectStore();monkeypatch.setattr(survey,"store",lambda:storage)
    engine=create_engine("sqlite://");Base.metadata.create_all(engine)
    with Session(engine) as db:
        body=survey.BlockRequest(column=0,row=0,size=50,until=0)
        first=survey.import_block(replay["id"],body,db,None)
        proc=ProcessedDataset(raw_dataset_id=first["dataset_id"],viewer_config_json={"block_snapshot":body.model_dump()})
        db.add(proc);db.flush()
        db.add(ProcessingJob(raw_dataset_id=first["dataset_id"],status="completed",result_processed_dataset_id=proc.id));db.commit()
        updated=survey.import_block(replay["id"],body.model_copy(update={"until":10}),db,None,overwrite=True)
        assert updated["dataset_id"] == first["dataset_id"]
        assert updated["job_id"] is None
        assert db.query(RawDataset).count() == 1
        assert survey.processed_blocks(replay["id"],db)[0]["until"] == 0
        assert b"-99" in next(iter(storage.objects.values()))


def test_reimport_updates_reference_metadata_even_when_xyz_is_unchanged(replay,monkeypatch):
    engine=create_engine('sqlite://');Base.metadata.create_all(engine)
    class Store:
        def put_bytes(self,*args):pass
    monkeypatch.setattr(survey,'store',Store)
    with Session(engine) as db:
        body=survey.BlockRequest(column=0,row=0,size=50,until=0)
        first=survey.import_block(replay['id'],body,db,None)
        replay['frames'][0]['vertical_samples']=[[1,1,8,4,2,2]]
        second=survey.import_block(replay['id'],body,db,None)
        assert first['dataset_id']==second['dataset_id']
        raw=db.get(RawDataset,first['dataset_id'])
        assert raw.coordinate_system_json['sea_level_reference']['vehicle_altitude_msl_m']==2
        assert second['job_id'] is None


def test_legacy_processed_cell_recovers_soundings_without_mesh_reprocessing(replay):
    from app.services.sea_levels import processed_sounding_reference
    from app.testing.fixtures import FakeObjectStore
    engine=create_engine('sqlite://');Base.metadata.create_all(engine)
    replay['frames'][0]['sounding_altitudes']=[[1,1,-20,18,1]]
    with Session(engine) as db:
        raw=RawDataset(id='r',metadata_json={'replay_id':replay['id'],'block':{'column':0,'row':0,'size':50,'until':0}})
        proc=ProcessedDataset(id='p',raw_dataset_id='r',status='completed')
        db.add_all([raw,proc]);db.commit()
        result=processed_sounding_reference(proc,db,FakeObjectStore(),lambda _:replay)
        assert result['points']==[[1,1,-20,18]]
        assert proc.assets==[]


@pytest.mark.parametrize("size_mb,accepted", [(101, True), (2048, True), (2049, False)])
def test_upload_limit_checks_file_size_without_reading_into_memory(monkeypatch, size_mb, accepted):
    from fastapi import HTTPException
    class Upload:
        def seek(self, offset, whence=0):
            return size_mb * 1024 * 1024 if whence == 2 else offset
        def read(self, *args):
            raise AssertionError("Upload must be passed to the streaming decoder")
    source = Upload()
    monkeypatch.setattr(survey.settings, "survey_upload_limit_mb", 2048)
    calls = []
    monkeypatch.setattr(survey, "save_replay", lambda *args: calls.append(args) or {"id":"ok"})
    if accepted:
        assert survey.save_uploaded_replay(source, "large.svlz", None, "", False) == {"id":"ok"}
        assert calls[0][0] is source
    else:
        with pytest.raises(HTTPException) as exc:
            survey.save_uploaded_replay(source, "large.svlz", None, "", False)
        assert exc.value.status_code == 413
        assert not calls


def test_streamed_recording_preserves_hash_and_stored_source(replay, monkeypatch):
    import io
    from app.testing.fixtures import FakeObjectStore
    class Storage(FakeObjectStore):
        def put_file(self, key, source, content_type):
            source.seek(0)
            self.put_bytes(key, source.read(1024), content_type)
    storage = Storage()
    monkeypatch.setattr(survey, "store", lambda: storage)
    def decode(source, name, **kwargs):
        if hasattr(source, "read"):
            assert source.read(1024) == b"same-recording"
        return dict(replay)
    monkeypatch.setattr(survey, "decode_sonar", decode)
    expected = survey.save_replay(b"same-recording", "one.svlog")
    streamed = survey.save_replay(io.BytesIO(b"same-recording"), "renamed.svlog")
    assert streamed["id"] == expected["id"]
    assert streamed["source_sha256"] == expected["source_sha256"]
    assert storage.objects[f"replays/{streamed['id']}/source.svlog"] == b"same-recording"


def test_playback_payload_omits_only_backend_reference_arrays(replay):
    replay['frames'][0]['sounding_altitudes'] = [[1,2,3,4]]
    replay['frames'][0]['vertical_samples'] = [[5,6]]
    payload = survey.playback_payload(replay)
    assert payload['frames'][0]['points'] == replay['frames'][0]['points']
    assert 'sounding_altitudes' not in payload['frames'][0]
    assert 'sounding_altitudes' in replay['frames'][0]


def test_compatible_upload_cache_skips_decoder(replay, monkeypatch):
    import hashlib, json
    from app.testing.fixtures import FakeObjectStore
    storage = FakeObjectStore()
    data = b'cached-recording'
    digest = hashlib.sha256(data).hexdigest()
    cached = {**replay, 'decoder_version':1, 'source_sha256':digest}
    storage.put_bytes(f'replay-cache/{digest}.json', json.dumps({'id':replay['id']}).encode())
    storage.put_bytes(f"replays/{replay['id']}/replay.json", json.dumps(cached).encode())
    monkeypatch.setattr(survey, 'store', lambda:storage)
    def unexpected(*args, **kwargs): raise AssertionError('Cached recording decoded again')
    monkeypatch.setattr(survey, 'decode_sonar', unexpected)
    result = survey.save_replay(data, 'renamed.svlog')
    assert result['source_sha256'] == digest
    assert result['name'] == 'renamed.svlog'


def test_legacy_upgrade_is_saved_across_memory_cache_clear(monkeypatch):
    import io, json
    from contextlib import closing
    from app.testing.fixtures import FakeObjectStore
    class Storage(FakeObjectStore):
        def get_bytes(self, key, progress=None): return super().get_bytes(key)
        def open_read(self, key): return closing(io.BytesIO(b'recording'))
        @property
        def client(self): return self
        bucket = 'test'
        def head_object(self, **kwargs): return {'ContentLength':9}
    storage = Storage()
    storage.put_bytes('replays/legacy/replay.json',json.dumps({'name':'legacy','frames':[{'t':0,'points':[]}]}).encode())
    monkeypatch.setattr(survey,'store',lambda:storage)
    calls=[]
    def decode(*args, **kwargs):
        calls.append(True)
        return {'frames':[{'t':0,'sounding_altitudes':[[1,2,-3,3]],'vertical_samples':[]}], 'motion_summary':{'samples':[]}}
    monkeypatch.setattr(survey,'decode_sonar',decode)
    survey.load_replay.cache_clear()
    try:
        first=survey.load_replay('legacy')
        survey.load_replay.cache_clear()
        second=survey.load_replay('legacy')
        assert first == second
        assert len(calls)==1
        assert 'replays/legacy/motion.json' in storage.objects
    finally: survey.load_replay.cache_clear()


def test_motion_uses_persisted_summary_without_recording_read(monkeypatch):
    import json
    from app.testing.fixtures import FakeObjectStore
    storage=FakeObjectStore()
    storage.put_bytes('replays/saved/motion.json',json.dumps({'samples':[{'t':1}]}).encode())
    monkeypatch.setattr(survey,'store',lambda:storage)
    monkeypatch.setattr(survey,'load_replay',lambda _: {'started_at':'2026-07-10T20:00:00Z'})
    survey.load_motion.cache_clear()
    try: assert survey.load_motion('saved')['samples']==[{'t':1}]
    finally: survey.load_motion.cache_clear()


@pytest.mark.parametrize('name', ['', '   ', 'x'*31])
def test_archive_rename_rejects_invalid_names(name):
    from pydantic import ValidationError
    with pytest.raises(ValidationError): survey.SurveyRename(name=name)


def test_archive_rename_updates_all_members_and_preserves_identity():
    from app.services.survey_archive import archive_surveys
    engine=create_engine('sqlite://');Base.metadata.create_all(engine)
    with Session(engine) as db:
        for i in range(2):
            db.add(RawDataset(id=f'r{i}',name=f'cell {i}',metadata_json={'source_sha256':'same','survey_name':'Old'}))
        db.commit()
        group=archive_surveys(db)[0]
        result=survey.archive_rename(group['id'],survey.SurveyRename(name='  New reef  '),db,None)
        assert result['name']=='New reef'
        updated=archive_surveys(db)[0]
        assert updated['id']==group['id']
        assert updated['name']=='New reef'
        assert len(updated['raw'])==2
        assert db.get(RawDataset,'r0').name=='cell 0'
