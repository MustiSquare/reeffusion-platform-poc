import json

from sqlalchemy.orm import Session
from app.models.tables import ProcessingJob, RawDataset, ProcessedDataset, ProcessedAsset
from app.processing.synthetic_data import reef_grid, _coral_texture
from app.processing.bathymetry import BathymetryGrid, load_bathymetry_grid
from app.processing.photogrammetry import reconstruct_point_cloud, point_cloud_to_xyz_csv
from app.processing.mesh import export_mesh_glb, export_mesh_obj, export_mesh_ply, texture_mapping_metadata
from app.processing.rugosity import rugosity_from_grid
from app.schemas.domain import ProcessingVersionSchema
from app.services.scientific_quality import build_processing_quality_report
from app.processing.ai_models import (
    TASK_BENTHIC_COVER,
    TASK_CORAL_HEALTH,
    TASK_CORAL_SEGMENTATION,
    TASK_IMAGE_QUALITY,
    TASK_LAYER_PROJECTION,
    generate_ai_insights,
    run_model_task,
)
from app.storage.s3 import store

PROCESSING_VERSION = ProcessingVersionSchema(
    name="bathymetry-mesh",
    version="v1",
    geometry_engine="bathymetry-grid-idw",
    mesh_formats=["glb", "ply", "obj"],
    ai_assisted=True,
)

STEPS = [
    "queued",
    "extracting video frames",
    "validating sonar / GPS / image metadata",
    "running image quality assessment",
    "AI coral image segmentation",
    "AI benthic cover classification",
    "AI coral health classification",
    "building bathymetry-derived point cloud",
    "fusing sonar bathymetry with image-derived features",
    "building textured 3D reef mesh",
    "projecting AI segmentation masks onto 3D model",
    "computing rugosity and habitat metrics",
    "generating AI-ready viewer layers",
    "completed",
]

STEP_QUEUED = "queued"
STEP_EXTRACT_FRAMES = "extracting video frames"
STEP_VALIDATE_METADATA = "validating sonar / GPS / image metadata"
STEP_IMAGE_QUALITY = "running image quality assessment"
STEP_SEGMENTATION = "AI coral image segmentation"
STEP_BENTHIC = "AI benthic cover classification"
STEP_HEALTH = "AI coral health classification"
STEP_POINT_CLOUD = "building bathymetry-derived point cloud"
STEP_FUSION = "fusing sonar bathymetry with image-derived features"
STEP_MESH = "building textured 3D reef mesh"
STEP_PROJECT_LAYERS = "projecting AI segmentation masks onto 3D model"
STEP_METRICS = "computing rugosity and habitat metrics"
STEP_VIEWER_LAYERS = "generating AI-ready viewer layers"
STEP_COMPLETED = "completed"


def _fallback_bathymetry(raw: RawDataset) -> BathymetryGrid:
    X, Y, Z = reef_grid(seed=abs(hash(raw.id)) % 1000, time_shift=0.0)
    return BathymetryGrid(
        x=X,
        y=Y,
        z=Z,
        source="generated fallback bathymetry",
        metadata={"fallback": True, "grid_shape": list(Z.shape)},
    )


def _progress(step: str) -> int:
    return int(STEPS.index(step) / (len(STEPS) - 1) * 100)


def _record_step(
    db: Session,
    job: ProcessingJob,
    step: str,
    status: str = "completed",
    output: dict | None = None,
    error: str | None = None,
) -> None:
    job.status = "running" if status != "failed" else "failed"
    job.current_step = step
    job.progress = _progress(step)
    job.steps = (job.steps or []) + [
        {
            "name": step,
            "status": status,
            "progress": job.progress,
            "output": output or {},
            "error": error,
        }
    ]
    db.commit()


def _asset_counts(raw: RawDataset) -> dict[str, int]:
    counts: dict[str, int] = {}
    for asset in raw.assets or []:
        counts[asset.asset_type] = counts.get(asset.asset_type, 0) + 1
    return counts


def run_processing_pipeline(db: Session, job_id: str):
    job = db.get(ProcessingJob, job_id)
    raw = db.get(RawDataset, job.raw_dataset_id)
    s3 = store()
    try:
        _record_step(db, job, STEP_QUEUED, output={"raw_dataset_id": raw.id})
        counts = _asset_counts(raw)
        _record_step(
            db,
            job,
            STEP_EXTRACT_FRAMES,
            output={"image_assets": counts.get("image", 0), "video_assets": counts.get("video", 0)},
        )
        _record_step(
            db,
            job,
            STEP_VALIDATE_METADATA,
            output={
                "asset_counts": counts,
                "dataset_metadata": raw.metadata_json or {},
                "location_id": raw.location_id,
            },
        )

        ai_inputs = {
            "raw_dataset_id": raw.id,
            "asset_counts": counts,
            "sensor_metadata": raw.sensor_metadata_json or {},
            "coordinate_system": raw.coordinate_system_json or {},
        }
        image_quality = run_model_task(
            db,
            TASK_IMAGE_QUALITY,
            raw,
            ai_inputs,
            raw_dataset_id=raw.id,
        )
        _record_step(db, job, STEP_IMAGE_QUALITY, output=image_quality)

        segmentation = run_model_task(
            db,
            TASK_CORAL_SEGMENTATION,
            raw,
            ai_inputs,
            raw_dataset_id=raw.id,
        )
        _record_step(db, job, STEP_SEGMENTATION, output=segmentation)

        benthic = run_model_task(
            db,
            TASK_BENTHIC_COVER,
            raw,
            ai_inputs,
            raw_dataset_id=raw.id,
        )
        _record_step(db, job, STEP_BENTHIC, output=benthic)

        health = run_model_task(
            db,
            TASK_CORAL_HEALTH,
            raw,
            ai_inputs,
            raw_dataset_id=raw.id,
        )
        _record_step(db, job, STEP_HEALTH, output=health)

        bathymetry = load_bathymetry_grid(raw, s3) or _fallback_bathymetry(raw)
        point_cloud = reconstruct_point_cloud(raw, bathymetry)
        _record_step(
            db,
            job,
            STEP_POINT_CLOUD,
            output={
                "source": point_cloud.source,
                "point_count": int(point_cloud.z.size),
                "metadata": point_cloud.metadata,
            },
        )

        _record_step(
            db,
            job,
            STEP_FUSION,
            output={
                "bathymetry_source": bathymetry.source,
                "bathymetry_metadata": bathymetry.metadata,
                "used_fallback_geometry": bool(bathymetry.metadata.get("fallback")),
            },
        )

        point_cloud_data = point_cloud_to_xyz_csv(point_cloud)
        mesh_glb_data = export_mesh_glb(point_cloud)
        mesh_ply_data = export_mesh_ply(point_cloud)
        mesh_obj_data = export_mesh_obj(point_cloud)
        texture_data = _coral_texture(abs(hash(raw.id)) % 1000)
        texture_metadata = texture_mapping_metadata(point_cloud, "coral_texture.jpg")
        texture_metadata_data = json.dumps(texture_metadata, indent=2).encode("utf-8")
        _record_step(
            db,
            job,
            STEP_MESH,
            output={
                "mesh_glb_bytes": len(mesh_glb_data),
                "mesh_ply_bytes": len(mesh_ply_data),
                "mesh_obj_bytes": len(mesh_obj_data),
                "texture_bytes": len(texture_data),
                "texture_mapping": texture_metadata,
            },
        )

        projected_layers = run_model_task(
            db,
            TASK_LAYER_PROJECTION,
            raw,
            {**ai_inputs, "point_count": int(point_cloud.z.size)},
            raw_dataset_id=raw.id,
        )
        _record_step(db, job, STEP_PROJECT_LAYERS, output=projected_layers)

        base_metrics = rugosity_from_grid(point_cloud.z)
        model_confidences = {
            "image_quality": image_quality.get("confidence"),
            "segmentation": segmentation.get("confidence"),
            "benthic_classification": benthic.get("confidence"),
            "health_classification": health.get("confidence"),
            "projected_3d_layers": projected_layers.get("confidence"),
        }
        quality_report = build_processing_quality_report(
            counts=counts,
            bathymetry_metadata=bathymetry.metadata,
            z_values=point_cloud.z,
            used_fallback_geometry=bool(bathymetry.metadata.get("fallback")),
            point_count=int(point_cloud.z.size),
            mesh_formats=["glb", "ply", "obj"],
            image_quality=image_quality,
            model_confidences=model_confidences,
        )
        metrics = {
            **base_metrics,
            "cover": benthic.get("classes", {}),
            "health": health.get("classes", {}),
            "quality": quality_report.model_dump(mode="json"),
            "scientific_validity": quality_report.scientific_validity,
            "uncertainty": quality_report.uncertainty,
        }
        _record_step(
            db,
            job,
            STEP_METRICS,
            output={
                **base_metrics,
                "quality": {
                    "validation_status": quality_report.validation_status,
                    "workflow_validation": quality_report.workflow_validation,
                    "scientific_validity": quality_report.scientific_validity,
                    "uncertainty": quality_report.uncertainty,
                    "warnings": quality_report.warnings,
                },
            },
        )

        metrics["ai"] = {
            "image_quality": image_quality,
            "segmentation": segmentation,
            "benthic_classification": benthic,
            "health_classification": health,
            "projected_3d_layers": projected_layers,
            "insights": generate_ai_insights(metrics),
        }

        proc = ProcessedDataset(
            raw_dataset_id=raw.id,
            name=f"Processed {raw.name}",
            location_id=raw.location_id,
            processing_version="bathymetry-mesh-v1",
            processing_version_json=PROCESSING_VERSION.model_dump(mode="json"),
            coordinate_system_json=raw.coordinate_system_json or bathymetry.metadata,
            quality_report_json=quality_report.model_dump(mode="json"),
            metrics_json=metrics,
            viewer_config_json={"primary": "point_cloud_xyz", "ai_layers": projected_layers.get("layers", [])},
        )
        db.add(proc)
        db.commit()
        for name, data, ctype, atype in [
            ("point_cloud.xyz.csv", point_cloud_data, "text/csv", "point_cloud_xyz"),
            ("mesh.glb", mesh_glb_data, "model/gltf-binary", "mesh_glb"),
            ("mesh.ply", mesh_ply_data, "application/octet-stream", "mesh_ply"),
            ("mesh.obj", mesh_obj_data, "text/plain", "mesh_obj"),
            ("coral_texture.jpg", texture_data, "image/jpeg", "coral_texture"),
            ("texture_mapping.json", texture_metadata_data, "application/json", "texture_mapping"),
        ]:
            key = f"processed/{proc.id}/{name}"
            s3.put_bytes(key, data, ctype)
            metadata = texture_metadata if atype == "texture_mapping" else {}
            db.add(ProcessedAsset(dataset_id=proc.id, file_name=name, object_key=key, media_type=ctype, asset_type=atype, metadata_json=metadata))
        _record_step(
            db,
            job,
            STEP_VIEWER_LAYERS,
            output={
                "processed_dataset_id": proc.id,
                "assets": ["point_cloud.xyz.csv", "mesh.glb", "mesh.ply", "mesh.obj", "coral_texture.jpg", "texture_mapping.json"],
                "ai_layers": projected_layers.get("layers", []),
            },
        )
        raw.status = "processed"
        job.status = "completed"
        job.current_step = STEP_COMPLETED
        job.progress = 100
        job.result_processed_dataset_id = proc.id
        job.steps = (job.steps or []) + [
            {
                "name": STEP_COMPLETED,
                "status": "completed",
                "progress": 100,
                "output": {"processed_dataset_id": proc.id},
                "error": None,
            }
        ]
        db.commit()
    except Exception as e:
        failed_step = getattr(job, "current_step", None) or STEP_QUEUED
        job.status = "failed"
        job.error = str(e)
        job.steps = (job.steps or []) + [
            {
                "name": failed_step,
                "status": "failed",
                "progress": job.progress,
                "output": {},
                "error": str(e),
            }
        ]
        db.commit()
        raise
