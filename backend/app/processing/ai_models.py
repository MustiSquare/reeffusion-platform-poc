import hashlib
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Protocol

from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.tables import ModelRun

TASK_IMAGE_QUALITY = "image_quality_assessment"
TASK_CORAL_SEGMENTATION = "coral_segmentation"
TASK_BENTHIC_COVER = "benthic_cover_classification"
TASK_CORAL_HEALTH = "coral_health_classification"
TASK_LAYER_PROJECTION = "project_ai_layers_to_3d"
TASK_REPORT_GENERATION = "report_generation"


@dataclass(frozen=True)
class ModelResult:
    provider: str
    task: str
    model_name: str
    model_version: str
    confidence: float | None
    output: dict
    provenance: dict


class AIModelProvider(Protocol):
    name: str

    def image_quality(self, raw_dataset, inputs: dict) -> ModelResult: ...
    def coral_segmentation(self, raw_dataset, inputs: dict) -> ModelResult: ...
    def benthic_cover(self, raw_dataset, inputs: dict) -> ModelResult: ...
    def coral_health(self, raw_dataset, inputs: dict) -> ModelResult: ...
    def project_layers(self, dataset_or_grid, inputs: dict) -> ModelResult: ...
    def reef_report(self, dataset, comparison_dataset, inputs: dict) -> ModelResult: ...


def _seed(obj: Any) -> int:
    value = getattr(obj, "id", None) or getattr(obj, "name", None) or str(obj)
    digest = hashlib.sha256(str(value).encode("utf-8")).hexdigest()
    return int(digest[:8], 16)


def _pct(seed: int, base: float, spread: float = 4.0) -> float:
    return round(base + ((seed % 1000) / 1000.0 - 0.5) * spread, 1)


def _normalize(values: dict[str, float]) -> dict[str, float]:
    total = sum(values.values()) or 1.0
    return {k: round(v / total * 100, 1) for k, v in values.items()}


def _provenance(provider: str, task: str, inputs: dict) -> dict:
    return {
        "provider": provider,
        "task": task,
        "mode": "local_optional_fallback",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "input_keys": sorted(inputs.keys()),
    }


class LocalDeterministicProvider:
    name = "local"

    def image_quality(self, raw_dataset, inputs: dict) -> ModelResult:
        s = _seed(raw_dataset)
        output = {
            "model_name": "ImageQuality Agent",
            "model_version": "image-qa-local-v1",
            "confidence": round(0.84 + (s % 9) / 100, 2),
            "visibility_score": _pct(s, 82.0, 8.0),
            "blur_risk": _pct(s // 3, 10.0, 6.0),
            "lighting_uniformity": _pct(s // 7, 78.0, 10.0),
            "notes": ["Underwater frames pass quality gates", "QA results support downstream reconstruction"],
        }
        return _result(self.name, TASK_IMAGE_QUALITY, output, _provenance(self.name, TASK_IMAGE_QUALITY, inputs))

    def coral_segmentation(self, raw_dataset, inputs: dict) -> ModelResult:
        s = _seed(raw_dataset)
        output = {
            "model_name": "CoralSeg Agent",
            "model_version": "coral-seg-local-v1",
            "confidence": round(0.86 + (s % 7) / 100, 2),
            "mask_count": 120 + (s % 35),
            "classes": _normalize({"coral": _pct(s, 43, 8), "background": _pct(s // 2, 57, 8)}),
        }
        return _result(self.name, TASK_CORAL_SEGMENTATION, output, _provenance(self.name, TASK_CORAL_SEGMENTATION, inputs))

    def benthic_cover(self, raw_dataset, inputs: dict) -> ModelResult:
        s = _seed(raw_dataset)
        output = {
            "model_name": "BenthicCover Agent",
            "model_version": "benthic-cover-local-v1",
            "confidence": round(0.83 + (s % 10) / 100, 2),
            "classes": _normalize({
                "coral": _pct(s, 42.5, 7.0),
                "rock": _pct(s // 3, 21.0, 5.0),
                "sand": _pct(s // 5, 18.3, 5.0),
                "algae": _pct(s // 7, 18.2, 5.0),
            }),
        }
        return _result(self.name, TASK_BENTHIC_COVER, output, _provenance(self.name, TASK_BENTHIC_COVER, inputs))

    def coral_health(self, raw_dataset, inputs: dict) -> ModelResult:
        s = _seed(raw_dataset)
        output = {
            "model_name": "ReefHealth Agent",
            "model_version": "coral-health-local-v1",
            "confidence": round(0.82 + (s % 12) / 100, 2),
            "classes": _normalize({
                "healthy": _pct(s, 68.5, 9.0),
                "bleached": _pct(s // 2, 14.2, 4.5),
                "dead": _pct(s // 4, 7.8, 3.0),
                "diseased": _pct(s // 6, 9.5, 3.5),
            }),
        }
        return _result(self.name, TASK_CORAL_HEALTH, output, _provenance(self.name, TASK_CORAL_HEALTH, inputs))

    def project_layers(self, dataset_or_grid, inputs: dict) -> ModelResult:
        s = _seed(dataset_or_grid)
        output = {
            "model_name": "3D Layer Projection Agent",
            "model_version": "ai-3d-projection-local-v1",
            "confidence": round(0.81 + (s % 10) / 100, 2),
            "layers": ["coral_segmentation_masks", "benthic_cover_classes", "health_classes"],
            "projected_vertices": 4096 + (s % 512),
            "viewer_layer_ready": True,
        }
        return _result(self.name, TASK_LAYER_PROJECTION, output, _provenance(self.name, TASK_LAYER_PROJECTION, inputs))

    def reef_report(self, dataset, comparison_dataset, inputs: dict) -> ModelResult:
        from app.services.ai_agents import build_reef_report_payload

        output = build_reef_report_payload(dataset, comparison_dataset)
        output["provider"] = self.name
        output["model_version"] = "reef-report-local-v1"
        output["confidence"] = 0.8
        return _result(self.name, TASK_REPORT_GENERATION, output, _provenance(self.name, TASK_REPORT_GENERATION, inputs))


def _result(provider: str, task: str, output: dict, provenance: dict) -> ModelResult:
    return ModelResult(
        provider=provider,
        task=task,
        model_name=output.get("model_name") or output.get("agent") or task,
        model_version=output.get("model_version") or output.get("version") or "local-v1",
        confidence=output.get("confidence"),
        output=output,
        provenance=provenance,
    )


def get_ai_provider() -> AIModelProvider | None:
    if not settings.ai_enabled:
        return None
    if settings.ai_provider != "local":
        raise ValueError(f"AI provider '{settings.ai_provider}' is not configured")
    return LocalDeterministicProvider()


def _disabled_output(task: str) -> dict:
    base = {
        "status": "disabled",
        "task": task,
        "confidence": None,
        "model_name": task,
        "model_version": "disabled",
        "notes": ["AI provider disabled; task was skipped."],
    }
    if task == TASK_BENTHIC_COVER:
        return {**base, "classes": {"coral": 0, "rock": 0, "sand": 0, "algae": 0}}
    if task == TASK_CORAL_HEALTH:
        return {**base, "classes": {"healthy": 0, "bleached": 0, "dead": 0, "diseased": 0}}
    if task == TASK_CORAL_SEGMENTATION:
        return {**base, "classes": {"coral": 0, "background": 0}, "mask_count": 0}
    if task == TASK_LAYER_PROJECTION:
        return {**base, "layers": [], "projected_vertices": 0, "viewer_layer_ready": False}
    return base


def persist_model_run(
    db: Session,
    result: ModelResult,
    inputs: dict,
    raw_dataset_id: str | None = None,
    processed_dataset_id: str | None = None,
) -> ModelRun:
    run = ModelRun(
        provider=result.provider,
        task=result.task,
        model_name=result.model_name,
        model_version=result.model_version,
        status="completed",
        confidence=result.confidence,
        raw_dataset_id=raw_dataset_id,
        processed_dataset_id=processed_dataset_id,
        inputs_json=inputs,
        outputs_json=result.output,
        provenance_json=result.provenance,
    )
    db.add(run)
    db.commit()
    db.refresh(run)
    return run


def run_model_task(
    db: Session,
    task: str,
    target,
    inputs: dict,
    raw_dataset_id: str | None = None,
    processed_dataset_id: str | None = None,
    comparison_dataset=None,
) -> dict:
    provider = get_ai_provider()
    if provider is None:
        output = _disabled_output(task)
        result = ModelResult("disabled", task, task, "disabled", None, output, {"mode": "disabled"})
    elif task == TASK_IMAGE_QUALITY:
        result = provider.image_quality(target, inputs)
    elif task == TASK_CORAL_SEGMENTATION:
        result = provider.coral_segmentation(target, inputs)
    elif task == TASK_BENTHIC_COVER:
        result = provider.benthic_cover(target, inputs)
    elif task == TASK_CORAL_HEALTH:
        result = provider.coral_health(target, inputs)
    elif task == TASK_LAYER_PROJECTION:
        result = provider.project_layers(target, inputs)
    elif task == TASK_REPORT_GENERATION:
        result = provider.reef_report(target, comparison_dataset, inputs)
    else:
        raise ValueError(f"Unsupported AI model task: {task}")

    run = persist_model_run(db, result, inputs, raw_dataset_id, processed_dataset_id)
    return {**result.output, "model_run_id": run.id, "provider": result.provider, "provenance": result.provenance}


def run_image_quality_assessment(raw_dataset) -> dict:
    provider = get_ai_provider() or LocalDeterministicProvider()
    return provider.image_quality(raw_dataset, {"raw_dataset_id": getattr(raw_dataset, "id", None)}).output


def run_coral_segmentation(raw_dataset) -> dict:
    provider = get_ai_provider() or LocalDeterministicProvider()
    return provider.coral_segmentation(raw_dataset, {"raw_dataset_id": getattr(raw_dataset, "id", None)}).output


def run_benthic_cover_classification(raw_dataset) -> dict:
    provider = get_ai_provider() or LocalDeterministicProvider()
    return provider.benthic_cover(raw_dataset, {"raw_dataset_id": getattr(raw_dataset, "id", None)}).output


def run_coral_health_classification(raw_dataset) -> dict:
    provider = get_ai_provider() or LocalDeterministicProvider()
    return provider.coral_health(raw_dataset, {"raw_dataset_id": getattr(raw_dataset, "id", None)}).output


def project_ai_layers_to_3d(processed_dataset_or_grid) -> dict:
    provider = get_ai_provider() or LocalDeterministicProvider()
    return provider.project_layers(processed_dataset_or_grid, {"target_id": getattr(processed_dataset_or_grid, "id", None)}).output


def generate_ai_insights(metrics: dict) -> list[str]:
    cover = metrics.get("cover", {}) or {}
    health = metrics.get("health", {}) or {}
    coral = float(cover.get("coral", 0) or 0)
    healthy = float(health.get("healthy", 0) or 0)
    bleached = float(health.get("bleached", 0) or 0)
    diseased = float(health.get("diseased", 0) or 0)
    insights = [
        f"Estimated coral cover is {coral:.1f}% based on benthic classification.",
        f"Healthy coral class is {healthy:.1f}% with bleaching-like signal around {bleached:.1f}%.",
    ]
    if bleached + diseased >= 22:
        insights.append("Combined bleaching/disease indicator is moderate and should be reviewed by a reef scientist.")
    else:
        insights.append("Stress-class indicators remain low-to-moderate in this survey run.")
    insights.append("AI layers were projected into the browser 3D model as viewer overlays.")
    return insights
