"""Bounded map preview of measured soundings, never interpolated mesh vertices."""
import csv
import io
import json
import math
from pyproj import Transformer
from app.models.tables import RawDataset, ProcessedDataset


def archive_coverage(summary, db, storage, size, limit=6000):
    cells = []
    warnings = []
    for cell in summary["cells"]:
        if cell["size"] != size: continue
        dataset = db.get(ProcessedDataset,cell["dataset_id"]) if cell.get("dataset_id") else None
        raw = db.get(RawDataset,dataset.raw_dataset_id) if dataset and dataset.raw_dataset_id else None
        if raw is None:
            for member in summary["raw"]:
                candidate = db.get(RawDataset,member["id"])
                block = (candidate.metadata_json or {}).get("block",{})
                if all(block.get(k)==cell[k] for k in ("column","row","size")):
                    raw = candidate; break
        if raw is None: continue
        coords = (dataset.coordinate_system_json if dataset else raw.coordinate_system_json) or {}
        crs = coords.get("projected_crs")
        if not crs: continue
        origin = coords.get("projected_origin") or [cell["column"]*size,cell["row"]*size]
        reference = next((a for a in dataset.assets if a.asset_type=="sounding_references"),None) if dataset else None
        if reference:
            rows = json.loads(storage.get_bytes(reference.object_key)).get("points",[])
        else:
            # A raw file may have advanced beyond a completed snapshot: do not mislabel it.
            snapshot = (dataset.viewer_config_json or {}).get("block_snapshot") if dataset else None
            if snapshot and snapshot != (raw.metadata_json or {}).get("block"):
                warnings.append(f"Measured coverage unavailable for older snapshot {cell['key']}")
                continue
            asset = next((a for a in raw.assets if a.asset_type=="bathymetry"),None)
            if not asset: continue
            text=storage.get_bytes(asset.object_key).decode("utf-8-sig")
            rows=[[float(r[k]) for k in ("x","y","z")] for r in csv.DictReader(io.StringIO("\n".join(line for line in text.splitlines() if not line.startswith("#"))))]
        points = [p[:3] for p in rows if len(p)>=3 and all(math.isfinite(v) for v in p[:3])]
        cells.append((cell["key"],points,crs,origin))
    total=sum(len(points) for _,points,_,_ in cells)
    stride=max(1,math.ceil(total/limit)); seen=0; result=[]
    for key,points,crs,origin in cells:
        selected=points[(stride-seen%stride)%stride::stride]; seen+=len(points)
        if not selected: continue
        transform=Transformer.from_crs(crs,4326,always_xy=True)
        lons,lats=transform.transform([p[0]+origin[0] for p in selected],[p[1]+origin[1] for p in selected])
        result.extend([[round(lon,7),round(lat,7),p[2],key] for lon,lat,p in zip(lons,lats,selected)])
    return {"points":result,"total_points":total,"sampled":stride>1,"warnings":warnings,"source":"Measured sounding positions"}
