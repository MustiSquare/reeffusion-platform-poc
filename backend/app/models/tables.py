import uuid
from sqlalchemy import Column, String, DateTime, ForeignKey, Integer, Float, JSON, Text
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.db.session import Base

def uuid_str(): return str(uuid.uuid4())

class SurveyLocation(Base):
    __tablename__ = "survey_locations"
    id = Column(String, primary_key=True, default=uuid_str)
    name = Column(String, index=True)
    latitude = Column(Float)
    longitude = Column(Float)
    crs = Column(String, default="EPSG:4326")
    coordinate_system = Column(String, default="geographic")
    vertical_datum = Column(String, nullable=True)
    geom_geojson = Column(JSON, nullable=True)
    metadata_json = Column(JSON, default=dict)

class RawDataset(Base):
    __tablename__ = "raw_datasets"
    id = Column(String, primary_key=True, default=uuid_str)
    name = Column(String, index=True)
    survey_date = Column(DateTime(timezone=True), server_default=func.now())
    acquisition_started_at = Column(DateTime(timezone=True), nullable=True)
    acquisition_ended_at = Column(DateTime(timezone=True), nullable=True)
    location_id = Column(String, ForeignKey("survey_locations.id"), nullable=True)
    status = Column(String, default="uploaded")
    source = Column(String, default="upload")
    sensor_metadata_json = Column(JSON, default=dict)
    coordinate_system_json = Column(JSON, default=dict)
    quality_report_json = Column(JSON, default=dict)
    metadata_json = Column(JSON, default=dict)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    location = relationship("SurveyLocation")
    assets = relationship("RawAsset", cascade="all,delete")

class RawAsset(Base):
    __tablename__ = "raw_assets"
    id = Column(String, primary_key=True, default=uuid_str)
    dataset_id = Column(String, ForeignKey("raw_datasets.id"))
    file_name = Column(String)
    media_type = Column(String)
    asset_type = Column(String)
    object_key = Column(String)
    size_bytes = Column(Integer, default=0)
    metadata_json = Column(JSON, default=dict)

class ProcessingJob(Base):
    __tablename__ = "processing_jobs"
    id = Column(String, primary_key=True, default=uuid_str)
    raw_dataset_id = Column(String, ForeignKey("raw_datasets.id"))
    status = Column(String, default="queued")
    current_step = Column(String, default="queued")
    progress = Column(Integer, default=0)
    error = Column(Text, nullable=True)
    result_processed_dataset_id = Column(String, nullable=True)
    steps = Column(JSON, default=list)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

class ProcessedDataset(Base):
    __tablename__ = "processed_datasets"
    id = Column(String, primary_key=True, default=uuid_str)
    raw_dataset_id = Column(String, ForeignKey("raw_datasets.id"), nullable=True)
    name = Column(String, index=True)
    location_id = Column(String, ForeignKey("survey_locations.id"), nullable=True)
    survey_date = Column(DateTime(timezone=True), server_default=func.now())
    processing_version = Column(String, default="bathymetry-mesh-v1")
    processing_version_json = Column(JSON, default=dict)
    status = Column(String, default="completed")
    coordinate_system_json = Column(JSON, default=dict)
    quality_report_json = Column(JSON, default=dict)
    metrics_json = Column(JSON, default=dict)
    viewer_config_json = Column(JSON, default=dict)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    assets = relationship("ProcessedAsset", cascade="all,delete")
    location = relationship("SurveyLocation")

class ProcessedAsset(Base):
    __tablename__ = "processed_assets"
    id = Column(String, primary_key=True, default=uuid_str)
    dataset_id = Column(String, ForeignKey("processed_datasets.id"))
    asset_type = Column(String)
    file_name = Column(String)
    object_key = Column(String)
    media_type = Column(String)
    metadata_json = Column(JSON, default=dict)

class Annotation(Base):
    __tablename__ = "annotations"
    id = Column(String, primary_key=True, default=uuid_str)
    processed_dataset_id = Column(String, ForeignKey("processed_datasets.id"))
    label = Column(String)
    annotation_type = Column(String)
    geometry_json = Column(JSON)
    properties_json = Column(JSON, default=dict)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

class MLModelRegistryEntry(Base):
    __tablename__ = "ml_model_registry"
    id = Column(String, primary_key=True, default=uuid_str)
    name = Column(String)
    task = Column(String)
    status = Column(String, default="placeholder")
    version = Column(String, default="0.0.0")
    metadata_json = Column(JSON, default=dict)

class ModelRun(Base):
    __tablename__ = "model_runs"
    id = Column(String, primary_key=True, default=uuid_str)
    provider = Column(String)
    task = Column(String, index=True)
    model_name = Column(String)
    model_version = Column(String)
    status = Column(String, default="completed")
    confidence = Column(Float, nullable=True)
    raw_dataset_id = Column(String, ForeignKey("raw_datasets.id"), nullable=True)
    processed_dataset_id = Column(String, ForeignKey("processed_datasets.id"), nullable=True)
    inputs_json = Column(JSON, default=dict)
    outputs_json = Column(JSON, default=dict)
    provenance_json = Column(JSON, default=dict)
    error = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

class ComparisonResult(Base):
    __tablename__ = "comparison_results"
    id = Column(String, primary_key=True, default=uuid_str)
    dataset_a_id = Column(String, ForeignKey("processed_datasets.id"))
    dataset_b_id = Column(String, ForeignKey("processed_datasets.id"))
    metrics_json = Column(JSON, default=dict)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
