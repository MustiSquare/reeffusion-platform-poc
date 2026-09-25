from datetime import datetime, timezone, timedelta
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from app.db.session import Base
from app.models.tables import RawDataset, ProcessedDataset
from app.services.survey_archive import archive_surveys, aggregate_conditions


def test_unique_cells_latest_completed_snapshot_and_combined_membership():
    engine=create_engine('sqlite://')
    Base.metadata.create_all(engine)
    start=datetime(2026,7,10,20,tzinfo=timezone.utc)
    with Session(engine) as db:
        for i,size in enumerate([50,50,100]):
            block=dict(size=size,column=10000,row=22000,until=i+1)
            db.add(RawDataset(id=f'r{i}',name='cell',acquisition_started_at=start,acquisition_ended_at=start+timedelta(seconds=i+1),
                coordinate_system_json={'projected_crs':'EPSG:32605'},metadata_json={'source_sha256':'abc','survey_name':'Alpha','block':block}))
            db.add(ProcessedDataset(id=f'p{i}',name='result',raw_dataset_id=f'r{i}',status='completed',viewer_config_json={'block_snapshot':block}))
        db.add(ProcessedDataset(id='combined',name='area',viewer_config_json={'source_dataset_ids':['p0','p1']}))
        db.add(RawDataset(id='manual',name='Manual data'))
        db.commit()
        groups=archive_surveys(db)
        g=next(g for g in groups if g['name']=='Alpha')
        assert g['received_cells']==g['processed_cells']==2
        assert len(g['processed'])==4
        assert next(c for c in g['cells'] if c['size']==50)['dataset_id']=='p1'
        assert len(g['cells'][0]['footprint'])==4
        assert -180<=g['location']['longitude']<=180
        assert g['duration_seconds']==3
        manual=next(g for g in groups if g['name']=='Manual data')
        assert manual['cells']==[] and manual['location'] is None
        assert g['id']==next(s['id'] for s in archive_surveys(db) if s['name']=='Alpha')


def conditions(directions):
    def provider(lat,lon,day):
        return {'weather':{'hourly':{'wind_speed_10m':[10]*24,'wind_direction_10m':directions},'units':{'wind_speed_10m':'km/h'}},
                'marine':{'hourly':{'wave_height':[None,2]+[1]*22}}}
    return provider


def test_conditions_direction_wrap_missing_data_and_calm():
    summary={'location':{'latitude':20,'longitude':-156},'started_at':'2026-07-10T00:30:00+00:00','ended_at':'2026-07-10T02:00:00+00:00'}
    result=aggregate_conditions(summary,conditions([350,10]+[0]*22))
    assert min(result['wind_from_degrees'],360-result['wind_from_degrees'])<1e-6
    assert result['expected_hours']==2 and result['wave_hours']==1 and result['partial']
    assert result['wave_height_range']==[2,2]
    result=aggregate_conditions(summary,conditions([0,180]+[0]*22))
    assert result['wind_from_degrees'] is None
    assert result['wind_direction_label']=='Variable / calm'
    assert not aggregate_conditions({**summary,'location':None},conditions([]))['available']


def test_conditions_cross_midnight_queries_both_days():
    summary={'location':{'latitude':20,'longitude':-156},'started_at':'2026-07-10T23:30:00+00:00','ended_at':'2026-07-11T00:30:00+00:00'}
    calls=[]
    def provider(lat,lon,day):
        calls.append(day)
        return conditions([90]*24)(lat,lon,day)
    assert aggregate_conditions(summary,provider)['expected_hours']==2
    assert calls==['2026-07-10','2026-07-11']


def test_delete_entire_survey_cleans_all_members_and_preserves_other_surveys(monkeypatch,tmp_path):
    from uuid import uuid4
    from app.core.config import settings
    from app.services.dataset_cleanup import delete_archived_survey
    from app.testing.fixtures import in_memory_session, FakeObjectStore, create_raw_fixture_dataset
    from app.models.tables import ProcessingJob
    monkeypatch.setattr(settings,'processed_export_dir',str(tmp_path))
    db,storage=in_memory_session(),FakeObjectStore()
    replay_id=str(uuid4())
    raws=[create_raw_fixture_dataset(db,storage) for _ in range(3)]
    for raw in raws[:2]:raw.metadata_json={'replay_id':replay_id,'survey_name':'Delete this survey'}
    results=[ProcessedDataset(raw_dataset_id=r.id,name='Cell') for r in raws]
    db.add_all(results);db.flush()
    combined=ProcessedDataset(name='Combined',viewer_config_json={'source_dataset_ids':[r.id for r in results[:2]]})
    db.add(combined);db.commit()
    for result in [*results,combined]:
        storage.put_bytes(f'processed/{result.id}/mesh.glb',b'mesh')
        directory=tmp_path/'2026-07-10'/'processed'/result.id
        directory.mkdir(parents=True);(directory/'mesh.glb').write_bytes(b'mesh')
    storage.put_bytes(f'replays/{replay_id}/original.svlz',b'sonar')
    group=next(g for g in archive_surveys(db) if g['name']=='Delete this survey')
    response=delete_archived_survey(db,group,storage)
    assert response['deleted']
    assert db.query(RawDataset).count()==1
    assert db.query(ProcessedDataset).count()==1
    assert db.get(ProcessedDataset,results[2].id)
    assert not any(k.startswith(f'replays/{replay_id}/') for k in storage.objects)
    assert len(list(tmp_path.glob('*/processed/*')))==1
    assert storage.objects[f'processed/{results[2].id}/mesh.glb']==b'mesh'


def test_survey_deletion_checks_all_jobs_before_any_files_are_deleted():
    import pytest
    from fastapi import HTTPException
    from app.models.tables import ProcessingJob
    from app.services.dataset_cleanup import delete_archived_survey
    from app.testing.fixtures import in_memory_session, FakeObjectStore, create_raw_fixture_dataset
    db,storage=in_memory_session(),FakeObjectStore()
    raws=[create_raw_fixture_dataset(db,storage) for _ in range(2)]
    db.add(ProcessingJob(raw_dataset_id=raws[1].id,status='running'));db.commit()
    original=dict(storage.objects)
    with pytest.raises(HTTPException) as error:
        delete_archived_survey(db,{'id':'test','raw':[{'id':r.id} for r in raws],'processed':[]},storage)
    assert error.value.status_code==409
    assert storage.objects==original and db.query(RawDataset).count()==2


def test_archive_map_rejects_unprocessed_survey_and_delete_requires_confirmation():
    import pytest
    from fastapi import HTTPException
    from app.api.survey import archive_detail,archive_delete
    from app.testing.fixtures import in_memory_session, FakeObjectStore, create_raw_fixture_dataset
    db=in_memory_session();create_raw_fixture_dataset(db,FakeObjectStore())
    group=archive_surveys(db)[0]
    with pytest.raises(HTTPException) as error:archive_detail(group['id'],db)
    assert error.value.status_code==409
    with pytest.raises(HTTPException) as error:archive_delete(group['id'],db,False,None)
    assert error.value.status_code==400
    assert db.query(RawDataset).count()==1
