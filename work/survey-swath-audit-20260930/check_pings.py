import csv,itertools,json,math,sys
from pathlib import Path
import numpy as np
from pyproj import Transformer,Proj
sys.path.insert(0,'backend')
from app.services.survey_replay import rotate
root=Path('work/survey-swath-audit-20260930');pings=json.loads((root/'two_pings.json').read_text());wanted={p['ping'] for p in pings};sv_by={p:[] for p in wanted}
with open(r'C:\Users\synap\Downloads\2026-08-21-23-13.csv',newline='') as f:
    for row in csv.DictReader(f):
        ping=int(row['ping number'])
        if ping not in wanted:break
        sv_by[ping].append([float(row[k]) for k in ['easting (UTM m)','northing (UTM m)','altitude (m)','power (dB)','classification']])
reports=[];predicted_csv=[];plot_data={}
for d in pings:
    nav=d['GLOBAL_POSITION_INT'];pose=d['ATTITUDE'];opts=d['options'];mount=opts['components'][d['device']]['mount_fsd'];lon,lat=nav['lon']/1e7,nav['lat']/1e7
    center=np.array(Transformer.from_crs(4326,32605,always_xy=True).transform(lon,lat))
    roll=math.atan2(d['up'][1],d['up'][2]);pitch=math.asin(d['up'][0]);yaw=pose['yaw']+math.radians(mount.get('yaw_deg',0)+opts.get('mount_yaw_deg',0))
    offset=rotate([mount.get('x_mm',0)/1000+opts.get('mount_x',0),mount.get('y_mm',0)/1000+opts.get('mount_y',0),mount.get('z_mm',0)/1000+opts.get('mount_z',0)],pose['roll'],pose['pitch'],pose['yaw'])
    rows=[];valid=[]
    for angle,tof,power,cls in d['points']:
        distance=tof*d['sos']/2;n,e,down=rotate([0,math.sin(angle)*distance,math.cos(angle)*distance],roll,pitch,yaw)
        row=[center[0]+e+offset[1],center[1]+n+offset[0],-down-offset[2],10*math.log10(power),cls]
        rows.append(row);valid.append(power>=d['threshold'] and cls!=2 and .2<=distance<=500 and row[2]<0)
    app=np.array(rows);valid=np.array(valid);sv=np.array(sv_by[d['ping']]);predicted_csv.extend(app[valid,:3]);pairs=[]
    for row in sv:
        ix=np.flatnonzero(valid&(abs(app[:,3]-row[3])<.05001)&(abs(app[:,2]-row[2])<.05))
        if len(ix)==1:pairs.append((app[ix[0]],row))
    a=np.array([p for p,q in pairs]);b=np.array([q for p,q in pairs]);keep=np.ones(len(a),bool)
    def fit(keep):
        c1=a[keep,:2].mean(axis=0);c2=b[keep,:2].mean(axis=0);u,s,vt=np.linalg.svd((a[keep,:2]-c1).T@(b[keep,:2]-c2));rot=u@vt
        if np.linalg.det(rot)<0:u[:,-1]*=-1;rot=u@vt
        residual=np.linalg.norm((a[:,:2]-c1)@rot+c2-b[:,:2],axis=1)
        return rot,residual,c1,c2
    rot,res,_,_=fit(keep);keep=res<.5;rot,res,_,_=fit(keep)
    report={'ping':d['ping'],'channel':d['device'],'raw_packet_detections':len(app),'application_export_detections':int(valid.sum()),'sonarview_export_detections':len(sv),'candidate_power_depth_matches':len(a),'inliers_after_half_metre_residual_check':int(keep.sum()),'fitted_rotation_degrees':math.degrees(math.atan2(rot[0,1],rot[0,0])),'utm_meridian_convergence_degrees':Proj('EPSG:32605').get_factors(lon,lat).meridian_convergence,'xy_error_before_median_m':float(np.median(np.linalg.norm(a[keep,:2]-b[keep,:2],axis=1))),'xy_error_after_rotation_translation_median_m':float(np.median(res[keep])),'xy_error_after_p95_m':float(np.quantile(res[keep],.95)),'absolute_z_difference_median_m':float(np.median(abs(a[keep,2]-b[keep,2])))}
    reports.append(report)
    plot_data[f'app_channel{d["device"]}']=app[valid];plot_data[f'sv_channel{d["device"]}']=sv;plot_data[f'boat_channel{d["device"]}']=center
predicted_csv=np.array(predicted_csv)
with open(r'C:\Users\synap\Downloads\2026-08-21-23-13.svlz_2026-08-21_xyz.csv') as f:
    while f.readline().startswith('#'):pass
    actual=np.loadtxt(list(itertools.islice(f,len(predicted_csv))),delimiter=',')
report={'method':'Within each ping, pair unique power (within 0.05001 dB) and non-MSL height (within 0.05 m); rigid XY fit; exclude >0.5 m residual candidates and refit. Rounded fields cannot identify every detection uniquely.','first_two_pings_formula_vs_actual_csv_max_error_m':float(np.max(abs(actual-predicted_csv))),'pings':reports}
(root/'matched-pings.json').write_text(json.dumps(report,indent=2));np.savez_compressed(root/'matched-ping-plots.npz',**plot_data)
print(json.dumps(report,indent=2))
