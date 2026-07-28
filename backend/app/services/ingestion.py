import csv
import hashlib
import io
import json
import mimetypes
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from PIL import Image

from app.processing.bathymetry import parse_xyz_csv
from app.schemas.domain import AcquisitionWindowSchema, CoordinateSystemSchema, QualityReportSchema, SensorMetadataSchema
from app.services.scientific_quality import (
    build_upload_quality_report,
    depth_outlier_report,
    image_quality_from_bytes,
    survey_coverage_metrics,
)


MAX_FILE_BYTES = 500 * 1024 * 1024

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".tif", ".tiff"}
VIDEO_EXTENSIONS = {".mp4", ".mov", ".avi", ".mkv"}
BATHYMETRY_EXTENSIONS = {".csv", ".xyz", ".las", ".laz"}
GEOJSON_EXTENSIONS = {".geojson"}
GPS_EXTENSIONS = {".gpx"}
METADATA_EXTENSIONS = {".json"}
RASTER_EXTENSIONS = {".tif", ".tiff", ".nc", ".netcdf"}


@dataclass(frozen=True)
class UploadedSurveyFile:
    filename: str
    content_type: str | None
    data: bytes


@dataclass(frozen=True)
class IngestedAsset:
    filename: str
    content_type: str
    asset_type: str
    size_bytes: int
    metadata: dict[str, Any]
    data: bytes


@dataclass(frozen=True)
class IngestionResult:
    dataset_name: str
    dataset_metadata: dict[str, Any]
    assets: list[IngestedAsset]
    location: dict[str, Any] | None = None
    acquisition: AcquisitionWindowSchema = field(default_factory=AcquisitionWindowSchema)
    sensor_metadata: SensorMetadataSchema = field(default_factory=SensorMetadataSchema)
    coordinate_system: CoordinateSystemSchema = field(default_factory=CoordinateSystemSchema)
    quality_report: QualityReportSchema = field(default_factory=QualityReportSchema)


def _extension(filename: str) -> str:
    return Path(filename).suffix.lower()


def _safe_filename(filename: str) -> str:
    name = Path(filename or "").name.strip()
    if not name or name in {".", ".."}:
        raise ValueError("Uploaded files must have valid file names")
    return name


def _content_type(filename: str, content_type: str | None) -> str:
    guessed = mimetypes.guess_type(filename)[0]
    return content_type or guessed or "application/octet-stream"


def _asset_type(filename: str, content_type: str) -> str:
    ext = _extension(filename)
    lower_type = content_type.lower()
    if ext in BATHYMETRY_EXTENSIONS:
        return "bathymetry"
    if ext in GEOJSON_EXTENSIONS:
        return "gps"
    if ext in GPS_EXTENSIONS:
        return "gps"
    if ext in METADATA_EXTENSIONS:
        return "metadata"
    if ext in RASTER_EXTENSIONS and ext not in IMAGE_EXTENSIONS:
        return "bathymetry"
    if lower_type.startswith("image/"):
        return "image"
    if lower_type.startswith("video/") or ext in VIDEO_EXTENSIONS:
        return "video"
    return "file"


def _json_metadata(data: bytes) -> dict[str, Any]:
    obj = json.loads(data.decode("utf-8-sig"))
    if not isinstance(obj, dict):
        raise ValueError("metadata JSON must contain an object")
    return {
        "json_keys": sorted(obj.keys()),
        "parsed_json": obj,
    }


def _geojson_metadata(data: bytes) -> dict[str, Any]:
    obj = json.loads(data.decode("utf-8-sig"))
    features = obj.get("features", []) if isinstance(obj, dict) else []
    coords: list[list[float]] = []

    def collect(value: Any) -> None:
        if isinstance(value, list) and len(value) >= 2 and all(isinstance(x, (int, float)) for x in value[:2]):
            coords.append([float(value[0]), float(value[1])])
            return
        if isinstance(value, list):
            for item in value:
                collect(item)

    if isinstance(obj, dict):
        collect(obj.get("coordinates"))
        for feature in features:
            if isinstance(feature, dict):
                collect((feature.get("geometry") or {}).get("coordinates"))

    metadata: dict[str, Any] = {
        "geojson_type": obj.get("type") if isinstance(obj, dict) else None,
        "feature_count": len(features) if isinstance(features, list) else 0,
    }
    if coords:
        lons = [c[0] for c in coords]
        lats = [c[1] for c in coords]
        metadata["bounds"] = {
            "min_lon": min(lons),
            "min_lat": min(lats),
            "max_lon": max(lons),
            "max_lat": max(lats),
        }
        metadata["centroid"] = {"longitude": sum(lons) / len(lons), "latitude": sum(lats) / len(lats)}
    return metadata


def _gpx_metadata(data: bytes) -> dict[str, Any]:
    root = ET.fromstring(data)
    points: list[tuple[float, float]] = []
    for elem in root.iter():
        if elem.tag.endswith("trkpt") or elem.tag.endswith("wpt"):
            lat = elem.attrib.get("lat")
            lon = elem.attrib.get("lon")
            if lat is not None and lon is not None:
                points.append((float(lat), float(lon)))
    metadata: dict[str, Any] = {"point_count": len(points)}
    if points:
        lats = [p[0] for p in points]
        lons = [p[1] for p in points]
        metadata["bounds"] = {
            "min_lon": min(lons),
            "min_lat": min(lats),
            "max_lon": max(lons),
            "max_lat": max(lats),
        }
        metadata["centroid"] = {"latitude": sum(lats) / len(lats), "longitude": sum(lons) / len(lons)}
    return metadata


def _image_metadata(data: bytes) -> dict[str, Any]:
    with Image.open(io.BytesIO(data)) as img:
        metadata = {"width": img.width, "height": img.height, "format": img.format}
    metadata["quality"] = image_quality_from_bytes(data)
    return metadata


def _csv_preview(data: bytes) -> dict[str, Any]:
    text = data.decode("utf-8-sig")
    reader = csv.reader(io.StringIO(text))
    headers = next(reader, [])
    rows = sum(1 for _ in reader)
    return {"columns": headers, "row_count": rows}


def _extract_metadata(filename: str, asset_type: str, data: bytes) -> dict[str, Any]:
    ext = _extension(filename)
    metadata: dict[str, Any] = {
        "sha256": hashlib.sha256(data).hexdigest(),
        "extension": ext,
    }
    if asset_type == "bathymetry" and ext in {".csv", ".xyz"}:
        grid = parse_xyz_csv(data, source=filename)
        metadata.update(grid.metadata)
        metadata["z_min"] = float(grid.z.min())
        metadata["z_max"] = float(grid.z.max())
        metadata["depth_outliers"] = depth_outlier_report(grid.z)
        metadata["survey_coverage"] = survey_coverage_metrics(grid.metadata)
    elif asset_type == "metadata" and ext == ".json":
        metadata.update(_json_metadata(data))
    elif asset_type == "gps" and ext == ".geojson":
        metadata.update(_geojson_metadata(data))
    elif asset_type == "gps" and ext == ".gpx":
        metadata.update(_gpx_metadata(data))
    elif asset_type == "image":
        metadata.update(_image_metadata(data))
    elif ext == ".csv":
        metadata.update(_csv_preview(data))
    return metadata


def _dataset_name(files: list[IngestedAsset], metadata_docs: list[dict[str, Any]]) -> str:
    for doc in metadata_docs:
        parsed = doc.get("parsed_json") or {}
        for key in ("dataset_name", "survey_name", "name", "title"):
            if parsed.get(key):
                return str(parsed[key])
    stems = [Path(asset.filename).stem for asset in files]
    common = stems[0] if stems else "Uploaded Reef Dataset"
    for stem in stems[1:]:
        while common and not stem.startswith(common):
            common = common[:-1]
    return common.strip(" _-.") or "Uploaded Reef Dataset"


def _parse_datetime(value: Any) -> datetime | None:
    if not value:
        return None
    if isinstance(value, datetime):
        return value
    text = str(value).strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = f"{text[:-1]}+00:00"
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return None


def _acquisition_from_metadata(metadata_docs: list[dict[str, Any]]) -> AcquisitionWindowSchema:
    for doc in metadata_docs:
        parsed = doc.get("parsed_json") or {}
        started = (
            parsed.get("acquisition_started_at")
            or parsed.get("acquisition_start")
            or parsed.get("survey_started_at")
            or parsed.get("survey_date")
        )
        ended = parsed.get("acquisition_ended_at") or parsed.get("acquisition_end") or parsed.get("survey_ended_at")
        window = AcquisitionWindowSchema(started_at=_parse_datetime(started), ended_at=_parse_datetime(ended))
        if window.started_at or window.ended_at:
            return window
    return AcquisitionWindowSchema()


def _sensor_metadata_from_assets(assets: list[IngestedAsset], metadata_docs: list[dict[str, Any]]) -> SensorMetadataSchema:
    raw: dict[str, Any] = {}
    for doc in metadata_docs:
        raw.update(doc.get("parsed_json") or {})
    return SensorMetadataSchema(
        camera=raw.get("camera") or {"image_count": sum(1 for asset in assets if asset.asset_type == "image")},
        sonar=raw.get("sonar") or {"bathymetry_asset_count": sum(1 for asset in assets if asset.asset_type == "bathymetry")},
        gps=raw.get("gps") or {"gps_asset_count": sum(1 for asset in assets if asset.asset_type == "gps")},
        platform=raw.get("platform") or {"source": raw.get("platform_name") or raw.get("equipment")},
        raw=raw,
    )


def _coordinate_system_from_assets(assets: list[IngestedAsset]) -> CoordinateSystemSchema:
    for asset in assets:
        if asset.asset_type == "bathymetry" and asset.metadata.get("crs"):
            return CoordinateSystemSchema(
                crs=asset.metadata.get("crs", "LOCAL_GRID"),
                coordinate_system=asset.metadata.get("coordinate_system", "projected_or_local"),
                horizontal_units=asset.metadata.get("horizontal_units", "meters"),
                vertical_units=asset.metadata.get("vertical_units", "meters"),
                vertical_datum=asset.metadata.get("vertical_datum"),
                vertical_convention=asset.metadata.get("vertical_convention", "elevation_positive_up"),
                bounds=asset.metadata.get("bounds"),
            )
    return CoordinateSystemSchema()


def _location_from_metadata(assets: list[IngestedAsset], metadata_docs: list[dict[str, Any]]) -> dict[str, Any] | None:
    for doc in metadata_docs:
        parsed = doc.get("parsed_json") or {}
        lat = parsed.get("latitude") or parsed.get("lat")
        lon = parsed.get("longitude") or parsed.get("lon") or parsed.get("lng")
        if lat is not None and lon is not None:
            return {
                "name": parsed.get("location_name") or parsed.get("site") or "Uploaded survey location",
                "latitude": float(lat),
                "longitude": float(lon),
                "source": "metadata",
            }

    for asset in assets:
        centroid = asset.metadata.get("centroid")
        if centroid and "latitude" in centroid and "longitude" in centroid:
            return {
                "name": "Uploaded survey location",
                "latitude": float(centroid["latitude"]),
                "longitude": float(centroid["longitude"]),
                "source": asset.filename,
            }
        if centroid and asset.metadata.get("coordinate_system") == "geographic":
            return {
                "name": "Uploaded survey location",
                "latitude": float(centroid["y"]),
                "longitude": float(centroid["x"]),
                "source": asset.filename,
            }
    return None


def validate_survey_upload(files: list[UploadedSurveyFile]) -> IngestionResult:
    if not files:
        raise ValueError("Upload must include at least one file")

    assets: list[IngestedAsset] = []
    seen_names: set[str] = set()
    errors: list[str] = []

    for uploaded in files:
        try:
            filename = _safe_filename(uploaded.filename)
            if filename in seen_names:
                raise ValueError("duplicate file name")
            seen_names.add(filename)
            if not uploaded.data:
                raise ValueError("file is empty")
            if len(uploaded.data) > MAX_FILE_BYTES:
                raise ValueError(f"file exceeds {MAX_FILE_BYTES // (1024 * 1024)} MB")

            content_type = _content_type(filename, uploaded.content_type)
            asset_type = _asset_type(filename, content_type)
            metadata = _extract_metadata(filename, asset_type, uploaded.data)
            assets.append(
                IngestedAsset(
                    filename=filename,
                    content_type=content_type,
                    asset_type=asset_type,
                    size_bytes=len(uploaded.data),
                    metadata=metadata,
                    data=uploaded.data,
                )
            )
        except Exception as exc:
            errors.append(f"{uploaded.filename or 'unnamed file'}: {exc}")

    if errors:
        raise ValueError("; ".join(errors))

    counts: dict[str, int] = {}
    for asset in assets:
        counts[asset.asset_type] = counts.get(asset.asset_type, 0) + 1

    if not any(asset.asset_type in {"bathymetry", "image", "video"} for asset in assets):
        raise ValueError("Upload must include bathymetry, imagery or video files")

    metadata_docs = [asset.metadata for asset in assets if asset.asset_type == "metadata"]
    warnings = []
    if counts.get("gps", 0) == 0:
        warnings.append("No GPS/GeoJSON/GPX file detected")
    if counts.get("bathymetry", 0) == 0:
        warnings.append("No bathymetry CSV/XYZ file detected; processing will use fallback geometry")

    dataset_metadata = {
        "source": "upload",
        "asset_counts": counts,
        "file_count": len(assets),
        "total_size_bytes": sum(asset.size_bytes for asset in assets),
        "warnings": warnings,
        "validation_status": "valid",
    }
    acquisition = _acquisition_from_metadata(metadata_docs)
    sensor_metadata = _sensor_metadata_from_assets(assets, metadata_docs)
    coordinate_system = _coordinate_system_from_assets(assets)
    quality_report = build_upload_quality_report(
        counts=counts,
        warnings=warnings,
        image_checks=[
            {"file_name": asset.filename, **asset.metadata.get("quality", {})}
            for asset in assets
            if asset.asset_type == "image"
        ],
        depth_checks=[
            {"file_name": asset.filename, **asset.metadata.get("depth_outliers", {})}
            for asset in assets
            if asset.asset_type == "bathymetry" and asset.metadata.get("depth_outliers")
        ],
        coverage=[
            {"file_name": asset.filename, **asset.metadata.get("survey_coverage", {})}
            for asset in assets
            if asset.asset_type == "bathymetry" and asset.metadata.get("survey_coverage")
        ],
    )
    location = _location_from_metadata(assets, metadata_docs)
    return IngestionResult(
        dataset_name=_dataset_name(assets, metadata_docs),
        dataset_metadata=dataset_metadata,
        assets=assets,
        location=location,
        acquisition=acquisition,
        sensor_metadata=sensor_metadata,
        coordinate_system=coordinate_system,
        quality_report=quality_report,
    )
