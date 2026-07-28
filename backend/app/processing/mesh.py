import numpy as np
import trimesh

from app.processing.photogrammetry import PointCloud


def _grid_faces(rows: int, cols: int) -> np.ndarray:
    faces: list[list[int]] = []
    for row in range(rows - 1):
        for col in range(cols - 1):
            a = row * cols + col
            b = a + 1
            c = a + cols
            d = c + 1
            faces.append([a, c, b])
            faces.append([b, c, d])
    return np.array(faces, dtype=np.int64)


def build_surface_mesh(point_cloud: PointCloud) -> trimesh.Trimesh:
    if point_cloud.x.shape != point_cloud.y.shape or point_cloud.x.shape != point_cloud.z.shape:
        raise ValueError("Point cloud x, y and z arrays must share the same grid shape")
    if point_cloud.z.ndim != 2 or min(point_cloud.z.shape) < 2:
        raise ValueError("Point cloud must be a two-dimensional grid with at least 2 rows and columns")

    vertices = np.column_stack(
        [point_cloud.x.ravel(), point_cloud.y.ravel(), point_cloud.z.ravel()]
    )
    faces = _grid_faces(*point_cloud.z.shape)
    mesh = trimesh.Trimesh(vertices=vertices, faces=faces, process=False)
    mesh.metadata.update({"source": point_cloud.source, "geometry": point_cloud.metadata})
    return mesh


def _export_mesh(point_cloud: PointCloud, file_type: str) -> bytes:
    mesh = build_surface_mesh(point_cloud)
    data = mesh.export(file_type=file_type)
    if isinstance(data, str):
        return data.encode("utf-8")
    return bytes(data)


def export_mesh_glb(point_cloud: PointCloud) -> bytes:
    return _export_mesh(point_cloud, "glb")


def export_mesh_ply(point_cloud: PointCloud) -> bytes:
    return _export_mesh(point_cloud, "ply")


def export_mesh_obj(point_cloud: PointCloud) -> bytes:
    return _export_mesh(point_cloud, "obj")


def texture_mapping_metadata(point_cloud: PointCloud, texture_file: str) -> dict:
    x_min = float(np.min(point_cloud.x))
    x_max = float(np.max(point_cloud.x))
    y_min = float(np.min(point_cloud.y))
    y_max = float(np.max(point_cloud.y))
    return {
        "texture_file": texture_file,
        "mapping": "planar_xy_normalized_uv",
        "uv_origin": "lower_left",
        "u_axis": "x",
        "v_axis": "y",
        "bounds": {
            "min_x": x_min,
            "max_x": x_max,
            "min_y": y_min,
            "max_y": y_max,
        },
        "source": point_cloud.source,
        "geometry_metadata": point_cloud.metadata,
    }
