from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.models.tables import (
    Annotation,
    ComparisonResult,
    ModelRun,
    ProcessedAsset,
    ProcessedDataset,
    ProcessingJob,
    RawAsset,
    RawDataset,
)


def _delete_objects(object_store, keys: list[str], prefixes: list[str]) -> list[str]:
    deleted: list[str] = []
    for key in keys:
        if key:
            object_store.delete_key(key)
            deleted.append(key)
    for prefix in prefixes:
        if prefix:
            object_store.delete_prefix(prefix)
            deleted.append(f"{prefix}*")
    return deleted


def delete_processed_dataset(db: Session, dataset_id: str, object_store) -> dict:
    dataset = db.get(ProcessedDataset, dataset_id)
    if not dataset:
        return {"deleted": False, "reason": "not_found"}

    object_keys = [asset.object_key for asset in dataset.assets or []]
    deleted_objects = _delete_objects(object_store, object_keys, [f"processed/{dataset.id}/"])

    db.query(Annotation).filter_by(processed_dataset_id=dataset.id).delete(synchronize_session=False)
    db.query(ModelRun).filter_by(processed_dataset_id=dataset.id).delete(synchronize_session=False)
    db.query(ComparisonResult).filter(
        or_(ComparisonResult.dataset_a_id == dataset.id, ComparisonResult.dataset_b_id == dataset.id)
    ).delete(synchronize_session=False)
    db.delete(dataset)
    db.commit()
    return {"deleted": True, "dataset_id": dataset_id, "object_keys": deleted_objects}


def delete_raw_dataset(db: Session, dataset_id: str, object_store) -> dict:
    dataset = db.get(RawDataset, dataset_id)
    if not dataset:
        return {"deleted": False, "reason": "not_found"}

    processed_ids = [row.id for row in db.query(ProcessedDataset.id).filter_by(raw_dataset_id=dataset.id).all()]
    processed_results = [delete_processed_dataset(db, processed_id, object_store) for processed_id in processed_ids]
    dataset = db.get(RawDataset, dataset_id)
    object_keys = [asset.object_key for asset in dataset.assets or []]
    deleted_objects = _delete_objects(object_store, object_keys, [f"raw/{dataset.id}/"])

    db.query(ModelRun).filter_by(raw_dataset_id=dataset.id).delete(synchronize_session=False)
    db.query(ProcessingJob).filter_by(raw_dataset_id=dataset.id).delete(synchronize_session=False)
    db.delete(dataset)
    db.commit()
    return {
        "deleted": True,
        "dataset_id": dataset_id,
        "object_keys": deleted_objects,
        "processed": processed_results,
    }
