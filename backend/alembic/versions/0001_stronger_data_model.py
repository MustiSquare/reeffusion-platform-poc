"""Stronger survey data model.

Revision ID: 0001_stronger_data_model
Revises:
Create Date: 2026-06-18
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

from app.db.session import Base
from app.models import tables  # noqa: F401


revision = "0001_stronger_data_model"
down_revision = None
branch_labels = None
depends_on = None


def _columns(table_name: str) -> set[str]:
    return {column["name"] for column in inspect(op.get_bind()).get_columns(table_name)}


def _add_column_if_missing(table_name: str, column: sa.Column) -> None:
    if column.name not in _columns(table_name):
        op.add_column(table_name, column)


def upgrade() -> None:
    bind = op.get_bind()
    Base.metadata.create_all(bind=bind)

    _add_column_if_missing("survey_locations", sa.Column("crs", sa.String(), server_default="EPSG:4326"))
    _add_column_if_missing("survey_locations", sa.Column("coordinate_system", sa.String(), server_default="geographic"))
    _add_column_if_missing("survey_locations", sa.Column("vertical_datum", sa.String(), nullable=True))
    _add_column_if_missing("survey_locations", sa.Column("metadata_json", sa.JSON(), nullable=True))

    _add_column_if_missing("raw_datasets", sa.Column("acquisition_started_at", sa.DateTime(timezone=True), nullable=True))
    _add_column_if_missing("raw_datasets", sa.Column("acquisition_ended_at", sa.DateTime(timezone=True), nullable=True))
    _add_column_if_missing("raw_datasets", sa.Column("sensor_metadata_json", sa.JSON(), nullable=True))
    _add_column_if_missing("raw_datasets", sa.Column("coordinate_system_json", sa.JSON(), nullable=True))
    _add_column_if_missing("raw_datasets", sa.Column("quality_report_json", sa.JSON(), nullable=True))

    _add_column_if_missing("processed_datasets", sa.Column("processing_version_json", sa.JSON(), nullable=True))
    _add_column_if_missing("processed_datasets", sa.Column("coordinate_system_json", sa.JSON(), nullable=True))
    _add_column_if_missing("processed_datasets", sa.Column("quality_report_json", sa.JSON(), nullable=True))


def downgrade() -> None:
    for table_name, column_name in [
        ("processed_datasets", "quality_report_json"),
        ("processed_datasets", "coordinate_system_json"),
        ("processed_datasets", "processing_version_json"),
        ("raw_datasets", "quality_report_json"),
        ("raw_datasets", "coordinate_system_json"),
        ("raw_datasets", "sensor_metadata_json"),
        ("raw_datasets", "acquisition_ended_at"),
        ("raw_datasets", "acquisition_started_at"),
        ("survey_locations", "metadata_json"),
        ("survey_locations", "vertical_datum"),
        ("survey_locations", "coordinate_system"),
        ("survey_locations", "crs"),
    ]:
        if column_name in _columns(table_name):
            op.drop_column(table_name, column_name)
