import io
import numpy as np
import pytest
import trimesh
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from app.db.session import Base
from app.models.tables import ProcessedDataset, ProcessedAsset, Annotation
from app.services import combined_survey

class Store:
    def __init__(self): self.data = {}
    def put_bytes(self, key, data, *args): self.data[key] = data
    def get_bytes(self, key): return self.data[key]
    def delete_key(self, key): self.data.pop(key, None)

@pytest.fixture
def fixture(monkeypatch):
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    monkeypatch.setattr(combined_survey, "record_export", lambda *args: None)
    storage = Store()
    with Session(engine) as db:
        for i, origin in enumerate(([500000, 2000000], [500050, 2000050])):
            key = f"mesh-{i}"
            mesh = trimesh.Trimesh(vertices=[[0,0,-2],[1,0,-2],[0,1,-2]], faces=[[0,1,2]], process=False)
            storage.put_bytes(key, mesh.export(file_type="glb"))
            db.add(ProcessedDataset(id=str(i), coordinate_system_json={"projected_crs":"EPSG:32605", "projected_origin":origin, "vertical_datum":"vehicle_origin_uncorrected"}))
            db.add(ProcessedAsset(dataset_id=str(i), asset_type="mesh_glb", object_key=key))
        db.add(Annotation(processed_dataset_id="1", label="coral", annotation_type="point", geometry_json={"type":"Point", "coordinates":[.2,.3,-2]}))
        db.commit()
        yield db, storage

def test_combined_mesh_preserves_gaps_coordinates_annotations_and_reuses_result(fixture):
    db, storage = fixture
    result = combined_survey.combine_datasets(["1", "0"], db, storage)
    dataset = db.get(ProcessedDataset, result["dataset_id"])
    asset = next(a for a in dataset.assets if a.asset_type == "mesh_glb")
    mesh = trimesh.load(io.BytesIO(storage.get_bytes(asset.object_key)), file_type="glb", force="mesh")
    assert len(mesh.faces) == 2  # no triangles bridging the two cells
    np.testing.assert_allclose(mesh.bounds, [[0,0,-2],[51,51,-2]])
    assert dataset.metrics_json["surface_area"] == 1
    ann = db.query(Annotation).filter_by(processed_dataset_id=dataset.id).one()
    assert ann.geometry_json["coordinates"] == [50.2,50.3,-2]
    original = db.query(Annotation).filter_by(processed_dataset_id="1").one()
    assert original.geometry_json["coordinates"] == [.2,.3,-2]
    assert combined_survey.combine_datasets(["0","1"], db, storage) == result
    assert db.query(ProcessedDataset).count() == 3
    assert db.query(Annotation).count() == 2
    points = next(a for a in dataset.assets if a.asset_type == "point_cloud_xyz")
    xyz = np.loadtxt(io.BytesIO(storage.get_bytes(points.object_key)), delimiter=",", skiprows=1)
    assert xyz.shape == (6,3)

@pytest.mark.parametrize('coords', [
    {"projected_crs":"EPSG:32705","projected_origin":[0,0],"vertical_datum":"vehicle_origin_uncorrected"},
    {"projected_crs":"EPSG:32605","projected_origin":[0,0],"vertical_datum":"MSL"},
    {"projected_crs":"EPSG:32605","projected_origin":[0,float("inf")],"vertical_datum":"vehicle_origin_uncorrected"},
])
def test_rejects_incompatible_or_invalid_coordinates(fixture, coords):
    db, storage = fixture
    db.get(ProcessedDataset,"1").coordinate_system_json = coords
    db.commit()
    with pytest.raises(HTTPException) as error:
        combined_survey.combine_datasets(["0","1"], db, storage)
    assert error.value.status_code == 422
    assert db.query(ProcessedDataset).count() == 2

def test_selection_limit_and_missing_result(fixture):
    db, storage = fixture
    for ids in ([], [str(i) for i in range(21)]):
        with pytest.raises(HTTPException) as error:
            combined_survey.combine_datasets(ids, db, storage)
        assert error.value.status_code == 422
    with pytest.raises(HTTPException) as error:
        combined_survey.combine_datasets(["0", "missing"], db, storage)
    assert error.value.status_code == 404


def test_combined_refreshes_in_place_after_source_reprocessing(fixture):
    db, storage = fixture
    result=combined_survey.combine_datasets(["0","1"],db,storage)
    combined=db.get(ProcessedDataset,result["dataset_id"])
    asset_ids={a.asset_type:a.id for a in combined.assets}
    source=db.get(ProcessedDataset,"1")
    source.viewer_config_json={"revision":"new-run"};db.commit()
    again=combined_survey.combine_datasets(["0","1"],db,storage)
    assert again == result
    assert combined.viewer_config_json["source_revisions"]["1"] == "new-run"
    assert {a.asset_type:a.id for a in combined.assets} == asset_ids
    assert db.query(ProcessedDataset).count() == 3
    assert db.query(Annotation).count() == 2


def test_combined_sounding_references_translate_xy_and_preserve_z_altitude(fixture):
    import json
    db,storage=fixture
    for i in range(2):
        key=f'references-{i}'
        storage.put_bytes(key,json.dumps({'version':2,'points':[[.2,.3,-20,18]]}).encode())
        db.add(ProcessedAsset(dataset_id=str(i),asset_type='sounding_references',object_key=key))
    db.commit()
    result=combined_survey.combine_datasets(['0','1'],db,storage)
    d=db.get(ProcessedDataset,result['dataset_id'])
    asset=next(a for a in d.assets if a.asset_type=='sounding_references')
    points=json.loads(storage.get_bytes(asset.object_key))['points']
    assert points==[[.2,.3,-20,18],[50.2,50.3,-20,18]]
