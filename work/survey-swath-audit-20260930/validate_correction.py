"""Independent reference audit; matches use power/depth only, never fitted XY."""
import csv
import io
import json
import math
import struct
import sys
from pathlib import Path
import numpy as np
sys.path.insert(0, 'backend')
from app.services.survey_replay import decode_detections, rotate


def packet(kind, payload):
    if isinstance(payload, dict): payload = json.dumps(payload).encode()
    header = b'BR' + struct.pack('<HHBB', len(payload), kind, 1, 0)
    return header + payload + struct.pack('<H', (sum(header)+sum(payload)) & 65535)


def recording(d):
    session = {'timestamp': '2026-07-10T20:00:00Z', 'session_devices': [{'product_id':'os3d45016', 'options':d['options']}]}
    raw = packet(10,session)
    for kind in ['ATTITUDE','GLOBAL_POSITION_INT']:
        raw += packet(150, {'message':{**d[kind], 'time_boot_ms':1000}})
    points = bytearray(80)
    struct.pack_into('<IfH',points,0,d['ping'],d['sos'],len(d['points']))
    struct.pack_into('<Q',points,16,1783713600000)
    points[28]=1;points[29]=d['device']
    struct.pack_into('<f',points,36,d['threshold'])
    for p in d['points']: points.extend(struct.pack('<fffB3x',*p))
    raw += packet(3104,points)
    end=bytearray(80);struct.pack_into('<fff',end,12,*d['up']);struct.pack_into('<I',end,24,d['ping']);end[66]=d['device']
    return raw+packet(3010,end)


if __name__ == '__main__':
    root=Path('work/survey-swath-audit-20260930')
    pings=json.loads((root/'heading-pings.json').read_text(encoding='utf-8-sig'))
    sv={d['ping']:[] for d in pings}
    cache=root/'heading-reference.json'
    if cache.exists():sv={int(k):v for k,v in json.loads(cache.read_text()).items()}
    else:
        with open(r'C:\Users\synap\Downloads\2026-08-21-23-13.csv') as f:
            for row in csv.DictReader(f):
                ping=int(row['ping number'])
                if ping>max(sv):break
                if ping in sv:
                    sv[ping].append([float(row[k]) for k in ['easting (UTM m)','northing (UTM m)','altitude (m)','power (dB)']])
        cache.write_text(json.dumps(sv))
    reports=[];fixtures=[]
    for d in pings:
        # Decode every finite supported point to retain raw packet indexing.
        all_points={**d,'threshold':0}
        decoded=[]
        decode_detections(io.BytesIO(recording(all_points)),'reference.svlog',lambda *p:decoded.append(p))
        roll=math.atan2(d['up'][1],d['up'][2]);pitch=math.asin(d['up'][0])
        opts=d['options'];mount=opts['components'][d['device']]['mount_fsd'];pose=d['ATTITUDE']
        offset=rotate([mount.get(k+'_mm',0)/1000+opts.get('mount_'+k,0) for k in ['x','y','z']],pose['roll'],pose['pitch'],pose['yaw'])
        indices=[]
        for i,(a,t,p,c) in enumerate(d['points']):
            distance=t*d['sos']/2
            down=math.cos(pitch)*(math.sin(roll)*math.sin(a)+math.cos(roll)*math.cos(a))*distance
            if .2<=distance<=500 and c!=2 and p>=0 and -down-offset[2]<0:indices.append(i)
        assert len(indices)==len(decoded)
        app=np.full((len(d['points']),3),np.nan);app[indices]=decoded
        power=10*np.log10(np.array(d['points'])[:,2]);valid=np.array(d['points'])[:,2]>=d['threshold']
        # SonarView's vertical lever-arm convention differs by several cm with
        # attitude. Estimate the dominant depth difference for association only;
        # neither XYZ output nor XY errors are adjusted.
        depth_differences=[]
        for row in sv[d['ping']]:
            ids=np.flatnonzero(valid & np.isfinite(app[:,2]) & (abs(power-row[3])<.05001))
            depth_differences.extend(app[ids,2]-row[2])
        values=np.array(depth_differences)
        rounded=np.round(values/.005).astype(int)
        keys,counts=np.unique(rounded,return_counts=True)
        mode=keys[np.argmax(counts)]*.005
        depth_difference=float(np.median(values[abs(values-mode)<=.005]))
        matches=[]
        for row in sv[d['ping']]:
            indices=np.flatnonzero(valid & (abs(power-row[3])<.05001) & (abs(app[:,2]-row[2]-depth_difference)<.002))
            if len(indices)==1:matches.append((int(indices[0]),row[:3]))
        # Require reciprocal uniqueness; no XY-based rejection or alignment.
        matches=[(i,p) for i,p in matches if sum(j==i for j,_ in matches)==1]
        if not matches:
            reports.append({'ping':d['ping'],'channel':d['device'],'matches':0,'note':'No unambiguous power/depth associations'})
            continue
        errors=np.array([np.linalg.norm(app[i,:2]-p[:2]) for i,p in matches])
        reports.append({'ping':d['ping'],'channel':d['device'],'heading_degrees':math.degrees(d['ATTITUDE']['yaw']),
                        'matches':len(matches),'association_depth_difference_m':depth_difference,'median_xy_m':float(np.median(errors)),
                        'p95_xy_m':float(np.quantile(errors,.95)), 'fraction_within_10cm':float(np.mean(errors<=.1))})
        chosen=matches[::max(1,len(matches)//32)]
        fixture={**d,'points':[d['points'][i] for i,_ in chosen], 'expected_xyz':[p for _,p in chosen]}
        fixture['options']={k:v for k,v in d['options'].items() if k in ['mount_x','mount_y','mount_z','mount_yaw_deg']}
        fixture['options']['components']=[{'mount_fsd':c.get('mount_fsd',{})} for c in d['options']['components']]
        fixture['GLOBAL_POSITION_INT']={k:v for k,v in d['GLOBAL_POSITION_INT'].items() if k in ['type','lat','lon','alt','hdg']}
        fixture['ATTITUDE']={k:v for k,v in d['ATTITUDE'].items() if k in ['type','roll','pitch','yaw']}
        fixtures.append(fixture)
    print(json.dumps(reports,indent=2))
    (root/'corrected-heading-validation.json').write_text(json.dumps(reports,indent=2))
    target=Path('backend/tests/fixtures/sonarview_coordinates.json');target.parent.mkdir(exist_ok=True)
    target.write_text(json.dumps({'source':'2026-08-21-23-13.csv, SonarView UTM 5N; independent power/depth matches, no XY fitting', 'pings':fixtures},indent=2))
