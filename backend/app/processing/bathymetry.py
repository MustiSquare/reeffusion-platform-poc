import csv
import io
from dataclasses import dataclass
from typing import Iterable

import numpy as np


DEPTH_NAMES = {"depth", "depth_m", "depth_meter", "depth_meters", "depth_ft", "depth_feet"}
ELEVATION_NAMES = {"z", "elevation", "elevation_m", "altitude", "height"}
LON_NAMES = {"lon", "lng", "longitude"}
LAT_NAMES = {"lat", "latitude"}
FEET_TO_METERS = 0.3048


@dataclass(frozen=True)
class BathymetryGrid:
    x: np.ndarray
    y: np.ndarray
    z: np.ndarray
    source: str
    metadata: dict


def _numeric(row: dict, names: Iterable[str]) -> float | None:
    for name in names:
        if name in row and row[name] not in (None, ""):
            return float(row[name])
    return None


def _comment_metadata(lines: list[str]) -> dict:
    metadata = {}
    for line in lines:
        stripped = line.strip()
        if not stripped.startswith("#"):
            continue
        value = stripped.lstrip("#").strip()
        if "=" in value:
            key, raw = value.split("=", 1)
        elif ":" in value:
            key, raw = value.split(":", 1)
        else:
            continue
        metadata[key.strip().lower()] = raw.strip()
    return metadata


def _clean_data_text(text: str) -> str:
    return "\n".join(line for line in text.splitlines() if line.strip() and not line.strip().startswith("#"))


def _unit_factor(unit: str | None) -> tuple[float, str]:
    normalized = (unit or "").strip().lower()
    if normalized in {"ft", "feet", "foot", "us_survey_foot"}:
        return FEET_TO_METERS, "meters"
    return 1.0, "meters" if normalized in {"", "m", "meter", "meters"} else normalized


def _header_unit(name: str, fallback: str | None = None) -> str | None:
    lower = name.lower()
    if lower.endswith("_ft") or lower.endswith("_feet"):
        return "feet"
    if lower.endswith("_m") or lower.endswith("_meter") or lower.endswith("_meters"):
        return "meters"
    return fallback


def _metadata_for_points(
    pts: np.ndarray,
    source: str,
    regular_grid: bool,
    grid_shape: tuple[int, int],
    comments: dict | None = None,
    interpolation: dict | None = None,
    coordinate_columns: tuple[str, str] = ("x", "y"),
    vertical_convention: str = "elevation_positive_up",
    z_unit: str = "meters",
) -> dict:
    comments = comments or {}
    x_col, y_col = coordinate_columns
    geographic = x_col in LON_NAMES and y_col in LAT_NAMES
    crs = comments.get("crs") or comments.get("epsg")
    if crs and str(crs).upper().startswith("EPSG:"):
        normalized_crs = str(crs).upper()
    elif crs:
        normalized_crs = f"EPSG:{crs}" if str(crs).isdigit() else str(crs)
    else:
        normalized_crs = "EPSG:4326" if geographic else "LOCAL_GRID"
    bounds = {
        "min_x": float(np.min(pts[:, 0])),
        "min_y": float(np.min(pts[:, 1])),
        "max_x": float(np.max(pts[:, 0])),
        "max_y": float(np.max(pts[:, 1])),
        "min_z": float(np.min(pts[:, 2])),
        "max_z": float(np.max(pts[:, 2])),
    }
    metadata = {
        "point_count": int(len(pts)),
        "grid_shape": list(grid_shape),
        "regular_grid": regular_grid,
        "interpolated": bool(interpolation),
        "interpolation": interpolation,
        "source": source,
        "crs": normalized_crs,
        "coordinate_columns": {"x": x_col, "y": y_col},
        "coordinate_system": "geographic" if geographic else "projected_or_local",
        "horizontal_units": "degrees" if geographic else comments.get("xy_units", "meters"),
        "vertical_units": z_unit,
        "vertical_convention": vertical_convention,
        "vertical_datum": comments.get("vertical_datum"),
        "bounds": bounds,
        "centroid": {
            "x": float(np.mean(pts[:, 0])),
            "y": float(np.mean(pts[:, 1])),
        },
    }
    if comments:
        metadata["source_metadata"] = comments
    return metadata


def _interpolate_idw(pts: np.ndarray, side: int) -> tuple[np.ndarray, np.ndarray, np.ndarray, dict]:
    xs = np.linspace(float(np.min(pts[:, 0])), float(np.max(pts[:, 0])), side)
    ys = np.linspace(float(np.min(pts[:, 1])), float(np.max(pts[:, 1])), side)
    x_grid, y_grid = np.meshgrid(xs, ys)
    targets = np.column_stack([x_grid.ravel(), y_grid.ravel()])
    z_values = np.empty(len(targets), dtype=float)
    power = 2.0
    chunk_size = 1024
    for start in range(0, len(targets), chunk_size):
        chunk = targets[start:start + chunk_size]
        dx = chunk[:, None, 0] - pts[None, :, 0]
        dy = chunk[:, None, 1] - pts[None, :, 1]
        dist2 = dx * dx + dy * dy
        exact = dist2 == 0
        weights = 1.0 / np.maximum(dist2, 1e-12) ** (power / 2.0)
        values = weights @ pts[:, 2] / np.sum(weights, axis=1)
        if exact.any():
            rows, cols = np.where(exact)
            for row in np.unique(rows):
                values[row] = pts[cols[rows == row][0], 2]
        z_values[start:start + len(chunk)] = values
    return x_grid, y_grid, z_values.reshape(side, side), {"method": "idw", "power": power, "grid_size": side}


def parse_xyz_csv(data: bytes, source: str = "uploaded csv") -> BathymetryGrid:
    text = data.decode("utf-8-sig")
    comments = _comment_metadata(text.splitlines())
    clean_text = _clean_data_text(text)
    rows = [row for row in csv.reader(io.StringIO(clean_text)) if row]
    if not rows:
        raise ValueError("Bathymetry CSV is missing a header row")

    points: list[tuple[float, float, float]] = []
    header = [cell.strip().lower() for cell in rows[0]]
    header_names = {"x", "lon", "lng", "longitude", "easting", "y", "lat", "latitude", "northing", *DEPTH_NAMES, *ELEVATION_NAMES}
    coordinate_columns = ("x", "y")
    vertical_convention = "elevation_positive_up"
    z_unit = comments.get("z_units") or comments.get("vertical_units") or comments.get("units")
    if set(header) & header_names:
        reader = csv.DictReader(io.StringIO(clean_text))
        for raw_row in reader:
            row = {str(k).strip().lower(): v for k, v in raw_row.items() if k is not None}
            x_name = next((name for name in ("x", "lon", "lng", "longitude", "easting") if name in row and row[name] not in (None, "")), "x")
            y_name = next((name for name in ("y", "lat", "latitude", "northing") if name in row and row[name] not in (None, "")), "y")
            depth_name = next((name for name in DEPTH_NAMES if name in row and row[name] not in (None, "")), None)
            elevation_name = next((name for name in ELEVATION_NAMES if name in row and row[name] not in (None, "")), None)
            z_name = depth_name or elevation_name or "z"
            x = _numeric(row, (x_name,))
            y = _numeric(row, (y_name,))
            z = _numeric(row, (z_name,))
            if x is None or y is None or z is None:
                continue
            coordinate_columns = (x_name, y_name)
            if depth_name:
                vertical_convention = "depth_positive_down_normalized_to_elevation"
                z = -abs(z)
            z_factor, z_unit = _unit_factor(_header_unit(z_name, z_unit))
            z *= z_factor
            points.append((x, y, z))
    else:
        z_factor, z_unit = _unit_factor(z_unit)
        for line in text.splitlines():
            if line.strip().startswith("#"):
                continue
            values = [part for part in line.replace(",", " ").split() if part]
            if len(values) < 3:
                continue
            points.append((float(values[0]), float(values[1]), float(values[2]) * z_factor))

    if len(points) < 4:
        raise ValueError("Bathymetry CSV must contain at least four x/y/z rows")

    return grid_from_points(
        points,
        source=source,
        comments=comments,
        coordinate_columns=coordinate_columns,
        vertical_convention=vertical_convention,
        z_unit=z_unit or "meters",
    )


def grid_from_points(
    points: Iterable[tuple[float, float, float]],
    source: str = "points",
    comments: dict | None = None,
    coordinate_columns: tuple[str, str] = ("x", "y"),
    vertical_convention: str = "elevation_positive_up",
    z_unit: str = "meters",
    interpolation_grid_size: int | None = None,
) -> BathymetryGrid:
    pts = np.array(list(points), dtype=float)
    if pts.ndim != 2 or pts.shape[1] != 3:
        raise ValueError("Bathymetry points must be an iterable of x/y/z triples")

    if not np.isfinite(pts).all():
        raise ValueError("Bathymetry coordinates must be finite")
    xs = np.unique(pts[:, 0])
    ys = np.unique(pts[:, 1])
    if len(xs) * len(ys) == len(pts) and not (comments or {}).get("support_radius_m"):
        x_grid, y_grid = np.meshgrid(xs, ys)
        z_grid = np.full_like(x_grid, np.nan, dtype=float)
        x_index = {v: i for i, v in enumerate(xs)}
        y_index = {v: i for i, v in enumerate(ys)}
        for x, y, z in pts:
            z_grid[y_index[y], x_index[x]] = z
        if np.isnan(z_grid).any():
            raise ValueError("Bathymetry grid contains missing cells")
        return BathymetryGrid(
            x=x_grid,
            y=y_grid,
            z=z_grid,
            source=source,
            metadata=_metadata_for_points(
                pts,
                source,
                True,
                z_grid.shape,
                comments=comments,
                coordinate_columns=coordinate_columns,
                vertical_convention=vertical_convention,
                z_unit=z_unit,
            ),
        )

    side = interpolation_grid_size or min(128, max(2, int(np.sqrt(len(pts)))))
    if (comments or {}).get("support_radius_m"):
        side = min(128, max(side, int(np.ceil(max(np.ptp(pts[:, 0]), np.ptp(pts[:, 1])))) + 1))
    x_grid, y_grid, z_grid, interpolation = _interpolate_idw(pts, side)
    metadata = _metadata_for_points(
        pts, source, False, z_grid.shape, comments=comments, interpolation=interpolation,
        coordinate_columns=coordinate_columns, vertical_convention=vertical_convention, z_unit=z_unit,
    )
    if comments and "support_radius_m" in comments:
        radius = float(comments["support_radius_m"])
        if not np.isfinite(radius) or radius <= 0 or radius > 20:
            raise ValueError("support_radius_m must be between 0 and 20 metres")
        targets = np.column_stack([x_grid.ravel(), y_grid.ravel()])
        supported = np.zeros(len(targets), dtype=bool)
        for start in range(0, len(targets), 256):
            distances = np.sum((targets[start:start+256, None, :] - pts[None, :, :2])**2, axis=2)
            supported[start:start+256] = np.min(distances, axis=1) <= radius**2
        metadata["support_mask"] = supported.reshape(z_grid.shape).tolist()
        metadata["support_radius_m"] = radius
        metadata["supported_fraction"] = float(supported.mean())
        metadata["metrics_note"] = "Legacy grid metrics include interpolation; not valid as measured-coverage metrics."
    return BathymetryGrid(
        x=x_grid,
        y=y_grid,
        z=z_grid,
        source=source,
        metadata=metadata,
    )


def load_bathymetry_grid(raw_dataset, object_store) -> BathymetryGrid | None:
    candidates = [
        asset
        for asset in getattr(raw_dataset, "assets", []) or []
        if (getattr(asset, "asset_type", "") or "").lower() == "bathymetry"
        or (getattr(asset, "file_name", "") or "").lower().endswith((".xyz", ".csv"))
    ]
    errors: list[str] = []
    for asset in candidates:
        try:
            data = object_store.get_bytes(asset.object_key)
            return parse_xyz_csv(data, source=asset.file_name)
        except Exception as exc:
            errors.append(f"{getattr(asset, 'file_name', 'asset')}: {exc}")
    if errors:
        raise ValueError("Could not parse bathymetry assets: " + "; ".join(errors))
    return None
