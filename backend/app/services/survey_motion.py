"""One-second attitude statistics, retaining within-second rocking variance."""
import gzip
import io
import json
import math
from datetime import datetime
from app.services.survey_replay import packets


def extract_motion(data, started_at):
    stream = gzip.GzipFile(fileobj=io.BytesIO(data)) if data[:2] == b"\x1f\x8b" else io.BytesIO(data)
    start = datetime.fromisoformat(started_at.replace("Z", "+00:00")).timestamp()
    epoch = anchor = previous_boot = None
    bins, warnings = {}, []
    for kind, payload in packets(stream, warnings):
        if kind == 10:
            if epoch is not None: break
            epoch = datetime.fromisoformat(json.loads(payload)["timestamp"].replace("Z", "+00:00")).timestamp()
        elif kind == 150 and epoch is not None:
            message = json.loads(payload).get("message", {})
            if message.get("type") not in ("ATTITUDE", "GLOBAL_POSITION_INT"): continue
            boot = message.get("time_boot_ms")
            if not isinstance(boot, (float, int)): continue
            if anchor is None: anchor = boot
            if message["type"] != "ATTITUDE": continue
            roll, pitch = message.get("roll"), message.get("pitch")
            if not all(isinstance(v, (float, int)) and math.isfinite(v) for v in (roll,pitch)): continue
            if previous_boot is not None and boot <= previous_boot: continue
            previous_boot = boot
            t = epoch + (boot-anchor)/1000 - start
            if t < 0 or t > 86400: continue
            # Timestamp at the end of the bucket avoids showing future samples.
            end = math.floor(t)+1
            row = bins.setdefault(end, {"t":end,"n":0,"roll_mean":0.,"pitch_mean":0.,"roll_m2":0.,"pitch_m2":0.})
            row["n"] += 1
            for key,value in (("roll",math.degrees(roll)),("pitch",math.degrees(pitch))):
                delta = value-row[key+"_mean"]
                row[key+"_mean"] += delta/row["n"]
                row[key+"_m2"] += delta*(value-row[key+"_mean"])
                row[key] = value
    return {"samples":[{k:round(v,6) if isinstance(v,float) else v for k,v in row.items()} for _,row in sorted(bins.items())],
            "warnings":warnings,"units":"degrees","source":"Recorded vehicle ATTITUDE","window_seconds":30}
