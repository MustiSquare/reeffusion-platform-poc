from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect

from app.core.config import settings


def test_alembic_upgrade_creates_stronger_data_model(tmp_path):
    db_path = tmp_path / "reefusion.sqlite"
    original_url = settings.database_url
    settings.database_url = f"sqlite:///{db_path}"
    try:
        backend_root = Path(__file__).resolve().parents[1]
        cfg = Config(str(backend_root / "alembic.ini"))
        cfg.set_main_option("script_location", str(backend_root / "alembic"))
        cfg.set_main_option("sqlalchemy.url", settings.database_url)
        command.upgrade(cfg, "head")

        engine = create_engine(settings.database_url)
        inspector = inspect(engine)
        raw_columns = {column["name"] for column in inspector.get_columns("raw_datasets")}
        processed_columns = {column["name"] for column in inspector.get_columns("processed_datasets")}
        location_columns = {column["name"] for column in inspector.get_columns("survey_locations")}
        model_run_columns = {column["name"] for column in inspector.get_columns("model_runs")}

        assert {"acquisition_started_at", "sensor_metadata_json", "coordinate_system_json", "quality_report_json"} <= raw_columns
        assert {"processing_version_json", "coordinate_system_json", "quality_report_json"} <= processed_columns
        assert {"crs", "coordinate_system", "vertical_datum", "metadata_json"} <= location_columns
        assert {"provider", "task", "model_name", "confidence", "inputs_json", "outputs_json", "provenance_json"} <= model_run_columns
    finally:
        settings.database_url = original_url
