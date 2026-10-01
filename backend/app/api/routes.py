import json
from uuid import uuid5, NAMESPACE_URL

from fastapi import APIRouter, Depends, UploadFile, File, Form, HTTPException, Response, Header
from sqlalchemy.orm import Session
from app.db.session import get_db
from app.models.tables import *
from app.storage.s3 import store
from app.processing.synthetic_data import generate_demo
from app.processing.ml_registry import ensure_ml_registry
from app.processing.comparison import compare_metrics
from app.processing.ai_models import TASK_REPORT_GENERATION, run_model_task
from app.services.ai_agents import generate_reef_report, answer_reef_question
from app.services.auth import require_role
from app.services.dataset_cleanup import delete_processed_dataset, delete_raw_dataset
from app.services.ingestion import UploadedSurveyFile, validate_survey_upload
from app.schemas.api import AnnotationIn, ComparisonIn, ReefReportIn, ReefQuestionIn
from app.worker import process_dataset
from app.services.overwrite import require_overwrite, survey_date_key

router=APIRouter(prefix="/api")

def ds_summary(d):
    return {"id":d.id,"name":d.name,"raw_dataset_id":getattr(d,"raw_dataset_id",None),"viewer_config":getattr(d,"viewer_config_json",None),"status":getattr(d,"status",None),"survey_date":str(getattr(d,"survey_date",'')),"acquisition_started_at":str(getattr(d,"acquisition_started_at",None) or "") if hasattr(d,"acquisition_started_at") else None,"acquisition_ended_at":str(getattr(d,"acquisition_ended_at",None) or "") if hasattr(d,"acquisition_ended_at") else None,"location": d.location.name if getattr(d,"location",None) else None,"file_count":len(getattr(d,"assets",[]) or []),"metadata":getattr(d,"metadata_json",None),"sensor_metadata":getattr(d,"sensor_metadata_json",None),"coordinate_system":getattr(d,"coordinate_system_json",None),"quality_report":getattr(d,"quality_report_json",None),"metrics":getattr(d,"metrics_json",None),"processing_version":getattr(d,"processing_version",None),"processing_version_info":getattr(d,"processing_version_json",None)}


def _polygon_planar_area(coords: list[list[float]]) -> float:
    if len(coords) < 3:
        return 0.0
    area = 0.0
    for i, p1 in enumerate(coords):
        p2 = coords[(i + 1) % len(coords)]
        area += float(p1[0]) * float(p2[1]) - float(p2[0]) * float(p1[1])
    return abs(area) / 2.0


def _step_name(step):
    if isinstance(step, dict):
        return step.get("name")
    return step

@router.post("/datasets/upload")
async def upload(
    files: list[UploadFile]=File(...),
    survey_name: str | None = Form(default=None),
    location_name: str | None = Form(default=None),
    latitude: float | None = Form(default=None),
    longitude: float | None = Form(default=None),
    acquisition_started_at: str | None = Form(default=None),
    acquisition_ended_at: str | None = Form(default=None),
    camera_model: str | None = Form(default=None),
    sonar_model: str | None = Form(default=None),
    gps_model: str | None = Form(default=None),
    platform_name: str | None = Form(default=None),
    crs: str | None = Form(default=None),
    vertical_datum: str | None = Form(default=None),
    db: Session=Depends(get_db),
    overwrite: bool = Header(default=False, alias="X-Confirm-Overwrite"),
    _principal=Depends(require_role("editor")),
):
    uploaded = [
        UploadedSurveyFile(filename=f.filename or "", content_type=f.content_type, data=await f.read())
        for f in files
    ]
    form_metadata = {
        k: v
        for k, v in {
            "survey_name": survey_name,
            "location_name": location_name,
            "latitude": latitude,
            "longitude": longitude,
            "acquisition_started_at": acquisition_started_at,
            "acquisition_ended_at": acquisition_ended_at,
            "camera": {"model": camera_model} if camera_model else None,
            "sonar": {"model": sonar_model} if sonar_model else None,
            "gps": {"model": gps_model} if gps_model else None,
            "platform": {"name": platform_name} if platform_name else None,
            "crs": crs,
            "vertical_datum": vertical_datum,
        }.items()
        if v not in (None, "")
    }
    if form_metadata:
        uploaded.append(
            UploadedSurveyFile(
                filename="upload_metadata.json",
                content_type="application/json",
                data=json.dumps(form_metadata).encode("utf-8"),
            )
        )
    try:
        ingestion = validate_survey_upload(uploaded)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    if not survey_name and ingestion.dataset_name == "Uploaded Reef Dataset":
        ingestion.dataset_name = next((a.filename for a in ingestion.assets if a.asset_type in ("bathymetry","image","video")), ingestion.dataset_name)
    # Match content plus acquisition date, independent of display names.
    signature = sorted((a.asset_type, a.metadata.get("sha256")) for a in ingestion.assets if a.filename != "upload_metadata.json")
    date_key = survey_date_key(ingestion.acquisition.started_at)
    for candidate in db.query(RawDataset).filter_by(source="upload").order_by(RawDataset.created_at.desc()).all():
        prior = sorted((a.asset_type, (a.metadata_json or {}).get("sha256")) for a in candidate.assets if a.file_name != "upload_metadata.json")
        candidate_date = survey_date_key(candidate.acquisition_started_at)
        # SQLite and legacy rows may omit the UTC offset.
        same_date = candidate_date == date_key
        if prior == signature and same_date:
            require_overwrite(db, [candidate.id], candidate.id, overwrite is True)
            candidate.name = ingestion.dataset_name
            candidate.metadata_json = ingestion.dataset_metadata
            candidate.quality_report_json = ingestion.quality_report.model_dump(mode="json")
            candidate.acquisition_ended_at = ingestion.acquisition.ended_at
            candidate.coordinate_system_json = ingestion.coordinate_system.model_dump(mode="json")
            candidate.sensor_metadata_json = ingestion.sensor_metadata.model_dump(mode="json")
            db.commit()
            return {"dataset_id":candidate.id,"name":candidate.name,"existing":True,
                    "file_count":len(candidate.assets),"asset_counts":ingestion.dataset_metadata["asset_counts"],
                    "warnings":ingestion.dataset_metadata["warnings"],"location_id":candidate.location_id}

    location_id = None
    if ingestion.location:
        loc = SurveyLocation(
            name=ingestion.location["name"],
            latitude=ingestion.location["latitude"],
            longitude=ingestion.location["longitude"],
            crs=ingestion.location.get("crs", "EPSG:4326"),
            coordinate_system=ingestion.location.get("coordinate_system", "geographic"),
            vertical_datum=ingestion.coordinate_system.vertical_datum,
            geom_geojson={
                "type": "Point",
                "coordinates": [ingestion.location["longitude"], ingestion.location["latitude"]],
            },
            metadata_json={"source": ingestion.location.get("source"), "coordinate_system": ingestion.coordinate_system.model_dump(mode="json")},
        )
        db.add(loc)
        db.commit()
        location_id = loc.id

    s3 = store()
    raw = RawDataset(
        id=str(uuid5(NAMESPACE_URL, "reef-upload:" + json.dumps([signature,date_key]))),
        name=ingestion.dataset_name,
        source="upload",
        location_id=location_id,
        acquisition_started_at=ingestion.acquisition.started_at,
        acquisition_ended_at=ingestion.acquisition.ended_at,
        sensor_metadata_json=ingestion.sensor_metadata.model_dump(mode="json"),
        coordinate_system_json=ingestion.coordinate_system.model_dump(mode="json"),
        quality_report_json=ingestion.quality_report.model_dump(mode="json"),
        metadata_json=ingestion.dataset_metadata,
    )
    db.add(raw)
    db.commit()
    for asset in ingestion.assets:
        key = f"raw/{raw.id}/{asset.filename}"
        s3.put_bytes(key, asset.data, asset.content_type)
        db.add(
            RawAsset(
                dataset_id=raw.id,
                file_name=asset.filename,
                media_type=asset.content_type,
                asset_type=asset.asset_type,
                object_key=key,
                size_bytes=asset.size_bytes,
                metadata_json=asset.metadata,
            )
        )
    db.commit()
    return {
        "dataset_id": raw.id,
        "name": raw.name,
        "file_count": len(ingestion.assets),
        "asset_counts": ingestion.dataset_metadata["asset_counts"],
        "warnings": ingestion.dataset_metadata["warnings"],
        "location_id": location_id,
    }

@router.post("/datasets/demo/generate")
def demo(db: Session=Depends(get_db), _principal=Depends(require_role("editor"))): return generate_demo(db, pair=True)

@router.get("/datasets/raw")
def raw_list(db: Session=Depends(get_db)):
    from app.services.survey_repair import visible
    return [ds_summary(x) for x in db.query(RawDataset).order_by(RawDataset.created_at.desc()).all() if visible(x)]

@router.get("/datasets/raw/{dataset_id}")
def raw_get(dataset_id: str, db: Session=Depends(get_db)):
    d=db.get(RawDataset,dataset_id)
    if not d: raise HTTPException(404)
    return {**ds_summary(d),"assets":[{"id":a.id,"file_name":a.file_name,"media_type":a.media_type,"asset_type":a.asset_type,"size_bytes":a.size_bytes,"metadata":a.metadata_json,"url":f"/api/assets/{a.id}"} for a in d.assets]}

@router.delete("/datasets/raw/{dataset_id}")
def raw_delete(dataset_id: str, db: Session=Depends(get_db), _principal=Depends(require_role("admin"))):
    result = delete_raw_dataset(db, dataset_id, store())
    if not result["deleted"]:
        raise HTTPException(404)
    return result

@router.get("/datasets/processed")
def proc_list(db: Session=Depends(get_db)):
    from app.services.survey_repair import visible
    return [ds_summary(x) for x in db.query(ProcessedDataset).order_by(ProcessedDataset.created_at.desc()).all() if visible(x)]

@router.get("/datasets/processed/{dataset_id}")
def proc_get(dataset_id: str, db: Session=Depends(get_db)):
    d=db.get(ProcessedDataset,dataset_id)
    if not d: raise HTTPException(404)
    config=d.viewer_config_json or {}
    if config.get("source_dataset_ids") and config.get("generation_state", "active") == "active":
        from app.services.combined_survey import combine_datasets
        from app.services.tile_seams import SEAM_VERSION
        if "continuous_surface_version" in config or d.processing_version == "combined-supported-grid-v2" or config.get("tile_seam_version") != SEAM_VERSION:
            combine_datasets(config["source_dataset_ids"],db,store())
            db.refresh(d)
    return {**ds_summary(d),"viewer_config":d.viewer_config_json,"assets":[{"id":a.id,"file_name":a.file_name,"asset_type":a.asset_type,"media_type":a.media_type,"metadata":a.metadata_json,"url":f"/api/assets/{a.id}"} for a in d.assets]}

@router.delete("/datasets/processed/{dataset_id}")
def proc_delete(dataset_id: str, db: Session=Depends(get_db), _principal=Depends(require_role("admin"))):
    result = delete_processed_dataset(db, dataset_id, store())
    if not result["deleted"]:
        raise HTTPException(404)
    return result

@router.post("/jobs/process/{dataset_id}")
def process(dataset_id: str, db: Session=Depends(get_db), overwrite: bool = Header(default=False, alias="X-Confirm-Overwrite"), _principal=Depends(require_role("editor"))):
    raw = db.query(RawDataset).filter_by(id=dataset_id).with_for_update().first()
    if not raw: raise HTTPException(404)
    from app.services.survey_repair import check_mutation, visible
    if not visible(raw): raise HTTPException(409, "Legacy or staged cells cannot be overwritten; rebuild the survey")
    if (raw.metadata_json or {}).get("replay_id"):
        check_mutation(db, raw.metadata_json["replay_id"])
    active = db.query(ProcessingJob).filter(ProcessingJob.raw_dataset_id==dataset_id, ProcessingJob.status.notin_(["completed","failed"])).first()
    if active: return {"job_id":active.id,"status":active.status}
    key = (raw.metadata_json or {}).get("replay_id") or raw.id
    require_overwrite(db, [raw.id], key, overwrite is True)
    job=ProcessingJob(raw_dataset_id=dataset_id); db.add(job); db.commit(); process_dataset.delay(job.id); return {"job_id":job.id,"status":job.status}

@router.get("/jobs/{job_id}")
def job(job_id: str, db: Session=Depends(get_db)):
    j=db.get(ProcessingJob,job_id)
    if not j: raise HTTPException(404)
    step_details = j.steps or []
    return {"id":j.id,"status":j.status,"current_step":j.current_step,"progress":j.progress,"error":j.error,"result_processed_dataset_id":j.result_processed_dataset_id,"steps":[s for s in (_step_name(step) for step in step_details) if s],"step_details":step_details}

@router.get("/assets/{asset_id}")
def asset(asset_id: str, db: Session=Depends(get_db)):
    a=db.get(RawAsset,asset_id) or db.get(ProcessedAsset,asset_id)
    if not a: raise HTTPException(404)
    data=store().get_bytes(a.object_key)
    return Response(data, media_type=a.media_type, headers={"Content-Disposition":f'inline; filename="{a.file_name}"'})

@router.get("/annotations/{processed_dataset_id}")
def ann_list(processed_dataset_id: str, db: Session=Depends(get_db)):
    return [{"id":a.id,"label":a.label,"annotation_type":a.annotation_type,"geometry_json":a.geometry_json,"properties_json":a.properties_json} for a in db.query(Annotation).filter_by(processed_dataset_id=processed_dataset_id).all()]

@router.post("/annotations/{processed_dataset_id}")
def ann_create(processed_dataset_id: str, body: AnnotationIn, db: Session = Depends(get_db), _principal=Depends(require_role("editor"))):
    if not db.get(ProcessedDataset, processed_dataset_id):
        raise HTTPException(404)

    data = body.model_dump()

    if data["annotation_type"] == "surface_area":
        coords = data["geometry_json"].get("coordinates") or []
        data["properties_json"] = {
            **(data.get("properties_json") or {}),
            "vertex_count": len(coords),
            "planar_area": _polygon_planar_area(coords),
        }

    a = Annotation(processed_dataset_id=processed_dataset_id, **data)
    db.add(a)
    db.commit()
    db.refresh(a)

    return {
        "id": a.id,
        "label": a.label,
        "annotation_type": a.annotation_type,
        "geometry_json": a.geometry_json,
        "properties_json": a.properties_json,
    }

@router.put("/annotations/{annotation_id}")
def ann_update(annotation_id: str, body: AnnotationIn, db: Session=Depends(get_db), _principal=Depends(require_role("editor"))):
    a=db.get(Annotation,annotation_id)
    if not a: raise HTTPException(404)
    for k,v in body.model_dump().items(): setattr(a,k,v)
    db.commit(); return {"id":a.id}

@router.delete("/annotations/{annotation_id}")
def ann_delete(annotation_id: str, db: Session=Depends(get_db), _principal=Depends(require_role("editor"))):
    a=db.get(Annotation,annotation_id)
    if not a: raise HTTPException(404)
    db.delete(a); db.commit(); return {"deleted":annotation_id}

@router.post("/comparison")
def compare(body: ComparisonIn, db: Session=Depends(get_db), _principal=Depends(require_role("editor"))):
    a=db.get(ProcessedDataset,body.dataset_a_id); b=db.get(ProcessedDataset,body.dataset_b_id)
    if not a or not b: raise HTTPException(404)
    metrics=compare_metrics(a.metrics_json or {}, b.metrics_json or {})
    r=ComparisonResult(dataset_a_id=a.id,dataset_b_id=b.id,metrics_json=metrics); db.add(r); db.commit(); return {"comparison_id":r.id,"metrics":metrics}

@router.post("/ai-agents/report")
def ai_report(body: ReefReportIn, db: Session=Depends(get_db), _principal=Depends(require_role("editor"))):
    dataset = db.get(ProcessedDataset, body.dataset_id)
    if not dataset:
        raise HTTPException(404)
    comparison = None
    if body.comparison_dataset_id:
        comparison = db.get(ProcessedDataset, body.comparison_dataset_id)
        if not comparison:
            raise HTTPException(404)
    return run_model_task(
        db,
        TASK_REPORT_GENERATION,
        dataset,
        {
            "dataset_id": dataset.id,
            "comparison_dataset_id": getattr(comparison, "id", None),
            "metrics_keys": sorted((dataset.metrics_json or {}).keys()),
        },
        processed_dataset_id=dataset.id,
        comparison_dataset=comparison,
    )

@router.post("/ai-agents/question")
def ai_question(body: ReefQuestionIn, db: Session=Depends(get_db), _principal=Depends(require_role("editor"))):
    dataset = db.get(ProcessedDataset, body.dataset_id)
    if not dataset:
        raise HTTPException(404)
    comparison = None
    if body.comparison_dataset_id:
        comparison = db.get(ProcessedDataset, body.comparison_dataset_id)
        if not comparison:
            raise HTTPException(404)
    return answer_reef_question(dataset, body.question, comparison)

@router.get("/ml/models")
def models(db: Session=Depends(get_db)):
    ensure_ml_registry(db)
    return [{"id":m.id,"name":m.name,"task":m.task,"status":m.status,"version":m.version,"metadata":m.metadata_json} for m in db.query(MLModelRegistryEntry).all()]

def _classification_payload(processed_dataset_id: str, db: Session):
    dataset = db.get(ProcessedDataset, processed_dataset_id)
    if not dataset:
        raise HTTPException(404)
    metrics = dataset.metrics_json or {}
    return {
        "processed_dataset_id": processed_dataset_id,
        "model_version": dataset.processing_version,
        "benthic_cover": metrics.get("cover", {}),
        "health": metrics.get("health", {}),
        "ai": metrics.get("ai", {}),
    }


@router.post("/ml/classify/{processed_dataset_id}")
def classify(processed_dataset_id: str, db: Session=Depends(get_db), _principal=Depends(require_role("editor"))):
    return _classification_payload(processed_dataset_id, db)


@router.get("/ml/model-runs")
def model_runs(dataset_id: str | None = None, db: Session=Depends(get_db)):
    q = db.query(ModelRun).order_by(ModelRun.created_at.desc())
    if dataset_id:
        q = q.filter((ModelRun.raw_dataset_id == dataset_id) | (ModelRun.processed_dataset_id == dataset_id))
    return [
        {
            "id": r.id,
            "provider": r.provider,
            "task": r.task,
            "model_name": r.model_name,
            "model_version": r.model_version,
            "status": r.status,
            "confidence": r.confidence,
            "raw_dataset_id": r.raw_dataset_id,
            "processed_dataset_id": r.processed_dataset_id,
            "inputs": r.inputs_json,
            "outputs": r.outputs_json,
            "provenance": r.provenance_json,
            "error": r.error,
            "created_at": str(r.created_at),
        }
        for r in q.limit(100).all()
    ]


@router.post("/datasets/survey/generate")
def survey_generate(db: Session = Depends(get_db), _principal=Depends(require_role("editor"))):
    return generate_demo(db, pair=True)
