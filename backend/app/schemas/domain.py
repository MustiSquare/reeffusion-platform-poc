from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


class CoordinateSystemSchema(BaseModel):
    crs: str = "LOCAL_GRID"
    coordinate_system: Literal["geographic", "projected_or_local"] = "projected_or_local"
    horizontal_units: str = "meters"
    vertical_units: str = "meters"
    vertical_datum: str | None = None
    vertical_convention: str = "elevation_positive_up"
    bounds: dict[str, float] | None = None


class SensorMetadataSchema(BaseModel):
    camera: dict[str, Any] = Field(default_factory=dict)
    sonar: dict[str, Any] = Field(default_factory=dict)
    gps: dict[str, Any] = Field(default_factory=dict)
    platform: dict[str, Any] = Field(default_factory=dict)
    raw: dict[str, Any] = Field(default_factory=dict)


class SurveyLocationSchema(BaseModel):
    name: str
    latitude: float | None = None
    longitude: float | None = None
    crs: str = "EPSG:4326"
    coordinate_system: Literal["geographic", "projected_or_local"] = "geographic"
    vertical_datum: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class QualityReportSchema(BaseModel):
    validation_status: Literal["valid", "warning", "failed"] = "valid"
    warnings: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    checks: dict[str, Any] = Field(default_factory=dict)
    workflow_validation: dict[str, Any] = Field(
        default_factory=lambda: {
            "status": "passed",
            "purpose": "technical workflow validation",
        }
    )
    scientific_validity: dict[str, Any] = Field(
        default_factory=lambda: {
            "status": "workflow_validation_only",
            "is_scientifically_valid": False,
            "reasons": ["Scientific calibration and expert QA have not been completed."],
        }
    )
    calibration: dict[str, Any] = Field(default_factory=dict)
    uncertainty: dict[str, Any] = Field(default_factory=dict)


class AcquisitionWindowSchema(BaseModel):
    started_at: datetime | None = None
    ended_at: datetime | None = None


class ProcessingVersionSchema(BaseModel):
    name: str
    version: str
    geometry_engine: str = "bathymetry-grid"
    mesh_formats: list[str] = Field(default_factory=lambda: ["glb", "ply", "obj"])
    ai_assisted: bool = True
