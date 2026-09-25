import asyncio
import inspect
import io
from starlette.datastructures import UploadFile
from app.api import routes
from app.models.tables import RawDataset
from app.testing.fixtures import FakeObjectStore, in_memory_session, SAMPLE_BATHYMETRY_XYZ


def test_manual_upload_reuses_content_but_not_same_name_with_different_content(monkeypatch):
    db, storage = in_memory_session(), FakeObjectStore()
    monkeypatch.setattr(routes,"store",lambda:storage)
    def upload(data,name):
        kwargs={key:None for key in inspect.signature(routes.upload).parameters if key not in ("files","db")}
        return asyncio.run(routes.upload(files=[UploadFile(filename=name,file=io.BytesIO(data))],db=db,**kwargs))
    first=upload(SAMPLE_BATHYMETRY_XYZ,"survey.xyz")
    second=upload(SAMPLE_BATHYMETRY_XYZ,"renamed.xyz")
    assert first["dataset_id"] == second["dataset_id"]
    assert second["existing"] is True
    third=upload(SAMPLE_BATHYMETRY_XYZ.replace(b"-4",b"-5"),"survey.xyz")
    assert third["dataset_id"] != first["dataset_id"]
    assert db.query(RawDataset).count() == 2


def test_matching_data_and_date_requires_confirmation_and_can_be_renamed(monkeypatch):
    import pytest
    from fastapi import HTTPException
    from app.models.tables import ProcessedDataset
    db, storage = in_memory_session(), FakeObjectStore()
    monkeypatch.setattr(routes,"store",lambda:storage)
    def upload(name, date, confirmed=False):
        kwargs={key:None for key in inspect.signature(routes.upload).parameters if key not in ("files","db")}
        kwargs.update(survey_name=name,acquisition_started_at=date,overwrite=confirmed)
        return asyncio.run(routes.upload(files=[UploadFile(filename="same.xyz",file=io.BytesIO(SAMPLE_BATHYMETRY_XYZ))],db=db,**kwargs))
    first=upload("First survey","2026-07-10T12:00:00Z")
    db.add(ProcessedDataset(raw_dataset_id=first["dataset_id"]));db.commit()
    before=dict(storage.objects)
    with pytest.raises(HTTPException) as error: upload("New label","2026-07-10T12:00:00Z")
    assert error.value.status_code == 409
    assert error.value.detail["processed_at"]
    assert db.get(RawDataset,first["dataset_id"]).name == "First survey"
    assert storage.objects == before
    accepted=upload("New label","2026-07-10T12:00:00Z",True)
    assert accepted["dataset_id"] == first["dataset_id"]
    assert accepted["name"] == "New label"
    different_date=upload("New date","2026-07-11T12:00:00Z")
    assert different_date["dataset_id"] != first["dataset_id"]
