from types import SimpleNamespace

from app.processing.bathymetry import parse_xyz_csv
from app.processing.mesh import export_mesh_glb, export_mesh_obj, export_mesh_ply, texture_mapping_metadata
from app.processing.photogrammetry import point_cloud_to_xyz_csv, reconstruct_point_cloud


def test_parse_xyz_csv_builds_regular_grid():
    grid = parse_xyz_csv(
        b"x,y,z\n0,0,-1\n1,0,-2\n0,1,-3\n1,1,-4\n",
        source="unit-test.csv",
    )

    assert grid.z.shape == (2, 2)
    assert grid.metadata["regular_grid"] is True
    assert grid.z[1, 1] == -4


def test_reconstruct_point_cloud_exports_xyz_csv():
    raw = SimpleNamespace(assets=[SimpleNamespace(asset_type="image", media_type="image/jpeg")])
    grid = parse_xyz_csv(b"x,y,z\n0,0,-1\n1,0,-2\n0,1,-3\n1,1,-4\n")
    point_cloud = reconstruct_point_cloud(raw, grid)
    csv_data = point_cloud_to_xyz_csv(point_cloud).decode("utf-8")

    assert point_cloud.metadata["image_asset_count"] == 1
    assert csv_data.startswith("x,y,z")
    assert "1.0,1.0,-4.0" in csv_data


def test_export_mesh_glb_returns_valid_glb_header():
    raw = SimpleNamespace(assets=[])
    grid = parse_xyz_csv(b"x,y,z\n0,0,-1\n1,0,-2\n0,1,-3\n1,1,-4\n")
    point_cloud = reconstruct_point_cloud(raw, grid)
    glb = export_mesh_glb(point_cloud)

    assert glb[:4] == b"glTF"


def test_parse_bathymetry_normalizes_depth_feet_and_crs_metadata():
    grid = parse_xyz_csv(
        b"# crs=EPSG:4326\nlongitude,latitude,depth_ft\n10,52,3.28084\n10.1,52,6.56168\n10,52.1,9.84252\n10.1,52.1,13.12336\n",
        source="geo-depth.csv",
    )

    assert grid.metadata["crs"] == "EPSG:4326"
    assert grid.metadata["coordinate_system"] == "geographic"
    assert grid.metadata["vertical_units"] == "meters"
    assert grid.metadata["vertical_convention"] == "depth_positive_down_normalized_to_elevation"
    assert round(float(grid.z[0, 0]), 3) == -1.0


def test_irregular_points_are_interpolated_to_grid():
    grid = parse_xyz_csv(
        b"x,y,z\n0,0,-1\n2,0,-2\n0,2,-3\n2,2,-4\n1,1,-2.5\n2,1,-3\n",
        source="irregular.csv",
    )

    assert grid.metadata["regular_grid"] is False
    assert grid.metadata["interpolated"] is True
    assert grid.metadata["interpolation"]["method"] == "idw"
    assert grid.z.shape == (2, 2)


def test_export_mesh_ply_obj_and_texture_mapping_metadata():
    raw = SimpleNamespace(assets=[])
    grid = parse_xyz_csv(b"x,y,z\n0,0,-1\n1,0,-2\n0,1,-3\n1,1,-4\n")
    point_cloud = reconstruct_point_cloud(raw, grid)

    assert export_mesh_ply(point_cloud).startswith(b"ply")
    assert b"v " in export_mesh_obj(point_cloud)
    metadata = texture_mapping_metadata(point_cloud, "coral_texture.jpg")
    assert metadata["mapping"] == "planar_xy_normalized_uv"
    assert metadata["texture_file"] == "coral_texture.jpg"
