"""SonarView decoding, using Cerulean's published Omniscan3D packet definitions.

WGS84 navigation -> UTM metres; sonar FSD -> NED -> ENU.
Geometry is provisional, with vehicle-origin depths, not tide-corrected MSL.
"""
import gzip
import io
import json
import math
import struct
import zlib
from collections import Counter
from datetime import datetime, timezone

from pyproj import Transformer, Geod

from app.core.config import settings

MAX_DECOMPRESSED = settings.survey_decompressed_limit_mb * 1024 * 1024
MAX_POINTS = 500_000
COORDINATE_VERSION = 2
GEODESIC = Geod(ellps="WGS84")


def project_offsets(projection, longitude, latitude, north, east):
    """True N/E metres to projected coordinates, including grid convergence/scale."""
    import numpy as np
    north, east = np.asarray(north), np.asarray(east)
    lon, lat, _ = GEODESIC.fwd(np.full(north.shape, longitude), np.full(north.shape, latitude),
                              np.degrees(np.arctan2(east, north)), np.hypot(north, east))
    return projection.transform(lon, lat)


def packets(source, warnings):
    total = 0
    while True:
        try:
            header = source.read(8)
            if not header:
                return
            if len(header) != 8 or header[:2] != b"BR":
                warnings.append("Incomplete or invalid packet header; recovered the valid prefix.")
                return
            length, kind, sender, receiver = struct.unpack("<HHBB", header[2:])
            total += length + 10
            if total > MAX_DECOMPRESSED:
                warnings.append("Decompressed size limit reached; replay contains only the valid prefix.")
                return
            payload = source.read(length)
            checksum = source.read(2)
            if len(payload) != length or len(checksum) != 2:
                warnings.append("Truncated packet; recovered the valid prefix.")
                return
            if (sum(header) + sum(payload)) & 0xffff != int.from_bytes(checksum, "little"):
                warnings.append("Packet checksum mismatch; recovered the valid prefix.")
                return
            yield kind, payload
        except (OSError, EOFError, zlib.error):
            warnings.append("Damaged or incomplete compressed recording; recovered the valid prefix.")
            return


def rotate(vector, roll, pitch, yaw):
    """Intrinsic forward/starboard/down roll/pitch/yaw -> north/east/down."""
    x, y, z = vector
    cr, sr, cp, sp, cy, sy = math.cos(roll), math.sin(roll), math.cos(pitch), math.sin(pitch), math.cos(yaw), math.sin(yaw)
    y, z = cr*y-sr*z, sr*y+cr*z
    x, z = cp*x+sp*z, -sp*x+cp*z
    return cy*x-sy*y, sy*x+cy*y, z


def recording_stream(data):
    """Read bytes or a streaming file without materializing the whole recording."""
    source=io.BytesIO(data) if isinstance(data,(bytes,bytearray)) else data
    prefix=source.read(2)
    class PrefixedReader:
        def __init__(self):self.prefix=prefix
        def read(self,size=-1):
            if size<0:
                first=self.prefix;self.prefix=b'';return first+source.read()
            first=self.prefix[:size];self.prefix=self.prefix[size:]
            return first+source.read(size-len(first))
    stream=PrefixedReader()
    return gzip.GzipFile(fileobj=stream) if prefix==b'\x1f\x8b' else stream


def decode_sonar(data, filename: str, progress=None) -> dict:
    return _decode_recording(data, filename, progress=progress)


def decode_detections(data, filename: str, sink, progress=None, detailed_sink=None) -> dict:
    """Stream each valid XYZ detection to sink; no bins, preview cap or motion history."""
    return _decode_recording(data, filename, progress=progress, detection_sink=sink, detailed_sink=detailed_sink)


def _decode_recording(data, filename: str, progress=None, detection_sink=None, detailed_sink=None) -> dict:
    warnings, frames, counts = [], {}, Counter()
    source = io.BytesIO(data) if isinstance(data, (bytes, bytearray)) else data
    class CountedReader:
        def read(self, size=-1):
            value = source.read(size)
            if progress: progress(len(value))
            return value
    stream = recording_stream(CountedReader())
    from app.services.survey_motion import MotionAccumulator
    motion_accumulator = MotionAccumulator() if detection_sink is None else None
    session, nav, attitude, projection, inverse = {}, None, None, None, None
    epoch, boot_anchor, start, epsg = None, None, None, None
    pending = {}
    retained = 0
    skipped = Counter()

    def frame_at(stamp):
        nonlocal start
        if start is None:
            start = stamp
            if motion_accumulator: motion_accumulator.set_start(stamp)
        second = max(0, int(stamp - start))
        if detection_sink is not None:
            return {"t": second, "boat": None}
        if second > 86400:
            raise ValueError("Recording exceeds one day or has inconsistent clocks")
        return frames.setdefault(second, {"t": second, "boat": None, "bins": {}})

    try:
        for kind, payload in packets(stream, warnings):
            counts[kind] += 1
            if kind in (3104, 3010) and len(payload) < 80:
                skipped["unsupported_point_packet"] += 1
                continue
            if kind == 10:
                config = json.loads(payload)
                if session:
                    warnings.append("Additional session encountered; replay stops at the session boundary.")
                    break
                session = config
                if motion_accumulator: motion_accumulator.session(config)
                epoch = datetime.fromisoformat(session["timestamp"].replace("Z", "+00:00")).timestamp()
            elif kind == 150:
                msg = json.loads(payload).get("message", {})
                if motion_accumulator: motion_accumulator.message(msg)
                if msg.get("type") not in {"GLOBAL_POSITION_INT", "ATTITUDE"} or epoch is None:
                    continue
                boot = msg.get("time_boot_ms")
                if boot is None:
                    continue
                if boot_anchor is None:
                    boot_anchor = boot
                stamp = epoch + (boot - boot_anchor) / 1000
                if msg["type"] == "ATTITUDE":
                    values = [msg.get(k, 0) for k in ("roll", "pitch", "yaw")]
                    if all(math.isfinite(v) for v in values):
                        attitude = (stamp, *values)
                else:
                    lat, lon = msg["lat"] / 1e7, msg["lon"] / 1e7
                    if not (-80 <= lat <= 84 and -180 <= lon <= 180) or (lat == 0 and lon == 0):
                        skipped["invalid_position"] += 1
                        continue
                    if projection is None:
                        epsg = (32600 if lat >= 0 else 32700) + min(60, int((lon + 180) // 6) + 1)
                        projection = Transformer.from_crs(4326, epsg, always_xy=True)
                        inverse = Transformer.from_crs(epsg, 4326, always_xy=True)
                    x, y = projection.transform(lon, lat)
                    heading = msg.get("hdg", 65535)
                    heading = heading / 100 if heading != 65535 else (math.degrees(attitude[3]) % 360 if attitude else 0)
                    alt=msg.get("alt")
                    alt_m=alt/1000 if isinstance(alt,(int,float)) and not isinstance(alt,bool) and math.isfinite(alt) else None
                    nav = (stamp, x, y, lon, lat, heading, alt_m)
                    frame_at(stamp)["boat"] = [round(lon, 7), round(lat, 7), round(heading, 1), round(x, 3), round(y, 3)]
            elif kind == 3104 and len(payload) >= 80:
                ping, sos, n = struct.unpack_from("<IfH", payload)
                utc = struct.unpack_from("<Q", payload, 16)[0] / 1000
                version, device = payload[28:30]
                if version != 1 or len(payload) != 80 + n * 16:
                    skipped["unsupported_point_packet"] += 1
                    continue
                if (device, ping) in pending:
                    skipped["unmatched_point_packet"] += 1
                pending[(device, ping)] = (payload, sos, n, utc, nav, attitude)
                if len(pending) > 16:
                    pending.pop(next(iter(pending)))
                    skipped["unmatched_point_packet"] += 1
            elif kind == 3010 and len(payload) >= 80:
                ping = struct.unpack_from("<I", payload, 24)[0]
                device = payload[66]
                item = pending.pop((device, ping), None)
                if not item:
                    continue
                point_data, sos, n, stamp, position, pose = item
                if not position or not pose or stamp <= 0 or abs(stamp-position[0]) > 2 or abs(stamp-pose[0]) > 2:
                    skipped["missing_or_stale_navigation"] += 1
                    continue
                sonar = next((d for d in session.get("session_devices", []) if d.get("product_id") == "os3d45016"), {})
                options = sonar.get("options", {})
                components = options.get("components", [])
                if device >= len(components):
                    skipped["missing_mount"] += 1
                    continue
                mount = components[device].get("mount_fsd", {})
                up = struct.unpack_from("<fff", payload, 12)
                if not all(math.isfinite(v) for v in up) or not 0.8 < sum(v*v for v in up) < 1.2:
                    skipped["invalid_sensor_attitude"] += 1
                    continue
                # The sensor IMU includes mounting tilt: do not apply mounting roll twice.
                # Published pitch is FPU (forward/port/up); negate it for FSD.
                roll, pitch = math.atan2(up[1], up[2]), math.asin(max(-1, min(1, up[0])))
                # SonarView mount yaw is referenced to the RX array axis, a quarter
                # turn from the forward axis used by this FSD beam/IMU rotation.
                # Apply that frame conversion before heading, never to world XY.
                yaw = pose[3] + math.radians(mount.get("yaw_deg", 0) + options.get("mount_yaw_deg", 0)) - math.pi/2
                offset = rotate([mount.get("x_mm", 0)/1000 + options.get("mount_x", 0),
                                 mount.get("y_mm", 0)/1000 + options.get("mount_y", 0),
                                 mount.get("z_mm", 0)/1000 + options.get("mount_z", 0)], *pose[1:])
                threshold = struct.unpack_from("<f", point_data, 36)[0]
                if not math.isfinite(sos) or not 1300 <= sos <= 1700 or not math.isfinite(threshold):
                    skipped["invalid_sonar_parameters"] += 1
                    continue
                frame = frame_at(stamp)
                cr, sr, cp, sp, cy, sy = math.cos(roll), math.sin(roll), math.cos(pitch), math.sin(pitch), math.cos(yaw), math.sin(yaw)
                detections = []
                for angle, tof, power, classification in struct.iter_unpack("<fffB3x", point_data[80:]):
                    if not all(math.isfinite(v) for v in (angle, tof, power)):
                        skipped["nonfinite_detection"] += 1
                        continue
                    if power < threshold:
                        skipped["below_medium_power"] += 1
                        continue
                    if classification == 2:
                        skipped["water_column_detection"] += 1
                        continue
                    distance = tof * sos / 2
                    if not 0.2 <= distance <= 500:
                        skipped["out_of_range_detection"] += 1
                        continue
                    beam_y, beam_z = math.sin(angle)*distance, math.cos(angle)*distance
                    ry, rz = cr*beam_y-sr*beam_z, sr*beam_y+cr*beam_z
                    rx, down = sp*rz, cp*rz
                    north, east = cy*rx-sy*ry, sy*rx+cy*ry
                    z = -down-offset[2]
                    if not all(math.isfinite(v) for v in (north, east, z)):
                        skipped["invalid_geometry"] += 1
                        continue
                    if z >= 0:
                        skipped["nonnegative_depth"] += 1
                        continue
                    detections.append((north+offset[0], east+offset[1], z, down))
                if not detections:
                    continue
                xs, ys = project_offsets(projection, position[3], position[4],
                                         [d[0] for d in detections], [d[1] for d in detections])
                for x, y, (_, _, z, down) in zip(xs, ys, detections):
                    if detection_sink is not None:
                        detection_sink(x, y, z)
                        if detailed_sink is not None:
                            detailed_sink(x, y, z, down, position[6], frame["t"])
                        retained += 1
                        continue
                    key = (math.floor(x), math.floor(y))
                    if key not in frame["bins"]:
                        if retained >= MAX_POINTS:
                            continue
                        retained += 1
                        frame["bins"][key] = [x, y, z, 1, 0., 0, None, None, 0.]
                    else:
                        cell = frame["bins"][key]
                        cell[0] += x; cell[1] += y; cell[2] += z; cell[3] += 1
                    cell=frame["bins"][key]
                    cell[8]+=down
                    if position[6] is not None:
                        alt=position[6];cell[4]+=alt;cell[5]+=1
                        cell[6]=alt if cell[6] is None else min(cell[6],alt)
                        cell[7]=alt if cell[7] is None else max(cell[7],alt)
    except (ValueError, KeyError, TypeError, AttributeError, OverflowError, struct.error) as exc:
        if detection_sink is None:
            raise
        warnings.append(f"Malformed recording contents; recovered the valid prefix ({type(exc).__name__}).")
    if detection_sink is not None:
        if pending:
            skipped["unmatched_point_packet"] += len(pending)
        for reason in ("unsupported_point_packet", "unmatched_point_packet", "missing_mount"):
            if skipped[reason]:
                warnings.append(f"{skipped[reason]} packets omitted: {reason}.")
        if projection is None:
            raise ValueError("No valid WGS84 BlueBoat navigation found in this recording")
        return {"coordinate_version": COORDINATE_VERSION, "crs": f"EPSG:{epsg}", "point_count": retained, "partial": bool(warnings),
                "warnings": warnings, "skipped": dict(skipped),
                "started_at": datetime.fromtimestamp(start, timezone.utc).isoformat() if start is not None else None,
                "vertical_datum": "vehicle_origin_uncorrected"}
    if projection is None or not frames:
        raise ValueError("No valid WGS84 BlueBoat navigation found in this recording")
    if retained >= MAX_POINTS:
        warnings.append("Replay point limit reached. Later navigation remains available; some soundings were omitted.")
    warnings.extend([
        "Provisional sonar geometry: verify mounting and heading against SonarView before scientific use.",
        "Depths are relative to the vehicle origin; no draft, tide or MSL correction is applied.",
        "Navigation UTC is anchored to the session timestamp and first vehicle boot timestamp.",
    ])
    output = []
    for second in sorted(frames):
        f = frames[second]
        points = []
        vertical=[];soundings=[]
        values = list(f.pop("bins").values())
        lons, lats = inverse.transform([v[0]/v[3] for v in values], [v[1]/v[3] for v in values])
        for (sx, sy, sz, count, alt_sum, alt_count, alt_min, alt_max, depth_sum), lon, lat in zip(values, lons, lats):
            x, y, z = sx/count, sy/count, sz/count
            soundings.append([round(x,3),round(y,3),round(z,3),depth_sum/count,count])
            if alt_count:vertical.append([round(x,3),round(y,3),alt_sum,alt_count,alt_min,alt_max])
            points.append([round(x, 3), round(y, 3), round(z, 3), round(lon, 7), round(lat, 7), count])
        f["sounding_altitudes"] = soundings
        f["vertical_samples"] = vertical
        f["points"] = points
        output.append(f)
    if not retained:
        warnings.append("No supported, synchronized sonar detections recovered; navigation-only playback.")
    motion = motion_accumulator.result(datetime.fromtimestamp(start, timezone.utc).isoformat(), list(warnings))
    return {"decoder_version": 1, "coordinate_version": COORDINATE_VERSION, "motion_summary": motion, "name": filename, "started_at": datetime.fromtimestamp(start, timezone.utc).isoformat(),
            "duration": output[-1]["t"], "crs": f"EPSG:{epsg}", "frames": output,
            "point_count": retained, "warnings": warnings, "packet_counts": dict(counts),
            "vertical_reference_version":2, "skipped": dict(skipped), "vertical_datum": "vehicle_origin_uncorrected",
            "reduction": "power-filtered means in 1 m cells per replay second"}


def block_snapshot(replay, column, row, size, until):
    """Only samples at or before the cursor can enter an exported block."""
    bins = {}
    for frame in replay["frames"]:
        if frame["t"] > until:
            break
        for x, y, z, lon, lat, count in frame["points"]:
            if math.floor(x / size) != column or math.floor(y / size) != row:
                continue
            value = bins.setdefault((math.floor(x), math.floor(y)), [0., 0., 0., 0])
            for i, v in enumerate((x, y, z)):
                value[i] += v * count
            value[3] += count
    return [[round(v[0]/v[3]-column*size, 3), round(v[1]/v[3]-row*size, 3), round(v[2]/v[3], 3)] for v in bins.values()]
