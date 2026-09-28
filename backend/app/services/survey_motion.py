"""One-second attitude statistics, retaining within-second rocking variance."""
import gzip
import io
import json
import math
from datetime import datetime
from app.services.survey_replay import packets, recording_stream


def extract_motion(data, started_at):
    warnings = []
    return motion_from_packets(packets(recording_stream(data), warnings), started_at, warnings)


class MotionAccumulator:
    def __init__(self):
        self.epoch = self.anchor = self.previous_boot = None
        self.bins = {}
        self.start = None
        self.pending = []

    def session(self, config):
        if self.epoch is None:
            self.epoch = datetime.fromisoformat(config["timestamp"].replace("Z", "+00:00")).timestamp()

    def set_start(self, stamp):
        self.start = stamp
        for stamp, roll, pitch in self.pending: self.add(stamp, roll, pitch)
        self.pending.clear()

    def add(self, stamp, roll, pitch):
        t = stamp-self.start
        if not 0 <= t <= 86400: return
        end = math.floor(t)+1
        row = self.bins.setdefault(end, {"t":end,"n":0,"roll_mean":0.,"pitch_mean":0.,"roll_m2":0.,"pitch_m2":0.})
        row["n"] += 1
        for key,value in (("roll",math.degrees(roll)),("pitch",math.degrees(pitch))):
            delta = value-row[key+"_mean"]
            row[key+"_mean"] += delta/row["n"]
            row[key+"_m2"] += delta*(value-row[key+"_mean"])
            row[key] = value

    def message(self, message):
        if self.epoch is None or message.get("type") not in ("ATTITUDE", "GLOBAL_POSITION_INT"): return
        boot = message.get("time_boot_ms")
        if not isinstance(boot, (float, int)): return
        if self.anchor is None: self.anchor = boot
        if message["type"] != "ATTITUDE": return
        roll, pitch = message.get("roll"), message.get("pitch")
        if not all(isinstance(v, (float, int)) and math.isfinite(v) for v in (roll,pitch)): return
        if self.previous_boot is not None and boot <= self.previous_boot: return
        self.previous_boot = boot
        stamp = self.epoch + (boot-self.anchor)/1000
        if self.start is None: self.pending.append((stamp, roll, pitch))
        else: self.add(stamp, roll, pitch)

    def result(self, started_at, warnings):
        if self.start is None: self.set_start(datetime.fromisoformat(started_at.replace("Z", "+00:00")).timestamp())
        samples = []
        for stamp, row in sorted(self.bins.items()):
            samples.append({**{k:round(v,6) if isinstance(v,float) else v for k,v in row.items()}, "t":stamp})
        return {"samples":samples,"warnings":warnings,"units":"degrees","source":"Recorded vehicle ATTITUDE","window_seconds":30}


def motion_from_packets(packet_iter, started_at, warnings):
    accumulator = MotionAccumulator()
    accumulator.set_start(datetime.fromisoformat(started_at.replace("Z", "+00:00")).timestamp())
    for kind, payload in packet_iter:
        if kind == 10:
            if accumulator.epoch is not None: break
            accumulator.session(json.loads(payload))
        elif kind == 150: accumulator.message(json.loads(payload).get("message", {}))
    return accumulator.result(started_at, warnings)
