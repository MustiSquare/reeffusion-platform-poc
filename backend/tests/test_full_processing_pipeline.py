from app.models.tables import ModelRun, ProcessingJob, ProcessedAsset, ProcessedDataset, RawAsset, RawDataset
from app.processing import pipeline
from app.testing.fixtures import FakeObjectStore, create_raw_fixture_dataset, in_memory_session


def test_full_processing_pipeline_with_uploaded_bathymetry(monkeypatch, tmp_path):
    from app.core.config import settings
    monkeypatch.setattr(settings, "processed_export_dir", str(tmp_path))
    db = in_memory_session()
    object_store = FakeObjectStore()
    monkeypatch.setattr(pipeline, "store", lambda: object_store)

    raw = create_raw_fixture_dataset(db, object_store)
    job = ProcessingJob(raw_dataset_id=raw.id)
    db.add(job)
    db.commit()

    pipeline.run_processing_pipeline(db, job.id)

    db.refresh(job)
    db.refresh(raw)
    processed = db.get(ProcessedDataset, job.result_processed_dataset_id)
    assets = db.query(ProcessedAsset).filter_by(dataset_id=processed.id).all()
    model_runs = db.query(ModelRun).filter_by(raw_dataset_id=raw.id).all()
    step_details = job.steps or []

    assert raw.status == "processed"
    assert job.status == "completed"
    assert job.current_step == pipeline.STEP_COMPLETED
    assert processed.processing_version == "bathymetry-mesh-v1"
    assert processed.processing_version_json["mesh_formats"] == ["glb", "ply", "obj"]
    assert processed.coordinate_system_json["crs"] == "LOCAL_GRID"
    assert processed.quality_report_json["checks"]["mesh_formats"] == ["glb", "ply", "obj"]
    assert processed.quality_report_json["checks"]["missing_gps"] is True
    assert processed.quality_report_json["checks"]["depth_outliers"]["outlier_count"] == 0
    assert processed.quality_report_json["checks"]["survey_coverage"]["coverage_area"] == 1.0
    assert processed.quality_report_json["scientific_validity"]["status"] == "workflow_validation_only"
    assert processed.quality_report_json["scientific_validity"]["is_scientifically_valid"] is False
    assert processed.quality_report_json["uncertainty"]["qualitative_level"] == "high"
    assert processed.metrics_json["rugosity"] > 1
    assert processed.metrics_json["scientific_validity"]["status"] == "workflow_validation_only"
    assert "quality" in processed.metrics_json
    assert {asset.asset_type for asset in assets} == {
        "point_cloud_xyz",
        "mesh_glb",
        "mesh_ply",
        "mesh_obj",
        "coral_texture",
        "texture_mapping",
    }
    assert object_store.objects[f"processed/{processed.id}/mesh.glb"][:4] == b"glTF"
    assert object_store.objects[f"processed/{processed.id}/mesh.ply"].startswith(b"ply")
    assert b"v " in object_store.objects[f"processed/{processed.id}/mesh.obj"]
    assert object_store.objects[f"processed/{processed.id}/texture_mapping.json"].startswith(b"{")
    assert {run.task for run in model_runs} >= {
        "image_quality_assessment",
        "coral_segmentation",
        "benthic_cover_classification",
        "coral_health_classification",
        "project_ai_layers_to_3d",
    }
    assert all(run.provider == "local" for run in model_runs)
    assert all(run.outputs_json for run in model_runs)
    assert all(run.provenance_json for run in model_runs)
    assert all(isinstance(step, dict) for step in step_details)
    assert {step["name"] for step in step_details} >= {
        pipeline.STEP_VALIDATE_METADATA,
        pipeline.STEP_POINT_CLOUD,
        pipeline.STEP_MESH,
        pipeline.STEP_COMPLETED,
    }
    point_cloud_step = next(step for step in step_details if step["name"] == pipeline.STEP_POINT_CLOUD)
    assert point_cloud_step["output"]["point_count"] == 4
    mesh_step = next(step for step in step_details if step["name"] == pipeline.STEP_MESH)
    assert mesh_step["output"]["texture_mapping"]["texture_file"] == "coral_texture.jpg"
    metrics_step = next(step for step in step_details if step["name"] == pipeline.STEP_METRICS)
    assert metrics_step["output"]["quality"]["scientific_validity"]["is_scientifically_valid"] is False
