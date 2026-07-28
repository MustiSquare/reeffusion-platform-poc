"""Persist AI model runs.

Revision ID: 0002_model_runs
Revises: 0001_stronger_data_model
Create Date: 2026-06-18
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = "0002_model_runs"
down_revision = "0001_stronger_data_model"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if inspect(op.get_bind()).has_table("model_runs"):
        return
    op.create_table(
        "model_runs",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("provider", sa.String(), nullable=True),
        sa.Column("task", sa.String(), nullable=True),
        sa.Column("model_name", sa.String(), nullable=True),
        sa.Column("model_version", sa.String(), nullable=True),
        sa.Column("status", sa.String(), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("raw_dataset_id", sa.String(), sa.ForeignKey("raw_datasets.id"), nullable=True),
        sa.Column("processed_dataset_id", sa.String(), sa.ForeignKey("processed_datasets.id"), nullable=True),
        sa.Column("inputs_json", sa.JSON(), nullable=True),
        sa.Column("outputs_json", sa.JSON(), nullable=True),
        sa.Column("provenance_json", sa.JSON(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_model_runs_task", "model_runs", ["task"])


def downgrade() -> None:
    if inspect(op.get_bind()).has_table("model_runs"):
        op.drop_table("model_runs")
