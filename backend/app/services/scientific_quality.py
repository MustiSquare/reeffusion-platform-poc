import io
from typing import Any

import numpy as np
from PIL import Image

from app.schemas.domain import QualityReportSchema


BLUR_SCORE_WARNING = 35.0
VISIBILITY_SCORE_WARNING = 0.45
DEPTH_OUTLIER_RATIO_WARNING = 0.05


def scientific_validity(
    reasons: list[str] | None = None,
    *,
    status: str = "workflow_validation_only",
    is_scientifically_valid: bool = False,
) -> dict[str, Any]:
    return {
        "status": status,
        "is_scientifically_valid": is_scientifically_valid,
        "reasons": reasons
        or [
            "Workflow outputs verify that platform processing runs end-to-end.",
            "Scientific conclusions require calibrated sensors, reviewed CRS/datum, and field QA.",
        ],
    }


def image_quality_from_bytes(data: bytes) -> dict[str, Any]:
    with Image.open(io.BytesIO(data)) as img:
        gray = np.asarray(img.convert("L"), dtype=float)

    if gray.size == 0:
        return {
            "blur_score": 0.0,
            "visibility_score": 0.0,
            "warnings": ["Image could not be evaluated for visibility"],
        }

    dx = np.diff(gray, axis=1)
    dy = np.diff(gray, axis=0)
    gradient_variance = float(np.var(dx)) + float(np.var(dy))
    contrast = float(np.std(gray))
    mean_luma = float(np.mean(gray))
    exposure_penalty = min(abs(mean_luma - 127.5) / 127.5, 1.0)
    contrast_score = min(contrast / 64.0, 1.0)
    visibility_score = max(0.0, min(1.0, contrast_score * (1.0 - 0.5 * exposure_penalty)))

    warnings: list[str] = []
    if gradient_variance < BLUR_SCORE_WARNING:
        warnings.append("Image blur risk is elevated")
    if visibility_score < VISIBILITY_SCORE_WARNING:
        warnings.append("Image visibility/contrast is low")

    return {
        "blur_score": round(gradient_variance, 4),
        "blur_warning_threshold": BLUR_SCORE_WARNING,
        "visibility_score": round(visibility_score, 4),
        "visibility_warning_threshold": VISIBILITY_SCORE_WARNING,
        "mean_luminance": round(mean_luma, 4),
        "contrast": round(contrast, 4),
        "warnings": warnings,
    }


def depth_outlier_report(values: Any) -> dict[str, Any]:
    z = np.asarray(values, dtype=float)
    z = z[np.isfinite(z)]
    if z.size == 0:
        return {"point_count": 0, "outlier_count": 0, "outlier_ratio": 0.0, "warnings": ["No finite depth/elevation values"]}

    median = float(np.median(z))
    mad = float(np.median(np.abs(z - median)))
    if mad > 0:
        robust_z = np.abs(0.6745 * (z - median) / mad)
        outliers = robust_z > 3.5
        method = "modified_z_score"
    else:
        std = float(np.std(z))
        outliers = np.abs(z - median) > (3.0 * std) if std > 0 else np.zeros_like(z, dtype=bool)
        method = "standard_deviation"

    outlier_count = int(np.sum(outliers))
    outlier_ratio = float(outlier_count / z.size)
    warnings = []
    if outlier_ratio > DEPTH_OUTLIER_RATIO_WARNING:
        warnings.append("Depth/elevation outlier ratio exceeds QA threshold")

    return {
        "method": method,
        "point_count": int(z.size),
        "median_z_m": round(median, 4),
        "min_z_m": round(float(np.min(z)), 4),
        "max_z_m": round(float(np.max(z)), 4),
        "outlier_count": outlier_count,
        "outlier_ratio": round(outlier_ratio, 6),
        "outlier_ratio_warning_threshold": DEPTH_OUTLIER_RATIO_WARNING,
        "warnings": warnings,
    }


def survey_coverage_metrics(metadata: dict[str, Any] | None) -> dict[str, Any]:
    metadata = metadata or {}
    bounds = metadata.get("bounds") or {}
    point_count = int(metadata.get("point_count") or 0)
    min_x = bounds.get("min_x")
    max_x = bounds.get("max_x")
    min_y = bounds.get("min_y")
    max_y = bounds.get("max_y")

    width = float(max_x - min_x) if min_x is not None and max_x is not None else 0.0
    height = float(max_y - min_y) if min_y is not None and max_y is not None else 0.0
    area = max(width * height, 0.0)
    density = point_count / area if area > 0 else None

    return {
        "bounds": bounds,
        "coverage_area": round(area, 4),
        "coverage_area_units": "square_degrees" if metadata.get("coordinate_system") == "geographic" else "square_meters",
        "point_count": point_count,
        "point_density": round(density, 6) if density is not None else None,
        "grid_shape": metadata.get("grid_shape"),
        "interpolated": bool(metadata.get("interpolated")),
        "regular_grid": bool(metadata.get("regular_grid")),
    }


def uncertainty_estimate(
    *,
    has_gps: bool,
    has_bathymetry: bool,
    used_fallback_geometry: bool = False,
    depth_outliers: dict[str, Any] | None = None,
    image_quality: dict[str, Any] | None = None,
    model_confidences: dict[str, Any] | None = None,
) -> dict[str, Any]:
    depth_outliers = depth_outliers or {}
    image_quality = image_quality or {}
    model_confidences = model_confidences or {}
    uncertainty_flags: list[str] = []
    if not has_gps:
        uncertainty_flags.append("missing_gps")
    if not has_bathymetry or used_fallback_geometry:
        uncertainty_flags.append("fallback_or_missing_bathymetry")
    if depth_outliers.get("outlier_ratio", 0) > DEPTH_OUTLIER_RATIO_WARNING:
        uncertainty_flags.append("depth_outliers")
    if image_quality.get("visibility_score", 1) < VISIBILITY_SCORE_WARNING:
        uncertainty_flags.append("low_image_visibility")

    return {
        "qualitative_level": "high" if uncertainty_flags else "moderate",
        "flags": uncertainty_flags,
        "depth_outlier_ratio": depth_outliers.get("outlier_ratio"),
        "image_visibility_score": image_quality.get("visibility_score"),
        "model_confidences": model_confidences,
        "note": "Uncertainty is a workflow estimate, not a calibrated measurement uncertainty budget.",
    }


def build_upload_quality_report(
    *,
    counts: dict[str, int],
    warnings: list[str],
    image_checks: list[dict[str, Any]],
    depth_checks: list[dict[str, Any]],
    coverage: list[dict[str, Any]],
) -> QualityReportSchema:
    image_warnings = [warning for check in image_checks for warning in check.get("warnings", [])]
    depth_warnings = [warning for check in depth_checks for warning in check.get("warnings", [])]
    all_warnings = [*warnings, *image_warnings, *depth_warnings]
    has_gps = counts.get("gps", 0) > 0
    has_bathymetry = counts.get("bathymetry", 0) > 0
    first_image_check = image_checks[0] if image_checks else {}
    first_depth_check = depth_checks[0] if depth_checks else {}

    return QualityReportSchema(
        validation_status="warning" if all_warnings else "valid",
        warnings=all_warnings,
        checks={
            "asset_counts": counts,
            "has_survey_data": True,
            "has_gps": has_gps,
            "missing_gps": not has_gps,
            "has_bathymetry": has_bathymetry,
            "image_quality": image_checks,
            "depth_outliers": depth_checks,
            "survey_coverage": coverage,
        },
        workflow_validation={
            "status": "passed_with_warnings" if all_warnings else "passed",
            "purpose": "upload/package validation and metadata extraction",
        },
        scientific_validity=scientific_validity(),
        calibration={
            "camera_calibration_present": False,
            "sonar_calibration_present": False,
            "gps_quality_present": has_gps,
        },
        uncertainty=uncertainty_estimate(
            has_gps=has_gps,
            has_bathymetry=has_bathymetry,
            depth_outliers=first_depth_check,
            image_quality=first_image_check,
        ),
    )


def build_processing_quality_report(
    *,
    counts: dict[str, int],
    bathymetry_metadata: dict[str, Any],
    z_values: Any,
    used_fallback_geometry: bool,
    point_count: int,
    mesh_formats: list[str],
    image_quality: dict[str, Any],
    model_confidences: dict[str, Any],
) -> QualityReportSchema:
    depth_check = depth_outlier_report(z_values)
    coverage = survey_coverage_metrics(bathymetry_metadata)
    warnings = [
        *depth_check.get("warnings", []),
        *image_quality.get("warnings", []),
    ]
    if used_fallback_geometry:
        warnings.append("Processing used fallback geometry; outputs are for workflow validation only")
    if counts.get("gps", 0) == 0:
        warnings.append("No GPS asset was present for geospatial validation")

    has_gps = counts.get("gps", 0) > 0
    return QualityReportSchema(
        validation_status="warning" if warnings else "valid",
        warnings=warnings,
        checks={
            "rugosity_computed": True,
            "mesh_formats": mesh_formats,
            "used_fallback_geometry": used_fallback_geometry,
            "point_count": point_count,
            "missing_gps": not has_gps,
            "depth_outliers": depth_check,
            "survey_coverage": coverage,
            "image_quality": image_quality,
        },
        workflow_validation={
            "status": "passed_with_warnings" if warnings else "passed",
            "purpose": "processing pipeline execution and output generation",
        },
        scientific_validity=scientific_validity(),
        calibration={
            "camera_calibration_present": False,
            "sonar_calibration_present": False,
            "coordinate_reference_reviewed": False,
        },
        uncertainty=uncertainty_estimate(
            has_gps=has_gps,
            has_bathymetry=counts.get("bathymetry", 0) > 0,
            used_fallback_geometry=used_fallback_geometry,
            depth_outliers=depth_check,
            image_quality=image_quality,
            model_confidences=model_confidences,
        ),
    )
