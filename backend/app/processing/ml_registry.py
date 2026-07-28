from sqlalchemy.orm import Session

from app.models.tables import MLModelRegistryEntry


MODEL_REGISTRY_DEFAULTS = [
    {
        "name": "CoralSeg Agent",
        "task": "image_segmentation",
        "status": "active",
        "version": "ai-segmentation-v1",
        "metadata_json": {"replaceable": True},
    },
    {
        "name": "BenthicCover Agent",
        "task": "benthic_cover_classification",
        "status": "active",
        "version": "benthic-cover-v1",
        "metadata_json": {"classes": ["coral", "rock", "sand", "algae"]},
    },
    {
        "name": "ReefHealth Agent",
        "task": "coral_health_classification",
        "status": "active",
        "version": "health-classifier-v1",
        "metadata_json": {"classes": ["healthy", "bleached", "dead", "diseased"]},
    },
    {
        "name": "ReefReport Agent",
        "task": "report_generation",
        "status": "active",
        "version": "report-agent-v1",
        "metadata_json": {"source": "metrics_json"},
    },
    {
        "name": "ReefQA Agent",
        "task": "question_answering",
        "status": "active",
        "version": "qa-agent-v1",
        "metadata_json": {"source": "metrics_json"},
    },
]


def ensure_ml_registry(db: Session) -> None:
    existing = {m.name for m in db.query(MLModelRegistryEntry).all()}
    db.add_all(
        MLModelRegistryEntry(**entry)
        for entry in MODEL_REGISTRY_DEFAULTS
        if entry["name"] not in existing
    )
    db.commit()
