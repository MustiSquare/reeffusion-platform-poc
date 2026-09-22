"""Recorded feed adapter. Normalized frames are also the contract for a future live adapter."""
import csv
import hashlib
import io
import json
from datetime import datetime, timedelta
from functools import lru_cache
from pathlib import Path
from uuid import UUID, uuid4, uuid5, NAMESPACE_URL

import httpx
from botocore.exceptions import ClientError
from fastapi import APIRouter, Depends, File, HTTPException, Query, Response, UploadFile
from pydantic import BaseModel, Field
from pyproj import Transformer
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from app.db.session import get_db
from app.models.tables import RawDataset, RawAsset, SurveyLocation, ProcessingJob, ProcessedDataset
from app.services.processed_export import record_export
from app.services.auth import require_role
from app.services.survey_replay import decode_sonar, block_snapshot
from app.storage.s3 import store

router = APIRouter(prefix="/api/survey", tags=["survey playback"])


@router.get("/results")
def completed_results(db: Session = Depends(get_db)):
    results = []
    datasets = db.query(ProcessedDataset).filter(ProcessedDataset.status == "completed").order_by(ProcessedDataset.created_at.desc()).limit(100).all()
    for dataset in datasets:
        raw = db.get(RawDataset, dataset.raw_dataset_id) if dataset.raw_dataset_id else None
        # A pipeline can create its dataset before finishing. Only expose finished jobs.
        job = db.query(ProcessingJob).filter_by(result_processed_dataset_id=dataset.id, status="completed").first()
        if raw and raw.source == "survey_replay" and not job:
            continue
        export = (dataset.viewer_config_json or {}).get("local_export", {"status": "not_saved"})
        results.append({"id": dataset.id, "name": dataset.name, "completed_at": str(dataset.created_at),
                        "block": (raw.metadata_json or {}).get("block") if raw else None,
                        "replay_id": (raw.metadata_json or {}).get("replay_id") if raw else None,
                        "export": export,
                        "files": [{"name": a.file_name, "asset_type": a.asset_type, "url": f"/api/assets/{a.id}"} for a in dataset.assets]})
    return results


@router.post("/results/{dataset_id}/export")
def retry_export(dataset_id: UUID, db: Session = Depends(get_db), _principal=Depends(require_role("editor"))):
    processed = db.get(ProcessedDataset, str(dataset_id))
    if not processed:
        raise HTTPException(404, "Processed dataset not found")
    raw = db.get(RawDataset, processed.raw_dataset_id) if processed.raw_dataset_id else None
    result = record_export(db, processed, raw, store())
    if result["status"] == "failed":
        raise HTTPException(503, f"Files remain in object storage; local export failed: {result['error']}")
    return result


@lru_cache(maxsize=3)
def load_replay(session_id: str):
    try:
        return json.loads(store().get_bytes(f"replays/{session_id}/replay.json"))
    except ClientError as exc:
        if exc.response["Error"]["Code"] in {"NoSuchKey", "404"}:
            raise HTTPException(404, "Replay not found") from exc
        raise


def save_replay(data, name):
    try:
        replay = decode_sonar(data, name)
    except (ValueError, KeyError, TypeError, OverflowError) as exc:
        raise HTTPException(422, f"Cannot decode recording: {exc}") from exc
    session_id = str(uuid4())
    replay["id"] = session_id
    replay["source_sha256"] = hashlib.sha256(data).hexdigest()
    s3 = store()
    extension = "svlz" if data[:2] == b"\x1f\x8b" else "svlog"
    s3.put_bytes(f"replays/{session_id}/source.{extension}", data, "application/octet-stream")
    s3.put_bytes(f"replays/{session_id}/replay.json", json.dumps(replay, separators=(",", ":")).encode(), "application/json")
    return replay


@router.post("/replays")
async def upload_replay(file: UploadFile = File(...), _principal=Depends(require_role("editor"))):
    if Path(file.filename or "").suffix.lower() not in {".svlz", ".svlog"}:
        raise HTTPException(422, "Choose a SonarView .svlz or .svlog recording")
    data = await file.read(100 * 1024 * 1024 + 1)
    if len(data) > 100 * 1024 * 1024:
        raise HTTPException(413, "Recording exceeds 100 MB; split it in SonarView")
    return await run_in_threadpool(save_replay, data, Path(file.filename).name)


@router.get("/replays/{session_id}")
def get_replay(session_id: UUID):
    return load_replay(str(session_id))


@router.get("/replays/{session_id}/processed-blocks")
def processed_blocks(session_id: UUID, db: Session = Depends(get_db)):
    """All completed cells for this replay, independent of the recent-results limit."""
    rows = (db.query(ProcessedDataset, RawDataset)
            .join(RawDataset, ProcessedDataset.raw_dataset_id == RawDataset.id)
            .join(ProcessingJob, ProcessingJob.result_processed_dataset_id == ProcessedDataset.id)
            .filter(ProcessingJob.status == "completed", RawDataset.source == "survey_replay")
            .order_by(ProcessedDataset.created_at.desc()).all())
    cells = {}
    for processed, raw in rows:
        meta = raw.metadata_json or {}
        if meta.get("replay_id") != str(session_id):
            continue
        block = meta.get("block", {})
        if not all(k in block for k in ("column", "row", "size", "until")):
            continue
        key = f"{block['size']}:{block['column']}:{block['row']}"
        previous = cells.get(key)
        if previous and previous["until"] >= block["until"]:
            continue
        cells[key] = {**block, "result_processed_dataset_id": processed.id, "status": "completed"}
    return list(cells.values())


class BlockRequest(BaseModel):
    column: int
    row: int
    size: int = Field(default=50, ge=10, le=200)
    until: float = Field(ge=0, le=86400, allow_inf_nan=False)


def block_data(session_id, body):
    replay = load_replay(str(session_id))
    points = block_snapshot(replay, body.column, body.row, body.size, body.until)
    if not points:
        raise HTTPException(422, "This block has no measurements at the playback cursor")
    out = io.StringIO()
    # The existing importer preserves these comments. Local coordinates keep 3D precision.
    out.write("# crs=LOCAL_GRID\n# xy_units=meters\n# vertical_datum=vehicle_origin_uncorrected\n# support_radius_m=2\n")
    out.write(f"# projected_crs={replay['crs']}\n# origin_easting={body.column*body.size}\n# origin_northing={body.row*body.size}\n")
    out.write(f"# replay_id={session_id}\n# replay_until_seconds={body.until}\n")
    writer = csv.writer(out)
    writer.writerow(["x", "y", "z"])
    writer.writerows(points)
    return replay, points, out.getvalue().encode()


@router.post("/replays/{session_id}/block.csv")
def export_block(session_id: UUID, body: BlockRequest):
    _, _, data = block_data(session_id, body)
    return Response(data, media_type="text/csv", headers={"Content-Disposition": 'attachment; filename="bathymetry_xyz.csv"'})


@router.post("/replays/{session_id}/blocks")
def import_block(session_id: UUID, body: BlockRequest, db: Session = Depends(get_db), _principal=Depends(require_role("editor"))):
    replay, points, data = block_data(session_id, body)
    if len(points) < 4 or len({p[0] for p in points}) < 2 or len({p[1] for p in points}) < 2:
        raise HTTPException(422, "Keep displaying/exporting these points; a surface needs at least four points spread across both axes")
    digest = hashlib.sha256(data).hexdigest()
    dataset_id = str(uuid5(NAMESPACE_URL, f"{session_id}/{body.size}/{body.column}/{body.row}/{digest}"))
    existing = db.get(RawDataset, dataset_id)
    if existing:
        job = db.query(ProcessingJob).filter_by(raw_dataset_id=dataset_id).order_by(ProcessingJob.created_at.desc()).first()
        return {"dataset_id": dataset_id, "name": existing.name, "existing": True,
                "job_id": job.id if job and job.status != "failed" else None}
    inverse = Transformer.from_crs(replay["crs"], 4326, always_xy=True)
    ox, oy = body.column * body.size, body.row * body.size
    lon, lat = inverse.transform(ox + body.size/2, oy + body.size/2)
    metadata = {"source": "survey_replay", "replay_id": str(session_id), "block": body.model_dump(),
                "projected_crs": replay["crs"], "projected_origin": [ox, oy],
                "point_count": len(points), "source_sha256": replay["source_sha256"],
                "warnings": replay["warnings"], "support_radius_m": 2,
                "surface_note": "Only faces supported within 2 m of measurements are exported; analysis still uses the interpolated grid."}
    coordinate = {"crs": "LOCAL_GRID", "coordinate_system": "projected_or_local", "horizontal_units": "meters",
                  "vertical_units": "meters", "vertical_datum": replay["vertical_datum"],
                  "vertical_convention": "elevation_positive_up", "projected_crs": replay["crs"], "projected_origin": [ox, oy]}
    location = SurveyLocation(name=f"BlueBoat block {body.column}, {body.row}", latitude=lat, longitude=lon)
    db.add(location); db.flush()
    started = datetime.fromisoformat(replay["started_at"])
    raw = RawDataset(id=dataset_id, name=f"{replay['name']} · {body.size} m block {body.column}, {body.row}",
                     source="survey_replay", location_id=location.id, metadata_json=metadata,
                     acquisition_started_at=started, acquisition_ended_at=started+timedelta(seconds=body.until),
                     coordinate_system_json=coordinate,
                     quality_report_json={"validation_status": "warning", "warnings": replay["warnings"],
                                          "scientific_validity": {"is_scientifically_valid": False, "status": "provisional"}})
    db.add(raw)
    key = f"raw/{dataset_id}/bathymetry_xyz.csv"
    store().put_bytes(key, data, "text/csv")
    db.add(RawAsset(dataset_id=dataset_id, file_name="bathymetry_xyz.csv", media_type="text/csv",
                    asset_type="bathymetry", object_key=key, size_bytes=len(data), metadata_json=metadata))
    db.commit()
    return {"dataset_id": dataset_id, "name": raw.name, "existing": False}


@lru_cache(maxsize=128)
def historical_conditions(latitude, longitude, day):
    common = {"latitude": latitude, "longitude": longitude, "start_date": day, "end_date": day, "timezone": "UTC"}
    output = {"date": day, "latitude": latitude, "longitude": longitude, "weather": None, "marine": None, "warnings": []}
    providers = [
        ("weather", "https://archive-api.open-meteo.com/v1/archive", "temperature_2m,wind_speed_10m,wind_direction_10m,surface_pressure", {}),
        ("marine", "https://marine-api.open-meteo.com/v1/marine", "wave_height,wave_direction,wave_period,swell_wave_height", {"models": "era5_ocean"}),
    ]
    with httpx.Client(timeout=15) as client:
        for name, url, variables, extra in providers:
            try:
                response = client.get(url, params={**common, "hourly": variables, **extra})
                response.raise_for_status()
                result = response.json()
                output[name] = {"hourly": result.get("hourly", {}), "units": result.get("hourly_units", {}),
                                "source": "Open-Meteo / ERA5 ocean reanalysis" if name == "marine" else "Open-Meteo historical weather"}
            except (httpx.HTTPError, ValueError):
                output["warnings"].append(f"Historical {name} unavailable for this date/location.")
    return output


@router.get("/conditions")
def conditions(latitude: float = Query(ge=-90, le=90), longitude: float = Query(ge=-180, le=180), day: str = Query(pattern=r"^\d{4}-\d{2}-\d{2}$")):
    try:
        datetime.strptime(day, "%Y-%m-%d")
    except ValueError as exc:
        raise HTTPException(422, "Invalid survey date") from exc
    # Quantize to regional model resolution; avoid fetching on every boat movement.
    return historical_conditions(round(latitude, 2), round(longitude, 2), day)


class CombinedAreaRequest(BaseModel):
    dataset_ids: list[UUID] = Field(min_length=1, max_length=20)


@router.post("/combined-area")
def combined_area(body: CombinedAreaRequest, db: Session = Depends(get_db), _principal=Depends(require_role("editor"))):
    from app.services.combined_survey import combine_datasets
    return combine_datasets(body.dataset_ids, db, store())
