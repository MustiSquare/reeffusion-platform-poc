"""Assemble existing tile meshes without reconstructing or bridging survey gaps."""
import io
import hashlib
import json
from copy import deepcopy
from uuid import uuid5, NAMESPACE_URL

import numpy as np
import trimesh
from fastapi import HTTPException
from app.models.tables import ProcessedDataset, ProcessedAsset, RawDataset, Annotation
from app.services.sea_levels import summarize_references, processed_sounding_reference
from app.services.processed_export import record_export
from app.services.tile_seams import join_tile_edges, SEAM_VERSION


def combine_datasets(ids, db, storage):
    ids = sorted(set(map(str, ids)))
    if not 1 <= len(ids) <= 20:
        raise HTTPException(422, "Select between 1 and 20 processed cells")
    if len(ids) == 1:
        result = db.get(ProcessedDataset, ids[0])
        if not result or result.status != "completed":
            raise HTTPException(404, "Completed dataset not found")
        return {"dataset_id": result.id}
    result_id = str(uuid5(NAMESPACE_URL, "reef-combined-v1:" + ",".join(ids)))
    existing = db.get(ProcessedDataset, result_id)
    sources, origins, meshes = [], [], []
    reference = None
    for dataset_id in ids:
        dataset = db.get(ProcessedDataset, dataset_id)
        if not dataset or dataset.status != "completed":
            raise HTTPException(404, "Completed dataset not found")
        coords = dataset.coordinate_system_json or {}
        origin = coords.get("projected_origin")
        if not isinstance(origin, list) or len(origin) != 2 or not all(isinstance(v, (int, float)) and np.isfinite(v) for v in origin):
            raise HTTPException(422, "All cells must have a finite projected origin")
        crs, datum = coords.get("projected_crs"), coords.get("vertical_datum")
        if not crs or not datum or (reference and (crs, datum) != reference):
            raise HTTPException(422, "Cells must use the same projected CRS and vertical reference")
        reference = (crs, datum)
        sources.append(dataset)
        origins.append(np.asarray(origin, dtype=float))
    revisions = {source.id:(source.viewer_config_json or {}).get("revision", "legacy") for source in sources}
    if existing and (existing.viewer_config_json or {}).get("source_revisions") == revisions and (existing.viewer_config_json or {}).get('sounding_reference_version')==2 and 'continuous_surface_version' not in (existing.viewer_config_json or {}) and existing.processing_version != 'combined-supported-grid-v2' and (existing.viewer_config_json or {}).get('tile_seam_version')==SEAM_VERSION:
        return {"dataset_id":result_id}
    revision_key = hashlib.sha256(json.dumps({"sources":revisions,"sounding_reference_version":2,"tile_seam_version":SEAM_VERSION}, sort_keys=True).encode()).hexdigest()[:16]
    anchor = origins[0]
    offsets = [origin - anchor for origin in origins]
    for dataset, offset in zip(sources, offsets):
        asset = next((a for a in dataset.assets if a.asset_type == "mesh_glb"), None)
        if not asset:
            raise HTTPException(422, "Every cell needs a processed mesh")
        scene = trimesh.load(io.BytesIO(storage.get_bytes(asset.object_key)), file_type="glb", force="scene", process=False)
        # Flatten scene graph transforms into vertices before applying the shared origin.
        mesh = scene.to_geometry()
        if not isinstance(mesh, trimesh.Trimesh) or not len(mesh.faces):
            raise HTTPException(422, "Cell mesh contains no surface")
        mesh.apply_translation([float(offset[0]), float(offset[1]), 0])
        meshes.append(mesh)
    from app.api.survey import load_replay
    ref_points=[]
    measured_parts=[]
    tiles=[]
    replay_ids=set()
    for source,offset in zip(sources,offsets):
        data=processed_sounding_reference(source,db,storage,load_replay)
        translated=[[p[0]+float(offset[0]),p[1]+float(offset[1]),*p[2:]] for p in data.get('points',[])]
        ref_points.extend(translated)
        measured_parts.append([p[:3] for p in translated])
        raw_source=db.get(RawDataset,source.raw_dataset_id) if source.raw_dataset_id else None
        metadata=(raw_source.metadata_json or {}) if raw_source else {}
        snapshot=(source.viewer_config_json or {}).get("block_snapshot") or metadata.get("block",{})
        size=snapshot.get("size")
        replay_ids.add(metadata.get("replay_id"))
        valid=isinstance(size,int) and 10<=size<=200 and np.allclose(offset,np.round(offset),rtol=0,atol=1e-6)
        tiles.append((int(round(offset[0])),int(round(offset[1])),size) if valid else None)
    mesh = trimesh.util.concatenate(meshes)
    seam_faces=0
    if len(replay_ids)==1 and None not in replay_ids:
        mesh,seam_faces=join_tile_edges(meshes,tiles,measured_parts)
    csv = io.StringIO()
    np.savetxt(csv, mesh.vertices, delimiter=",", header="x,y,z", comments="", fmt="%.6f")
    area = float(mesh.area)
    triangles = mesh.triangles
    ab, ac = triangles[:, 1, :2] - triangles[:, 0, :2], triangles[:, 2, :2] - triangles[:, 0, :2]
    planar = float(np.abs(ab[:, 0] * ac[:, 1] - ab[:, 1] * ac[:, 0]).sum() / 2)
    raw = db.get(RawDataset, sources[0].raw_dataset_id) if sources[0].raw_dataset_id else None
    values = dict(name=f"Combined reef area ({len(ids)} cells)",
        location_id=sources[0].location_id,
        survey_date=(raw.acquisition_started_at or raw.survey_date) if raw else sources[0].survey_date,
        processing_version="combined-existing-meshes-v1",
        coordinate_system_json={**sources[0].coordinate_system_json, "projected_origin": anchor.tolist(),
            "sea_level_reference":summarize_references([s.coordinate_system_json.get("sea_level_reference") or {} for s in sources],sum((s.coordinate_system_json.get("sea_level_reference") or {}).get("total_soundings",0) for s in sources)) if all(s.coordinate_system_json.get("sea_level_reference") for s in sources) else None},
        quality_report_json={"source_dataset_ids": ids, "notes": [f"Original high-resolution surfaces retained unchanged; {seam_faces} connecting faces added only at narrow, measurement-supported tile joins. Wider gaps preserved. Classes remain provisional."]},
        metrics_json={"surface_area": area, "planar_area": planar, "rugosity": area / planar if planar else None},
        viewer_config_json={"source_dataset_ids": ids, "source_revisions":revisions,"primary": "mesh_glb","sounding_reference_version":2,"tile_seam_version":SEAM_VERSION,"tile_seam_faces":seam_faces})
    result = existing or ProcessedDataset(id=result_id)
    assets = [("mesh.glb", mesh.export(file_type="glb"), "model/gltf-binary", "mesh_glb"),
              ("point_cloud.xyz.csv", csv.getvalue().encode(), "text/csv", "point_cloud_xyz"),
              ("mesh.ply", mesh.export(file_type="ply"), "application/octet-stream", "mesh_ply"),
              ("mesh.obj", mesh.export(file_type="obj").encode(), "text/plain", "mesh_obj")]
    reference_data={'version':2,'points':ref_points,'waterline_offset_m':None,'msl_offset_m':None,'source':'Combined per-sounding vertical distances'}
    assets.append(('sounding_references.json',json.dumps(reference_data).encode(),'application/json','sounding_references'))
    written, old_keys = [], []
    try:
        for name, data, media, kind in assets:
            key = f"processed/{result_id}/revisions/{revision_key}/{name}"
            storage.put_bytes(key, data, media)
            written.append(key)
        for key,value in values.items(): setattr(result,key,value)
        db.add(result)
        db.flush()
        prior = {a.asset_type:a for a in result.assets}
        for (name, _, media, kind), key in zip(assets, written):
            asset = prior.get(kind)
            if asset is None:
                asset = ProcessedAsset(dataset_id=result_id, asset_type=kind)
                db.add(asset)
            else:
                old_keys.append(asset.object_key)
            asset.file_name, asset.object_key, asset.media_type = name, key, media
        for source, offset in ([] if existing else zip(sources, offsets)):
            for annotation in db.query(Annotation).filter_by(processed_dataset_id=source.id).all():
                geometry = deepcopy(annotation.geometry_json)
                def translate(value):
                    if isinstance(value, list) and len(value) >= 3 and all(isinstance(v, (int, float)) for v in value[:3]):
                        return [value[0] + float(offset[0]), value[1] + float(offset[1]), *value[2:]]
                    return [translate(v) for v in value] if isinstance(value, list) else value
                if geometry and "coordinates" in geometry:
                    geometry["coordinates"] = translate(geometry["coordinates"])
                db.add(Annotation(processed_dataset_id=result_id, label=annotation.label, annotation_type=annotation.annotation_type,
                    geometry_json=geometry, properties_json={**(annotation.properties_json or {}), "source_annotation_id": annotation.id, "source_dataset_id": source.id}))
        db.commit()
    except Exception:
        db.rollback()
        for key in written:
            storage.delete_key(key)
        raise
    db.expire(result, ["assets"])
    record_export(db, result, None, storage)
    for key in old_keys:
        if key not in written:
            try: storage.delete_key(key)
            except Exception: pass
    return {"dataset_id": result_id}
