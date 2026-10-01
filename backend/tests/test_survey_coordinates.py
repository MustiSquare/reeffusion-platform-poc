"""Independent SonarView coordinates, not decoder-against-decoder expectations."""
import json
import math
import struct
from pathlib import Path

import numpy as np
import pytest
from pyproj import Transformer
from app.services.survey_replay import decode_detections, project_offsets, COORDINATE_VERSION
from test_survey_replay import packet

REFERENCE = json.loads((Path(__file__).parent/'fixtures/sonarview_coordinates.json').read_text())


def reference_recording(d):
    config={'timestamp':'2026-07-10T20:00:00Z','session_devices':[{'product_id':'os3d45016','options':d['options']}]}
    raw=packet(10,config)
    for kind in ['ATTITUDE','GLOBAL_POSITION_INT']:
        raw+=packet(150,{'message':{**d[kind],'time_boot_ms':1000}})
    points=bytearray(80)
    struct.pack_into('<IfH',points,0,d['ping'],d['sos'],len(d['points']))
    struct.pack_into('<Q',points,16,1783713600000)
    points[28]=1;points[29]=d['device']
    struct.pack_into('<f',points,36,d['threshold'])
    for p in d['points']:points.extend(struct.pack('<fffB3x',*p))
    raw+=packet(3104,points)
    end=bytearray(80);struct.pack_into('<fff',end,12,*d['up']);struct.pack_into('<I',end,24,d['ping']);end[66]=d['device']
    return raw+packet(3010,end)


@pytest.mark.parametrize('reference',REFERENCE['pings'],ids=lambda p:f"ch{p['device']}-ping{p['ping']}")
def test_both_channels_match_independent_reference_across_headings(reference):
    points=[]
    result=decode_detections(reference_recording(reference),'fixture.svlog',lambda *p:points.append(p))
    assert result['coordinate_version']==COORDINATE_VERSION
    assert result['point_count']==len(reference['expected_xyz'])
    horizontal=np.linalg.norm(np.array(points)[:,:2]-np.array(reference['expected_xyz'])[:,:2],axis=1)
    assert np.quantile(horizontal,.95)<.1
    assert all(p[2]<0 for p in points)
    # Z intentionally retains the existing vehicle-relative lever-arm convention.
    roll=math.atan2(reference['up'][1],reference['up'][2]);pitch=math.asin(reference['up'][0])
    from app.services.survey_replay import rotate
    opts=reference['options'];mount=opts['components'][reference['device']]['mount_fsd'];pose=reference['ATTITUDE']
    offset=rotate([mount.get(k+'_mm',0)/1000+opts.get('mount_'+k,0) for k in ['x','y','z']],pose['roll'],pose['pitch'],pose['yaw'])
    for p,(angle,tof,power,classification) in zip(points,reference['points']):
        depth=math.cos(pitch)*(math.sin(roll)*math.sin(angle)+math.cos(roll)*math.cos(angle))*tof*reference['sos']/2
        assert p[2]==pytest.approx(-depth-offset[2],abs=1e-9)


@pytest.mark.parametrize('lon,lat,epsg',[(3,0,32631),(147,-20,32755),(-155.8,20,32605),(5.8,70,32631)])
def test_offsets_preserve_true_bearing_and_distance_in_utm(lon,lat,epsg):
    from pyproj import Geod
    forward=Transformer.from_crs(4326,epsg,always_xy=True)
    inverse=Transformer.from_crs(epsg,4326,always_xy=True)
    north,east=[0,500,-500,200],[500,0,0,-200]
    xs,ys=project_offsets(forward,lon,lat,north,east)
    out_lon,out_lat=inverse.transform(xs,ys)
    bearings,_,distances=Geod(ellps='WGS84').inv([lon]*4,[lat]*4,out_lon,out_lat)
    assert distances==pytest.approx(np.hypot(north,east),abs=1e-6)
    differences=(np.asarray(bearings)-np.degrees(np.arctan2(east,north))+180)%360-180
    assert differences==pytest.approx([0]*4,abs=1e-6)
