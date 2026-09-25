import gzip
import io
import json
import math
import struct
from types import SimpleNamespace

import numpy as np
import pytest

from app.services.survey_replay import block_snapshot, decode_sonar, packets, rotate
from app.processing.bathymetry import parse_xyz_csv
from app.processing.mesh import build_surface_mesh
from app.processing.photogrammetry import reconstruct_point_cloud, point_cloud_to_xyz_csv


def packet(kind, payload):
    if isinstance(payload, dict):
        payload = json.dumps(payload).encode()
    header = b"BR" + struct.pack("<HHBB", len(payload), kind, 1, 0)
    return header + payload + struct.pack("<H", (sum(header)+sum(payload)) & 0xffff)


def recording(version=1, nav_age=0, altitude=None, angle=0, mount_z=0):
    config = {"timestamp": "2026-07-10T20:00:00Z", "session_devices": [
        {"product_id": "os3d45016", "options": {"components": [{"mount_fsd": {"z_mm":mount_z*1000}}]}}]}
    raw = packet(10, config)
    raw += packet(150, {"message": {"type": "ATTITUDE", "time_boot_ms": 1000, "roll": 0, "pitch": 0, "yaw": 0}})
    raw += packet(150, {"message": {"type": "GLOBAL_POSITION_INT", "time_boot_ms": 1000, "lat": 201800000, "lon": -1559000000, "hdg": 9000, "alt":altitude, "relative_alt":987650}})
    point = bytearray(80)
    struct.pack_into("<IfH", point, 0, 1, 1500., 1)
    struct.pack_into("<Q", point, 16, 1783713600000 + nav_age*1000)
    point[28] = version
    struct.pack_into("<f", point, 36, 10.)
    point.extend(struct.pack("<fffB3x", angle, 0.02, 20., 1))
    raw += packet(3104, point)
    end = bytearray(80)
    struct.pack_into("<fff", end, 12, 0., 0., 1.)
    struct.pack_into("<I", end, 24, 1)
    raw += packet(3010, end)
    return raw


def test_real_packet_geometry_and_utm_position():
    replay = decode_sonar(gzip.compress(recording()), "test.svlz")
    assert replay["crs"] == "EPSG:32605"
    assert replay["point_count"] == 1
    point = replay["frames"][0]["points"][0]
    assert point[2] == pytest.approx(-15, abs=.001)
    assert point[3:5] == pytest.approx([-155.9, 20.18], abs=1e-6)
    assert replay["vertical_datum"] == "vehicle_origin_uncorrected"


def test_checksum_damage_stops_before_untrusted_packet():
    data = recording() + packet(14, b"abc")[:-1] + b"\xff"
    warnings = []
    result = list(packets(io.BytesIO(data), warnings))
    assert len(result) == 5
    assert "checksum" in warnings[0]


def test_truncated_gzip_recovers_navigation_and_warns():
    compressed = gzip.compress(recording())[:-5]
    replay = decode_sonar(compressed, "partial.svlz")
    assert replay["frames"][0]["boat"]
    assert any("compressed" in w for w in replay["warnings"])


@pytest.mark.parametrize("kwargs", [{"version": 0}, {"nav_age": 10}])
def test_unsupported_or_unsynchronized_points_are_not_fabricated(kwargs):
    replay = decode_sonar(recording(**kwargs), "test.svlog")
    assert replay["point_count"] == 0
    assert replay["frames"][0]["boat"]


def test_rotation_heading_ninety_degrees():
    assert rotate((10, 0, 0), 0, 0, math.pi/2) == pytest.approx((0, 10, 0))


def test_blocks_respect_boundaries_and_cursor_and_weighted_means():
    replay = {"frames": [{"t": 0, "points": [[49.5, 1, -2, 0, 0, 2], [50, 1, -9, 0, 0, 1], [-.1, 1, -3, 0, 0, 1]]},
                         {"t": 10, "points": [[49.5, 1, -8, 0, 0, 1]]}]}
    assert block_snapshot(replay, 0, 0, 50, 0) == [[49.5, 1, -2]]
    assert block_snapshot(replay, 0, 0, 50, 10) == [[49.5, 1, -4]]
    assert block_snapshot(replay, 1, 0, 50, 10) == [[0, 1, -9]]
    assert block_snapshot(replay, -1, 0, 50, 10) == [[49.9, 1, -3]]


def test_sparse_mesh_preserves_unsurveyed_gap_and_csv_mask():
    grid = parse_xyz_csv(b"# support_radius_m=2\nx,y,z\n0,0,-2\n0,10,-2\n10,0,-2\n10,10,-2\n")
    assert grid.metadata["support_mask"][5][5] is False
    cloud = reconstruct_point_cloud(SimpleNamespace(assets=[]), grid)
    mesh = build_surface_mesh(cloud)
    assert len(mesh.faces) > 0
    assert not np.any(np.all((mesh.triangles_center[:, :2] > 3) & (mesh.triangles_center[:, :2] < 7), axis=1))
    csv = point_cloud_to_xyz_csv(cloud)
    assert b"x,y,z,supported" in csv
    assert b",0\r\n" in csv


def test_recorded_msl_uses_navigation_altitude_not_home_relative_height():
    from app.services.sea_levels import block_reference
    replay=decode_sonar(recording(altitude=12340),'test.svlog')
    point=replay['frames'][0]['points'][0]
    ref=block_reference(replay,math.floor(point[0]/50),math.floor(point[1]/50),50,0)
    assert ref['vehicle_altitude_msl_m']==pytest.approx(12.34)
    assert ref['msl_z_m'] is None
    assert ref['sea_surface_z_m'] is None
    assert ref['coverage']==1
    assert point[2]==-15  # Preserve vehicle-relative geometry.


def test_references_follow_tile_cursor_and_sounding_weights():
    from app.services.sea_levels import block_reference,summarize_references
    replay={'frames':[
        {'t':0,'points':[[1,1,-10,0,0,2]],'vertical_samples':[[1,1,20,2,10,10],[51,1,999,1,999,999]]},
        {'t':10,'points':[[1,1,-10,0,0,1]],'vertical_samples':[[1,1,16,1,16,16]]}]}
    first=block_reference(replay,0,0,50,0)
    assert first['vehicle_altitude_msl_m']==10
    complete=block_reference(replay,0,0,50,10)
    assert complete['vehicle_altitude_msl_m']==12
    assert complete['vehicle_altitude_msl_range_m']==[10,16]
    combined=summarize_references([first,complete],5)
    assert combined['vehicle_altitude_msl_m']==pytest.approx(11.2)
    assert block_reference({'frames':[{'t':0,'points':[[1,1,-10,0,0,1]]}]},0,0,50,0) is None


def test_sounding_altitude_is_vertical_not_slant_range_or_gps_height():
    from app.services.sea_levels import sounding_reference
    replay=decode_sonar(recording(altitude=999000,angle=math.pi/3,mount_z=.2),'test.svlog')
    p=replay['frames'][0]['points'][0]
    ref=sounding_reference(replay,math.floor(p[0]/50),math.floor(p[1]/50),50,0)
    x,y,z,alt=ref['points'][0]
    assert alt==pytest.approx(7.5,abs=.001)  # 15 m slant range at 60 degrees.
    assert z==pytest.approx(-7.7,abs=.001)
    assert z+alt==pytest.approx(-.2,abs=.001)
    assert z+alt+.2==pytest.approx(0,abs=.001)  # Known 20 cm sonar-to-waterline offset.
    assert ref['msl_offset_m'] is None


def test_sounding_reference_averages_measurements_and_respects_cursor():
    from app.services.sea_levels import sounding_reference
    replay={'frames':[{'t':0,'sounding_altitudes':[[1,1,-20,18,2],[51,1,-90,20,1]]},
                      {'t':10,'sounding_altitudes':[[1,1,-23,21,1]]}]}
    assert sounding_reference(replay,0,0,50,0)['points']==[[1,1,-20,18]]
    assert sounding_reference(replay,0,0,50,10)['points']==[[1,1,-21,19]]
