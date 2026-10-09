import io
import json
import numpy as np
import pytest
from sqlalchemy.orm import sessionmaker
from fastapi import HTTPException
from app.services import raw_points as raw
from app.services import survey_xyz_export as exports
from app.services.survey_replay import decode_detections
from test_survey_xyz_export import setup, repeated_recording


def test_full_index_preserves_repeats_and_exceeds_preview_limit(tmp_path):
    spool = raw.TileSpool(tmp_path)
    meta = decode_detections(io.BytesIO(repeated_recording()), 'recording.svlog', spool.add)
    payloads = {}
    index = spool.publish(lambda name, data: payloads.setdefault(name, data))
    assert index['point_count'] == meta['point_count'] == 504000
    assert max(c['count'] for c in index['chunks']) <= 100000
    assert sum(c['count'] for c in index['chunks']) == 504000
    for c in index['chunks']:
        points = np.frombuffer(payloads[c['id']], dtype='<f4').reshape(-1, 3) + c['origin']
        assert np.all(points[:, 2] < 0)
        assert np.max(np.abs(points - points[0])) < .001


def test_boundaries_precision_overview_and_empty(tmp_path, monkeypatch):
    monkeypatch.setattr(raw, 'OVERVIEW_POINTS', 4)
    original = np.array([[500000,2200000,-40.123], [499999.999,2199999.999,-8.333],
                         [500025,2200025,-3], [500000,2200000,-40.123], [500024.999,2200024.999,-.2]])
    spool = raw.TileSpool(tmp_path)
    for p in original: spool.add(*p)
    payloads = {}
    result = spool.publish(lambda key,data:payloads.setdefault(key,data))
    recovered = np.concatenate([np.frombuffer(payloads[c['id']],dtype='<f4').reshape(-1,3)+c['origin'] for c in result['chunks']])
    assert sorted(map(tuple,np.round(recovered,3))) == sorted(map(tuple,original))
    assert result['overview_count'] <= 4
    assert len(result['overview']) == len(spool.tiles)
    assert result['min'] == list(original.min(axis=0))
    assert result['max'] == list(original.max(axis=0))
    empty = raw.TileSpool(tmp_path/'empty')
    with pytest.raises(ValueError,match='No valid'): empty.publish(lambda *_:None)


def test_job_duplicate_deletion_cache_and_retry(setup):
    db, storage, queue, summary, row = setup
    calls=[]
    state=raw.start(summary,db,storage,lambda *args:calls.append(args))
    assert state['status']=='queued'
    raw.start(summary,db,storage,lambda *args:calls.append(args))
    assert len(calls)==1
    with pytest.raises(HTTPException):exports.check_deletion(db,row)
    raw.run(*calls[0],storage,sessionmaker(bind=db.get_bind()))
    source=calls[0][0]
    assert raw.status(source,storage)['status']=='completed'
    manifest=raw.cached(source,storage)
    assert manifest['point_count']==1
    assert not queue.exists(exports.keys(source['replay_id'])[0])
    raw.start(summary,db,storage,lambda *args:calls.append(args))
    assert len(calls)==1
    assert raw.cached({**source,'source_sha256':'changed'},storage) is None
    exports.check_deletion(db,row)


def test_interruption_and_failed_worker_allow_retry(setup,monkeypatch):
    db,storage,queue,summary,row=setup
    calls=[]
    raw.start(summary,db,storage,lambda *args:calls.append(args))
    source,token=calls[0]
    queue.values.pop(exports.keys(source['replay_id'])[0])
    assert raw.status(source,storage)['status']=='failed'
    raw.start(summary,db,storage,lambda *args:calls.append(args))
    assert len(calls)==2
    monkeypatch.setattr(raw,'decode_detections',lambda *a,**k:(_ for _ in ()).throw(ValueError('test failure')))
    raw.run(*calls[1],storage,sessionmaker(bind=db.get_bind()))
    assert raw.status(source,storage)['status']=='failed'
    assert not queue.exists(exports.keys(source['replay_id'])[0])
    raw.start(summary,db,storage,lambda *args:calls.append(args))
    assert len(calls)==3


def test_missing_source_and_partial_metadata(setup,monkeypatch):
    db,storage,queue,summary,row=setup
    assert raw.status(None,storage)['status']=='unavailable'
    real=raw.decode_detections
    def partial(*a,**kw):return {**real(*a,**kw),'partial':True,'warnings':['Truncated recording']}
    monkeypatch.setattr(raw,'decode_detections',partial)
    calls=[];raw.start(summary,db,storage,lambda *args:calls.append(args))
    raw.run(*calls[0],storage,sessionmaker(bind=db.get_bind()))
    manifest=raw.cached(calls[0][0],storage)
    assert manifest['partial'] and manifest['warnings']==['Truncated recording']


def test_chunk_endpoint_streams_only_manifest_members(setup,monkeypatch):
    import asyncio
    from app.api import survey
    db,storage,queue,summary,row=setup
    calls=[];raw.start(summary,db,storage,lambda *args:calls.append(args))
    raw.run(*calls[0],storage,sessionmaker(bind=db.get_bind()))
    monkeypatch.setattr(survey,'store',lambda:storage)
    manifest=survey.raw_points_manifest(summary['id'],db)
    assert 'generation' not in manifest
    response=survey.raw_points_chunk(summary['id'],manifest['chunks'][0]['id'],db)
    async def read():return b''.join([data async for data in response.body_iterator])
    data=asyncio.run(read())
    assert len(data)==int(response.headers['content-length'])==12
    with pytest.raises(HTTPException) as error:survey.raw_points_chunk(summary['id'],'../../source.svlz',db)
    assert error.value.status_code==404


def test_source_resolution_follows_combined_cells(setup,monkeypatch):
    from app.api import survey
    from app.models.tables import ProcessedDataset
    db,storage,queue,summary,row=setup
    first=ProcessedDataset(name='Cell one',raw_dataset_id=row.id,viewer_config_json={'block_snapshot':{'column':20000,'row':88000,'size':25}})
    second=ProcessedDataset(name='Cell two',raw_dataset_id=row.id,viewer_config_json={'block_snapshot':{'column':20002,'row':88000,'size':25}})
    db.add_all([first,second]);db.commit()
    combined=ProcessedDataset(name='Combined',viewer_config_json={'source_dataset_ids':[first.id,second.id]})
    db.add(combined);db.commit()
    monkeypatch.setattr(survey,'store',lambda:storage)
    result=survey.raw_point_source(combined.id,db)
    assert result['survey_id']==summary['id']
    assert len(result['surveys'])==1
    assert sorted(result['areas'])==[[500000,2200000,500025,2200025],[500050,2200000,500075,2200025]]
    assert survey.raw_point_source(first.id,db)['areas']==[[500000,2200000,500025,2200025]]
