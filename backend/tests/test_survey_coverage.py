import json
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from app.db.session import Base
from app.models.tables import RawDataset, ProcessedDataset, ProcessedAsset
from app.testing.fixtures import FakeObjectStore
from app.services.survey_coverage import archive_coverage


def test_coverage_uses_measured_references_and_preserves_tile_gaps():
    engine=create_engine('sqlite://');Base.metadata.create_all(engine)
    storage=FakeObjectStore()
    with Session(engine) as db:
        raw=RawDataset(id='raw',metadata_json={'block':{'column':4000,'row':44000,'size':50,'until':10}})
        processed=ProcessedDataset(id='processed',raw_dataset_id='raw',coordinate_system_json={'projected_crs':'EPSG:32605','projected_origin':[200000,2200000]})
        db.add_all([raw,processed]);db.flush()
        db.add(ProcessedAsset(dataset_id='processed',asset_type='sounding_references',object_key='points',file_name='sounding_references.json'))
        db.commit()
        storage.put_bytes('points',json.dumps({'points':[[1,2,-10,10],[49,2,-11,11]]}).encode())
        summary={'raw':[{'id':'raw'}],'cells':[{'key':'4000:44000','column':4000,'row':44000,'size':50,'dataset_id':'processed'}]}
        result=archive_coverage(summary,db,storage,50)
        assert result['total_points']==2
        assert len(result['points'])==2
        assert [p[2] for p in result['points']]==[-10,-11]
        assert result['points'][0][0]<result['points'][1][0]
        assert not result['sampled']
        assert archive_coverage(summary,db,storage,100)['points']==[]
        limited=archive_coverage(summary,db,storage,50,limit=1)
        assert limited['sampled'] and len(limited['points'])==1
