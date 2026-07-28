from celery import Celery
from app.core.config import settings
from app.db.session import SessionLocal
from app.processing.pipeline import run_processing_pipeline

celery_app = Celery("reefusion", broker=settings.redis_url, backend=settings.redis_url)

@celery_app.task(name="process_dataset")
def process_dataset(job_id: str):
    db=SessionLocal()
    try: run_processing_pipeline(db, job_id)
    finally: db.close()
