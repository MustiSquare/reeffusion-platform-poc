import pytest
from fastapi import HTTPException

from app.core.config import settings
from app.models.tables import ProcessedAsset, ProcessedDataset, ProcessingJob
from app.services.auth import require_role
from app.services.dataset_cleanup import delete_raw_dataset
from app.testing.fixtures import FakeObjectStore, create_raw_fixture_dataset, in_memory_session


def test_delete_raw_dataset_cleans_raw_processed_and_objects():
    db = in_memory_session()
    object_store = FakeObjectStore()
    raw = create_raw_fixture_dataset(db, object_store)
    processed = ProcessedDataset(raw_dataset_id=raw.id, name="Processed Fixture")
    db.add(processed)
    db.commit()
    processed_key = f"processed/{processed.id}/mesh.glb"
    object_store.put_bytes(processed_key, b"glTF", "model/gltf-binary")
    db.add(
        ProcessedAsset(
            dataset_id=processed.id,
            file_name="mesh.glb",
            object_key=processed_key,
            media_type="model/gltf-binary",
            asset_type="mesh_glb",
        )
    )
    db.add(ProcessingJob(raw_dataset_id=raw.id, result_processed_dataset_id=processed.id))
    db.commit()

    result = delete_raw_dataset(db, raw.id, object_store)

    assert result["deleted"] is True
    assert db.get(type(raw), raw.id) is None
    assert db.get(ProcessedDataset, processed.id) is None
    assert object_store.objects == {}
    assert f"raw/{raw.id}/" in object_store.deleted_prefixes
    assert f"processed/{processed.id}/" in object_store.deleted_prefixes


def test_role_guard_is_disabled_for_local_demo():
    original = settings.auth_enabled
    settings.auth_enabled = False
    try:
        principal = require_role("admin")()
        assert principal.role == "admin"
        assert principal.auth_enabled is False
    finally:
        settings.auth_enabled = original


def test_role_guard_rejects_editor_for_admin_operation():
    original = settings.auth_enabled
    settings.auth_enabled = True
    try:
        with pytest.raises(HTTPException) as exc:
            require_role("admin")(authorization=None, x_api_key=settings.auth_editor_token)
        assert exc.value.status_code == 403
    finally:
        settings.auth_enabled = original
