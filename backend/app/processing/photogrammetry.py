import csv
import io
from dataclasses import dataclass

import numpy as np

from app.processing.bathymetry import BathymetryGrid


@dataclass(frozen=True)
class PointCloud:
    x: np.ndarray
    y: np.ndarray
    z: np.ndarray
    source: str
    metadata: dict


def reconstruct_point_cloud(raw_dataset, bathymetry: BathymetryGrid) -> PointCloud:
    image_assets = [
        asset
        for asset in getattr(raw_dataset, "assets", []) or []
        if (getattr(asset, "asset_type", "") or "").lower() == "image"
        or (getattr(asset, "media_type", "") or "").lower().startswith("image/")
    ]
    return PointCloud(
        x=bathymetry.x,
        y=bathymetry.y,
        z=bathymetry.z,
        source=f"bathymetry-derived point cloud from {bathymetry.source}",
        metadata={
            **bathymetry.metadata,
            "image_asset_count": len(image_assets),
            "method": "structured bathymetry surface reconstruction",
        },
    )


def point_cloud_to_xyz_csv(point_cloud: PointCloud) -> bytes:
    out = io.StringIO()
    writer = csv.writer(out)
    support = point_cloud.metadata.get("support_mask")
    mask = np.asarray(support, dtype=bool).ravel() if support is not None else None
    writer.writerow(["x", "y", "z", "supported"] if mask is not None else ["x", "y", "z"])
    for i, (x, y, z) in enumerate(zip(point_cloud.x.ravel(), point_cloud.y.ravel(), point_cloud.z.ravel())):
        row = [round(float(x), 4), round(float(y), 4), round(float(z), 4)]
        writer.writerow(row + [int(mask[i])] if mask is not None else row)
    return out.getvalue().encode("utf-8")
