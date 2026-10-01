import json
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy.orm import sessionmaker
from app.api import survey
from app.models.tables import RawDataset, ProcessedDataset, Annotation
from app.services import survey_repair as repair
from app.services import survey_xyz_export as exports
from app.services.survey_archive import archive_surveys
from test_survey_xyz_export import setup


def test_disk_bins_keep_weights_boundaries_and_coverage(tmp_path):
    bins = repair.DetectionBins(str(tmp_path/'bins.sqlite'))
    try:
        for _ in range(10000): bins.add(-.25,.5,-10,9,20,3)
        bins.add(.25,.5,-20,19,None,4)
        bins.add(.75,.5,-30,29,30,5)
        bins.flush()
        assert not bins.batch
        assert bins.cells(50)==[(-1,0),(0,0)]
        frame=bins.frame(0,0,50)
        assert frame['points'][0][:3]==[.5,.5,-25]
        assert frame['points'][0][5]==2
        assert frame['sounding_altitudes'][0][3]==24
        assert frame['vertical_samples'][0][2:]==[30,1,30,30]
        footprint=bins.coverage('EPSG:32605')
        assert footprint['occupied_square_metres']==2
        assert len(footprint['polygons'])==1
    finally: bins.db.close()


def test_interrupted_spool_cleanup_is_scoped_to_the_survey(tmp_path,monkeypatch):
    replay_id=str(uuid4())
    abandoned=tmp_path/f'survey-repair-{replay_id}-interrupted';abandoned.mkdir()
    (abandoned/'bins.sqlite').write_bytes(b'interrupted')
    other=tmp_path/f'survey-repair-{uuid4()}-active';other.mkdir()
    (other/'keep').write_bytes(b'other survey')
    monkeypatch.setattr(repair.tempfile,'gettempdir',lambda:str(tmp_path))
    repair.discard_interrupted_spools(replay_id)
    assert not abandoned.exists() and (other/'keep').exists()


def test_repair_lease_duplicates_interruption_and_export_conflict(setup):
    db, storage, queue, summary, raw=setup
    jobs=[]
    first=repair.start(summary,db,storage,lambda *args:jobs.append(args))
    assert first['status']=='queued'
    assert repair.start(summary,db,storage,lambda *args:jobs.append(args))['status']=='queued'
    assert len(jobs)==1
    with pytest.raises(HTTPException): exports.start_export(summary,db,storage,lambda *args:None)
    with pytest.raises(HTTPException): exports.check_deletion(db,raw)
    queue.values.pop(exports.keys(raw.metadata_json['replay_id'])[0])
    assert repair.status(summary,db,storage)['status']=='failed'
    repair.start(summary,db,storage,lambda *args:jobs.append(args))
    assert len(jobs)==2
    repair.run(*jobs[0],storage,sessionmaker(bind=db.bind))  # Stale delivery cannot publish.
    assert repair.status(summary,db,storage)['status']=='queued'


def test_sparse_full_recording_rebuild_preserves_legacy_and_annotations(setup,monkeypatch):
    db,storage,queue,summary,raw=setup
    monkeypatch.setattr(survey,'store',lambda:storage)
    processed=ProcessedDataset(raw_dataset_id=raw.id,name='old',status='completed')
    db.add(processed);db.flush()
    annotation=Annotation(processed_dataset_id=processed.id,label='original',geometry_json={'position':[1,2,3]})
    combined=ProcessedDataset(name='old combined',viewer_config_json={'source_dataset_ids':[processed.id]})
    db.add(combined);db.flush()
    nested=ProcessedDataset(name='nested combined',viewer_config_json={'source_dataset_ids':[combined.id]})
    db.add(nested)
    db.add(annotation);db.commit()
    jobs=[]
    repair.start(summary,db,storage,lambda *args:jobs.append(args))
    repair.run(*jobs[0],storage,sessionmaker(bind=db.bind))
    db.expire_all()
    state=repair.status(summary,db,storage)
    assert state['status']=='completed' and state['point_count']==1 and state['sparse_cells']==1
    assert not repair.visible(raw) and not repair.visible(processed)
    assert not repair.visible(combined) and not repair.visible(nested)
    assert annotation.geometry_json=={'position':[1,2,3]}
    active=[r for r in db.query(RawDataset) if repair.visible(r)]
    assert len(active)==1 and active[0].id!=raw.id
    assert active[0].metadata_json['coordinate_version']==2
    group=next(g for g in archive_surveys(db) if any(r['id']==active[0].id for r in g['raw']))
    assert group['received_cells']==1 and group['processed_cells']==0
    assert json.loads(storage.get_bytes(state['coverage_key']))['occupied_square_metres']==1
    assert not queue.exists(exports.keys(raw.metadata_json['replay_id'])[0])


def test_repair_failure_retains_active_results_and_releases_lease(setup,monkeypatch):
    db,storage,queue,summary,raw=setup
    jobs=[];repair.start(summary,db,storage,lambda *args:jobs.append(args))
    def fail(*args,**kwargs): raise ValueError('injected decoding error')
    monkeypatch.setattr(repair,'decode_detections',fail)
    with pytest.raises(ValueError):repair.run(*jobs[0],storage,sessionmaker(bind=db.bind))
    db.expire_all()
    assert repair.visible(raw)
    assert repair.status(summary,db,storage)['status']=='failed'
    assert not queue.exists(exports.keys(raw.metadata_json['replay_id'])[0])


def test_activation_is_fenced_against_newer_repair(setup):
    db,storage,queue,summary,raw=setup
    raw.metadata_json={**raw.metadata_json,'repair_job':'newer'};db.commit()
    with pytest.raises(RuntimeError):repair.activate(db,raw.metadata_json['replay_id'],'older',set(),{})
    assert repair.visible(raw)


def test_old_coordinate_export_manifest_cannot_be_reused(setup):
    db,storage,queue,summary,raw=setup
    source=exports.source_for(summary,db,storage)
    storage.put_bytes(exports.prefix(source['replay_id'])+'/manifest.json',json.dumps({
        'format_version':exports.VERSION,'coordinate_version':1,'source_sha256':source['source_sha256']}).encode())
    assert exports.cached_export(storage,source) is None


def test_surface_generation_stays_hidden_until_all_cells_succeed(setup,monkeypatch):
    from app.models.tables import ProcessingJob
    from app.processing import pipeline
    db,storage,queue,summary,raw=setup
    monkeypatch.setattr(survey,'store',lambda:storage)
    def decode(source,name,sink,progress=None,detailed_sink=None):
        for x in [500001,500002,500051,500052]:
            for y in [2200001,2200002]:detailed_sink(x,y,-5,5,None,20)
        return {'coordinate_version':2,'crs':'EPSG:32605','point_count':8,'partial':False,'warnings':[],
                'skipped':{},'started_at':'2026-07-10T00:00:00+00:00','vertical_datum':'vehicle_origin_uncorrected'}
    monkeypatch.setattr(repair,'decode_detections',decode)
    processed_ids=[]
    def process(session,job_id):
        job=session.get(ProcessingJob,job_id);new=session.get(RawDataset,job.raw_dataset_id)
        assert not repair.visible(new)
        assert repair.visible(session.get(RawDataset,raw.id))
        assert all(not repair.visible(session.get(ProcessedDataset,id)) for id in processed_ids)
        proc=ProcessedDataset(raw_dataset_id=new.id,name='corrected',status='completed',viewer_config_json={'generation_state':'staged'})
        session.add(proc);session.flush();processed_ids.append(proc.id)
        new.status='processed';job.status='completed';job.result_processed_dataset_id=proc.id;session.commit()
    monkeypatch.setattr(pipeline,'run_processing_pipeline',process)
    jobs=[];repair.start(summary,db,storage,lambda *args:jobs.append(args))
    repair.run(*jobs[0],storage,sessionmaker(bind=db.bind))
    db.expire_all()
    assert len(processed_ids)==2
    assert not repair.visible(raw)
    assert all(repair.visible(db.get(ProcessedDataset,id)) for id in processed_ids)
    group=archive_surveys(db)[0]
    assert group['processed_cells']==2
