import json
from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import uuid4

import pytest
from app.core.config import settings
from app.services.processed_export import export_processed


def test_dated_export_contains_assets_source_and_manifest(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "processed_export_dir", str(tmp_path))
    asset = SimpleNamespace(id="asset", file_name="mesh.obj", object_key="mesh", asset_type="mesh_obj")
    raw = SimpleNamespace(acquisition_started_at=datetime(2026,7,10,tzinfo=timezone.utc),
                          metadata_json={"block": {"size":50}}, assets=[SimpleNamespace(id="raw",file_name="b.csv",object_key="raw",asset_type="bathymetry")])
    processed = SimpleNamespace(id=str(uuid4()),name="Block",raw_dataset_id="raw",assets=[asset],
                                coordinate_system_json={},quality_report_json={},metrics_json={})
    store = SimpleNamespace(get_bytes=lambda key: b"x,y,z\n0,0,-1" if key=="raw" else b"v 0 0 -1")
    result = export_processed(processed,raw,store)
    folder = tmp_path/result["relative_path"]
    assert result["relative_path"].startswith("2026-07-10/processed/")
    assert {p.name for p in folder.iterdir()} == {"mesh.obj","bathymetry_xyz.csv","metadata.json"}
    assert json.loads((folder/"metadata.json").read_text())["files"][0]["size_bytes"] == 8
    asset.file_name = "../escape.obj"
    with pytest.raises(ValueError): export_processed(processed,raw,store)
