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


@celery_app.task(name="export_survey_xyz", acks_late=True, reject_on_worker_lost=True)
def export_survey_xyz(source: dict, token: str):
    from app.services.survey_xyz_export import run_export
    from app.storage.s3 import store
    run_export(source, token, store(), SessionLocal)


@celery_app.task(name="repair_survey", acks_late=True, reject_on_worker_lost=True)
def repair_survey(source: dict, token: str):
    from app.services.survey_repair import run
    from app.storage.s3 import store
    run(source, token, store(), SessionLocal)
