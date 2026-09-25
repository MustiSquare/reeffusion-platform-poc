from datetime import datetime, timezone
from fastapi import HTTPException
from app.models.tables import ProcessedDataset, ProcessingJob


def previous_processing(db, raw_ids):
    job = (db.query(ProcessingJob).filter(ProcessingJob.raw_dataset_id.in_(list(raw_ids)), ProcessingJob.status == "completed")
           .order_by(ProcessingJob.updated_at.desc(), ProcessingJob.created_at.desc()).first())
    if job:
        return str(job.updated_at or job.created_at)
    result = (db.query(ProcessedDataset).filter(ProcessedDataset.raw_dataset_id.in_(list(raw_ids)))
              .order_by(ProcessedDataset.created_at.desc()).first())
    return str(result.created_at) if result else None


def require_overwrite(db, raw_ids, key, confirmed):
    date = previous_processing(db, raw_ids)
    if date and not confirmed:
        raise HTTPException(409, {"code":"overwrite_confirmation_required", "confirmation_key":key,
            "processed_at":date, "message":f"Survey processed before on {date}. Are you sure you want to overwrite?"})


def survey_date_key(value):
    if not value: return None
    if isinstance(value, str): value = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if value.tzinfo is None: value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat()
