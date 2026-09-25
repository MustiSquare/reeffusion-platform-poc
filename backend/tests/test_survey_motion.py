import json,struct,math
import pytest
from app.services.survey_motion import extract_motion

def packet(kind,body):
    payload=json.dumps(body).encode();header=b"BR"+struct.pack("<HHBB",len(payload),kind,1,0)
    return header+payload+struct.pack("<H",(sum(header)+sum(payload))&65535)

def test_motion_preserves_fast_variation_and_timestamps_at_bucket_end():
    data=packet(10,{"timestamp":"2026-07-10T20:00:00Z"})
    for boot,roll in [(1000,8),(1500,12),(1500,99),(2000,10)]:
        data+=packet(150,{"message":{"type":"ATTITUDE","time_boot_ms":boot,"roll":math.radians(roll),"pitch":0}})
    motion=extract_motion(data,"2026-07-10T20:00:00Z")
    first=motion["samples"][0]
    assert first["t"]==1 and first["n"]==2
    assert first["roll_mean"]==pytest.approx(10)
    assert first["roll_m2"]==pytest.approx(8)
    assert first["roll"]==pytest.approx(12)
    assert motion["samples"][1]["t"]==2

def test_absent_attitude_is_not_reported_as_calm():
    data=packet(10,{"timestamp":"2026-07-10T20:00:00Z"})
    assert extract_motion(data,"2026-07-10T20:00:00Z")["samples"]==[]
