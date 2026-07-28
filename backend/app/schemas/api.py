from pydantic import BaseModel, Field
from typing import Any

class AnnotationIn(BaseModel):
    label: str
    annotation_type: str = "point"
    geometry_json: dict[str, Any]
    properties_json: dict[str, Any] = Field(default_factory=dict)

class ComparisonIn(BaseModel):
    dataset_a_id: str
    dataset_b_id: str

class ReefReportIn(BaseModel):
    dataset_id: str
    comparison_dataset_id: str | None = None

class ReefQuestionIn(BaseModel):
    dataset_id: str
    question: str
    comparison_dataset_id: str | None = None
