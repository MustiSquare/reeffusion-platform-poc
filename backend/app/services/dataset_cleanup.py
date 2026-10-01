from pathlib import Path
from uuid import UUID
import shutil
from fastapi import HTTPException
from app.core.config import settings
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
    SurveyLocation,
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


def _remove_local_exports(dataset_id):
    root = Path(settings.processed_export_dir).resolve()
    for candidate in root.glob(f"*/processed/{UUID(dataset_id)}"):
        resolved = candidate.resolve()
        if not resolved.is_relative_to(root) or resolved.name != str(UUID(dataset_id)):
            raise ValueError("Invalid local export path")
        shutil.rmtree(resolved)


def _check_active(db, raw_id):
    if raw_id:
        raw = db.query(RawDataset).filter_by(id=raw_id).populate_existing().with_for_update().first()
        if raw:
            from app.services.survey_xyz_export import check_deletion
            check_deletion(db, raw)
    if raw_id and db.query(ProcessingJob).filter(ProcessingJob.raw_dataset_id == raw_id,
            ProcessingJob.status.notin_(["completed", "failed"])).first():
        raise HTTPException(409, "Wait for processing to finish before deleting this dataset")


def delete_processed_dataset(db: Session, dataset_id: str, object_store, *, commit=True) -> dict:
    dataset = db.get(ProcessedDataset, dataset_id)
    if not dataset:
        return {"deleted": False, "reason": "not_found"}

    _check_active(db, dataset.raw_dataset_id)
    for derived in db.query(ProcessedDataset).all():
        if dataset_id in (derived.viewer_config_json or {}).get("source_dataset_ids", []):
            delete_processed_dataset(db, derived.id, object_store, commit=False)
    object_keys = [asset.object_key for asset in dataset.assets or []]
    deleted_objects = _delete_objects(object_store, object_keys, [f"processed/{dataset.id}/"])
    _remove_local_exports(dataset_id)
    for job in db.query(ProcessingJob).filter_by(result_processed_dataset_id=dataset_id).all():
        job.result_processed_dataset_id = None
        job.status = "failed"
        job.error = "Processed result deleted from archive"

    db.query(Annotation).filter_by(processed_dataset_id=dataset.id).delete(synchronize_session=False)
    db.query(ModelRun).filter_by(processed_dataset_id=dataset.id).delete(synchronize_session=False)
    db.query(ComparisonResult).filter(
        or_(ComparisonResult.dataset_a_id == dataset.id, ComparisonResult.dataset_b_id == dataset.id)
    ).delete(synchronize_session=False)
    db.delete(dataset)
    db.flush()
    if commit: db.commit()
    return {"deleted": True, "dataset_id": dataset_id, "object_keys": deleted_objects}


def delete_raw_dataset(db: Session, dataset_id: str, object_store, *, commit=True) -> dict:
    dataset = db.get(RawDataset, dataset_id)
    if not dataset:
        return {"deleted": False, "reason": "not_found"}

    _check_active(db, dataset_id)
    replay_id = (dataset.metadata_json or {}).get("replay_id")
    processed_ids = [row.id for row in db.query(ProcessedDataset.id).filter_by(raw_dataset_id=dataset.id).all()]
    processed_results = [delete_processed_dataset(db, processed_id, object_store, commit=False) for processed_id in processed_ids]
    dataset = db.get(RawDataset, dataset_id)
    object_keys = [asset.object_key for asset in dataset.assets or []]
    deleted_objects = _delete_objects(object_store, object_keys, [f"raw/{dataset.id}/"])

    db.query(ModelRun).filter_by(raw_dataset_id=dataset.id).delete(synchronize_session=False)
    db.query(ProcessingJob).filter_by(raw_dataset_id=dataset.id).delete(synchronize_session=False)
    db.delete(dataset)
    db.flush()
    if commit: db.commit()
    if replay_id and not any((r.metadata_json or {}).get("replay_id") == replay_id for r in db.query(RawDataset).all()):
        object_store.delete_prefix(f"replays/{UUID(replay_id)}/")
        from app.api.survey import load_replay, load_motion
        getattr(load_replay, "cache_clear", lambda: None)()
        load_motion.cache_clear()
    return {
        "deleted": True,
        "dataset_id": dataset_id,
        "object_keys": deleted_objects,
        "processed": processed_results,
    }


def delete_archived_survey(db, summary, object_store):
    raw_ids=[d['id'] for d in summary['raw']]
    processed_ids=[d['id'] for d in summary['processed']]
    # Check every member before deleting any files. Hold raw rows against new jobs.
    if raw_ids:
        db.query(RawDataset).filter(RawDataset.id.in_(raw_ids)).order_by(RawDataset.id).with_for_update().all()
    for raw_id in raw_ids:
        _check_active(db,raw_id)
    raw_members=db.query(RawDataset).filter(RawDataset.id.in_(raw_ids)).all()
    replay_ids=sorted({(r.metadata_json or {}).get('replay_id') for r in raw_members if (r.metadata_json or {}).get('replay_id')})
    location_ids={r.location_id for r in raw_members if r.location_id}
    affected=set(processed_ids)
    all_processed=db.query(ProcessedDataset).all()
    while True:
        dependants={p.id for p in all_processed if affected.intersection((p.viewer_config_json or {}).get('source_dataset_ids',[]))}
        if dependants.issubset(affected): break
        affected.update(dependants)
    for p in all_processed:
        if p.id in affected:
            _check_active(db,p.raw_dataset_id)
            if p.location_id: location_ids.add(p.location_id)
    try:
        for dataset_id in raw_ids:
            delete_raw_dataset(db,dataset_id,object_store,commit=False)
        for dataset_id in processed_ids:
            delete_processed_dataset(db,dataset_id,object_store,commit=False)
        for location_id in location_ids:
            if not db.query(RawDataset).filter_by(location_id=location_id).first() and not db.query(ProcessedDataset).filter_by(location_id=location_id).first():
                db.query(SurveyLocation).filter_by(id=location_id).delete(synchronize_session=False)
        db.commit()
    except Exception:
        db.rollback()
        raise
    return {'deleted':True,'survey_id':summary['id'],'raw_ids':raw_ids,'processed_ids':sorted(affected),'replay_ids':replay_ids}
