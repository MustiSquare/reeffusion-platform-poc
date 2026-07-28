from types import SimpleNamespace

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.session import Base
from app.core.config import settings
from app.models import tables  # noqa: F401
from app.models.tables import ModelRun
from app.processing.ai_models import TASK_BENTHIC_COVER, TASK_IMAGE_QUALITY, run_model_task


def test_run_model_task_persists_provider_output():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    db = Session()
    dataset = SimpleNamespace(id="raw-a", name="Raw Reef A")

    output = run_model_task(
        db,
        TASK_IMAGE_QUALITY,
        dataset,
        {"raw_dataset_id": dataset.id, "asset_counts": {"image": 2}},
        raw_dataset_id=dataset.id,
    )
    run = db.query(ModelRun).one()

    assert output["model_run_id"] == run.id
    assert output["provider"] == "local"
    assert run.task == TASK_IMAGE_QUALITY
    assert run.confidence is not None
    assert run.inputs_json["asset_counts"]["image"] == 2
    assert run.outputs_json["model_name"] == "ImageQuality Agent"
    assert run.provenance_json["mode"] == "local_optional_fallback"


def test_run_model_task_can_be_disabled(monkeypatch):
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    db = Session()
    monkeypatch.setattr(settings, "ai_enabled", False)

    output = run_model_task(
        db,
        TASK_BENTHIC_COVER,
        SimpleNamespace(id="raw-disabled", name="Disabled AI"),
        {"raw_dataset_id": "raw-disabled"},
        raw_dataset_id="raw-disabled",
    )
    run = db.query(ModelRun).one()

    assert output["status"] == "disabled"
    assert output["classes"] == {"coral": 0, "rock": 0, "sand": 0, "algae": 0}
    assert run.provider == "disabled"
    assert run.provenance_json["mode"] == "disabled"
