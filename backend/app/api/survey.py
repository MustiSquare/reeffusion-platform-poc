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
from fastapi import APIRouter, Depends, File, HTTPException, Query, Response, UploadFile, Form, Header
from pydantic import BaseModel, Field
from pyproj import Transformer
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from app.db.session import get_db
from app.services.sea_levels import block_reference, sounding_reference, processed_sounding_reference
from app.services.overwrite import require_overwrite, survey_date_key, previous_processing
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
                        "block": (dataset.viewer_config_json or {}).get("block_snapshot") or ((raw.metadata_json or {}).get("block") if raw else None),
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
        replay=json.loads(store().get_bytes(f"replays/{session_id}/replay.json"))
        if replay.get("vertical_reference_version") != 2:
            for extension in ("svlz","svlog"):
                try:
                    source=store().get_bytes(f"replays/{session_id}/source.{extension}")
                except ClientError as exc:
                    if exc.response["Error"]["Code"] in {"NoSuchKey","404"}:continue
                    raise
                decoded=decode_sonar(source,replay.get("source_name",replay["name"]))
                by_time={f['t']:f for f in decoded['frames']}
                for frame in replay['frames']:
                    frame['vertical_samples']=by_time.get(frame['t'],{}).get('vertical_samples',[])
                    frame['sounding_altitudes']=by_time.get(frame['t'],{}).get('sounding_altitudes',[])
                replay['vertical_reference_version']=2
                break
        return replay
    except ClientError as exc:
        if exc.response["Error"]["Code"] in {"NoSuchKey", "404"}:
            raise HTTPException(404, "Replay not found") from exc
        raise


def save_replay(data, name, db=None, survey_name=None, overwrite=False):
    try:
        replay = decode_sonar(data, name)
    except (ValueError, KeyError, TypeError, OverflowError) as exc:
        raise HTTPException(422, f"Cannot decode recording: {exc}") from exc
    digest = hashlib.sha256(data).hexdigest()
    date_key = survey_date_key(replay["started_at"])
    session_id = str(uuid5(NAMESPACE_URL, f"reef-replay:{digest}:{date_key}"))
    if db is not None:
        for raw in db.query(RawDataset).filter_by(source="survey_replay").order_by(RawDataset.created_at.asc()).all():
            if (raw.metadata_json or {}).get("source_sha256") == digest and survey_date_key(raw.acquisition_started_at) == date_key:
                session_id = raw.metadata_json["replay_id"]
                break
    if db is not None:
        previous = [r.id for r in db.query(RawDataset).filter_by(source="survey_replay").all()
                    if (r.metadata_json or {}).get("replay_id") == session_id]
        require_overwrite(db, previous, session_id, overwrite is True)
        for raw_id in previous:
            raw = db.get(RawDataset, raw_id)
            raw.metadata_json = {**raw.metadata_json, "survey_name":(survey_name or name).strip() or name}
        db.commit()
    replay["source_name"] = name
    replay["name"] = (survey_name or name).strip() or name
    replay["id"] = session_id
    replay["source_sha256"] = digest
    s3 = store()
    extension = "svlz" if data[:2] == b"\x1f\x8b" else "svlog"
    s3.put_bytes(f"replays/{session_id}/source.{extension}", data, "application/octet-stream")
    s3.put_bytes(f"replays/{session_id}/replay.json", json.dumps(replay, separators=(",", ":")).encode(), "application/json")
    getattr(load_replay,"cache_clear",lambda:None)()
    return replay


@router.post("/replays")
async def upload_replay(file: UploadFile = File(...), db: Session = Depends(get_db), survey_name: str = Form(default=""), overwrite: bool = Header(default=False, alias="X-Confirm-Overwrite"), _principal=Depends(require_role("editor"))):
    if Path(file.filename or "").suffix.lower() not in {".svlz", ".svlog"}:
        raise HTTPException(422, "Choose a SonarView .svlz or .svlog recording")
    data = await file.read(100 * 1024 * 1024 + 1)
    if len(data) > 100 * 1024 * 1024:
        raise HTTPException(413, "Recording exceeds 100 MB; split it in SonarView")
    return await run_in_threadpool(save_replay, data, Path(file.filename).name, db, survey_name, overwrite)


@router.get("/replays/{session_id}")
def get_replay(session_id: UUID):
    return load_replay(str(session_id))


@router.get("/replays/{session_id}/processing-history")
def replay_processing_history(session_id: UUID, db: Session = Depends(get_db)):
    ids = [raw.id for raw in db.query(RawDataset).filter_by(source="survey_replay").all()
           if (raw.metadata_json or {}).get("replay_id") == str(session_id)]
    return {"processed_at":previous_processing(db,ids),"confirmation_key":str(session_id)}


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
        block = (processed.viewer_config_json or {}).get("block_snapshot") or meta.get("block", {})
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
def import_block(session_id: UUID, body: BlockRequest, db: Session = Depends(get_db), _principal=Depends(require_role("editor")), overwrite: bool = Header(default=False, alias="X-Confirm-Overwrite")):
    replay, points, data = block_data(session_id, body)
    reference = block_reference(replay,body.column,body.row,body.size,body.until)
    sounding_data=sounding_reference(replay,body.column,body.row,body.size,body.until)
    def save_soundings(raw):
        key=f"raw/{raw.id}/sounding_references.json"
        payload=json.dumps(sounding_data,separators=(',',':')).encode()
        store().put_bytes(key,payload,'application/json')
        asset=next((a for a in raw.assets if a.asset_type=='sounding_references'),None)
        if asset is None:
            asset=RawAsset(dataset_id=raw.id,asset_type='sounding_references');db.add(asset)
        asset.file_name='sounding_references.json';asset.object_key=key;asset.media_type='application/json';asset.size_bytes=len(payload)
        raw.coordinate_system_json={**(raw.coordinate_system_json or {}),'sounding_reference_version':2}
    if len(points) < 4 or len({p[0] for p in points}) < 2 or len({p[1] for p in points}) < 2:
        raise HTTPException(422, "Keep displaying/exporting these points; a surface needs at least four points spread across both axes")
    digest = hashlib.sha256(data).hexdigest()
    dataset_id = str(uuid5(NAMESPACE_URL, f"reef-cell/{session_id}/{body.size}/{body.column}/{body.row}"))
    existing = db.query(RawDataset).filter_by(id=dataset_id).with_for_update().first()
    if not existing:
        for candidate in db.query(RawDataset).filter_by(source="survey_replay").order_by(RawDataset.created_at.desc()).all():
            meta = candidate.metadata_json or {}
            cell = meta.get("block", {})
            if meta.get("replay_id") == str(session_id) and all(cell.get(k) == getattr(body,k) for k in ("size","column","row")):
                existing = db.query(RawDataset).filter_by(id=candidate.id).with_for_update().one()
                dataset_id = existing.id
                break
    if existing:
        require_overwrite(db, [existing.id], str(session_id), overwrite is True)
        job = db.query(ProcessingJob).filter_by(raw_dataset_id=dataset_id).order_by(ProcessingJob.created_at.desc()).first()
        same = (existing.metadata_json or {}).get("snapshot_sha256") == digest
        if not same and (existing.metadata_json or {}).get("block") == body.model_dump():
            same = True  # legacy snapshot without a saved checksum
        same = same and (existing.coordinate_system_json or {}).get("sea_level_reference") == reference and (existing.coordinate_system_json or {}).get('sounding_reference_version')==2
        if job and job.status not in ("completed", "failed"):
            if not same:
                raise HTTPException(409, "This cell is still processing; wait before replacing its input")
            return {"dataset_id":dataset_id,"name":existing.name,"existing":True,"job_id":job.id}
        if same:
            return {"dataset_id":dataset_id,"name":existing.name,"existing":True,
                    "job_id":job.id if job and job.status == "completed" and existing.status == "processed" else None}
        metadata = {**(existing.metadata_json or {}), "block":body.model_dump(), "snapshot_sha256":digest,"point_count":len(points)}
        asset = next(a for a in existing.assets if a.asset_type == "bathymetry")
        store().put_bytes(asset.object_key, data, "text/csv")
        asset.size_bytes = len(data)
        asset.metadata_json = metadata
        existing.metadata_json = metadata
        existing.acquisition_ended_at = existing.acquisition_started_at + timedelta(seconds=body.until)
        existing.coordinate_system_json={**(existing.coordinate_system_json or {}),"sea_level_reference":reference}
        existing.status = "uploaded"
        save_soundings(existing)
        db.commit()
        return {"dataset_id":dataset_id,"name":existing.name,"existing":True,"job_id":None}
    inverse = Transformer.from_crs(replay["crs"], 4326, always_xy=True)
    ox, oy = body.column * body.size, body.row * body.size
    lon, lat = inverse.transform(ox + body.size/2, oy + body.size/2)
    metadata = {"snapshot_sha256": digest, "survey_name": replay["name"], "source": "survey_replay", "replay_id": str(session_id), "block": body.model_dump(),
                "projected_crs": replay["crs"], "projected_origin": [ox, oy],
                "point_count": len(points), "source_sha256": replay["source_sha256"],
                "warnings": replay["warnings"], "support_radius_m": 2,
                "surface_note": "Only faces supported within 2 m of measurements are exported; analysis still uses the interpolated grid."}
    coordinate = {"crs": "LOCAL_GRID", "coordinate_system": "projected_or_local", "horizontal_units": "meters",
                  "vertical_units": "meters", "vertical_datum": replay["vertical_datum"],
                  "vertical_convention": "elevation_positive_up", "projected_crs": replay["crs"], "projected_origin": [ox, oy]}
    coordinate["sea_level_reference"] = reference
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
    save_soundings(raw)
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


@lru_cache(maxsize=3)
def load_motion(session_id):
    from app.services.survey_motion import extract_motion
    replay = load_replay(session_id)
    storage = store()
    try:
        data = storage.get_bytes(f"replays/{session_id}/source.svlz")
    except ClientError as exc:
        if exc.response["Error"]["Code"] not in {"NoSuchKey","404"}: raise
        data = storage.get_bytes(f"replays/{session_id}/source.svlog")
    return extract_motion(data, replay["started_at"])


@router.get("/replays/{session_id}/motion")
def replay_motion(session_id: UUID):
    return load_motion(str(session_id))


@router.get("/archive")
def archive_index(db: Session = Depends(get_db)):
    from app.services.survey_archive import archive_surveys
    return [{k:v for k,v in item.items() if k != "cells"} for item in archive_surveys(db)]


def archived_survey(survey_key,db):
    from app.services.survey_archive import archive_surveys
    item=next((s for s in archive_surveys(db) if s["id"]==str(survey_key)),None)
    if item is None:raise HTTPException(404,"Archived survey not found")
    return item


@router.get("/archive/{survey_key}")
def archive_detail(survey_key: UUID,db: Session = Depends(get_db)):
    summary=archived_survey(survey_key,db)
    if not summary['processed_cells']:
        raise HTTPException(409,"Process the survey data before opening its survey map")
    return summary


@router.delete("/archive/{survey_key}")
def archive_delete(survey_key: UUID, db: Session = Depends(get_db), confirmed: bool = Query(False), _principal=Depends(require_role("admin"))):
    if not confirmed:
        raise HTTPException(400,"Confirm permanent deletion of all survey data before proceeding")
    from app.services.dataset_cleanup import delete_archived_survey
    return delete_archived_survey(db,archived_survey(survey_key,db),store())


@router.get("/archive/{survey_key}/conditions")
def archive_conditions(survey_key: UUID,db: Session = Depends(get_db)):
    from app.services.survey_archive import aggregate_conditions
    return aggregate_conditions(archived_survey(survey_key,db),historical_conditions)


@router.get("/processed/{dataset_id}/sounding-references")
def processed_references(dataset_id: UUID, db: Session = Depends(get_db)):
    dataset=db.get(ProcessedDataset,str(dataset_id))
    if not dataset or dataset.status!='completed':raise HTTPException(404,"Completed dataset not found")
    return processed_sounding_reference(dataset,db,store(),load_replay)
