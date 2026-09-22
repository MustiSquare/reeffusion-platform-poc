"""Mirror processed products to dated host folders without replacing source data."""
import hashlib
import json
from datetime import timezone
from pathlib import Path
from uuid import UUID, uuid4

from app.core.config import settings


def export_processed(processed, raw, object_store):
    root = Path(settings.processed_export_dir).resolve()
    date = (getattr(raw, "acquisition_started_at", None) or getattr(raw, "survey_date", None)
            or processed.survey_date or processed.created_at)
    if date.tzinfo:
        date = date.astimezone(timezone.utc)
    relative = Path(date.strftime("%Y-%m-%d")) / "processed" / str(UUID(processed.id))
    destination = (root / relative).resolve()
    if not destination.is_relative_to(root):
        raise ValueError("Export path must remain inside the configured export directory")
    destination.mkdir(parents=True, exist_ok=True)
    files = []

    def write(name, data, asset_type, asset_id=None):
        # Filenames are metadata, not trusted paths (including Windows separators).
        if not name or name in {".", ".."} or any(c in name for c in '/\\:'):
            raise ValueError("Invalid export filename")
        path = (destination / name).resolve()
        if path.parent != destination:
            raise ValueError("Export file escapes its dataset folder")
        temp = destination / f".{name}.{uuid4().hex}.tmp"
        try:
            temp.write_bytes(data)
            temp.replace(path)
        finally:
            temp.unlink(missing_ok=True)
        files.append({"name": name, "size_bytes": len(data), "sha256": hashlib.sha256(data).hexdigest(),
                      "asset_type": asset_type, "asset_id": asset_id})

    for asset in processed.assets:
        write(asset.file_name, object_store.get_bytes(asset.object_key), asset.asset_type, asset.id)
    if raw:
        bathymetry = next((a for a in raw.assets if a.asset_type == "bathymetry" and a.file_name.lower().endswith((".csv", ".xyz"))), None)
        if bathymetry:
            write("bathymetry_xyz.csv", object_store.get_bytes(bathymetry.object_key), "source_bathymetry", bathymetry.id)
    metadata = {"processed_dataset_id": processed.id, "name": processed.name,
                "raw_dataset_id": processed.raw_dataset_id, "survey_date_utc": date.isoformat(),
                "coordinate_system": processed.coordinate_system_json,
                "quality_report": processed.quality_report_json, "metrics": processed.metrics_json,
                "source_metadata": getattr(raw, "metadata_json", None), "files": files.copy()}
    write("metadata.json", json.dumps(metadata, indent=2, default=str).encode(), "metadata")
    return {"status": "saved", "relative_path": relative.as_posix(), "files": files}


def record_export(db, processed, raw, object_store):
    try:
        result = export_processed(processed, raw, object_store)
    except Exception as exc:
        result = {"status": "failed", "error": str(exc)}
    processed.viewer_config_json = {**(processed.viewer_config_json or {}), "local_export": result}
    db.commit()
    return result
