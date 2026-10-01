import itertools,json,time
from pathlib import Path
from collections import Counter
import numpy as np
ROOT=Path('work/survey-swath-audit-20260930')
FILES={'app':Path(r'C:\Users\synap\Downloads\2026-08-21-23-13.svlz_2026-08-21_xyz.csv'),'sonarview':Path(r'C:\Users\synap\Downloads\2026-08-21-23-13.csv')}
result={};cells={};samples={}
for name,path in FILES.items():
    total=0;lo=np.full(3,np.inf);hi=-lo;groups={};sample=[];classes=Counter();channels=Counter();elapsed=[float('inf'),-float('inf')];pings=[float('inf'),-float('inf')];header=[];start=time.monotonic();last=start
    masks_names=['all'] if name=='app' else ['all','class_not_2_negative_z','class_1']
    for group in masks_names: groups[group]={'count':0,'min':np.full(3,np.inf),'max':np.full(3,-np.inf),'cells':set()}
    with path.open(encoding='utf-8-sig',newline='') as f:
        while True:
            line=f.readline()
            if not line.startswith('#'): header.append(line.strip());break
            header.append(line.strip())
        while True:
            lines=list(itertools.islice(f,100000))
            if not lines:break
            a=np.loadtxt(lines,delimiter=',',usecols=(0,1,2) if name=='app' else (10,9,2,12,13,6,5,14,8),ndmin=2)
            xyz=a[:,:3];finite=np.isfinite(xyz).all(axis=1)
            masks={'all':finite}
            if name=='sonarview':
                masks.update(class_not_2_negative_z=finite&(a[:,3]!=2)&(a[:,2]<0),class_1=finite&(a[:,3]==1))
                u,c=np.unique(a[:,3],return_counts=True);classes.update(dict(zip(u.astype(int).tolist(),c.tolist())))
                u,c=np.unique(a[:,4],return_counts=True);channels.update(dict(zip(u.astype(int).tolist(),c.tolist())))
                elapsed=[min(elapsed[0],float(np.min(a[:,5]))),max(elapsed[1],float(np.max(a[:,5])))];pings=[min(pings[0],float(np.min(a[:,6]))),max(pings[1],float(np.max(a[:,6])))]
            for group,mask in masks.items():
                xyz=a[mask,:3];g=groups[group];g['count']+=len(xyz)
                if not len(xyz):continue
                g['min']=np.minimum(g['min'],xyz.min(axis=0));g['max']=np.maximum(g['max'],xyz.max(axis=0))
                xy=np.floor(xyz[:,:2]).astype(np.int64)
                packed=(xy[:,0].astype(np.uint64)<<32)|(xy[:,1].astype(np.uint64)&np.uint64(0xffffffff))
                g['cells'].update(np.unique(packed).tolist())
            sample.append(a[(-total)%100::100].copy());total+=len(a)
            if time.monotonic()-last>15:
                print(name,total,'rows scanned',flush=True);last=time.monotonic()
    samples[name]=np.concatenate(sample)
    saved_groups={}
    for group,g in groups.items():
        cells[name+'_'+group]=np.array(sorted(g.pop('cells')),dtype=np.uint64)
        saved_groups[group]={'count':g['count'],'min_xyz':g['min'].tolist(),'max_xyz':g['max'].tolist(),'span_xyz':(g['max']-g['min']).tolist(),'occupied_1m_cells':len(cells[name+'_'+group])}
    result[name]={'file':str(path),'bytes':path.stat().st_size,'rows':total,'header':header,'groups':saved_groups,'classes':dict(classes),'channels':dict(channels),'elapsed_range':elapsed if name=='sonarview' else None,'ping_range':pings if name=='sonarview' else None,'sample_quantiles_xyz':np.quantile(samples[name][:,:3],[0,.01,.5,.99,1],axis=0).tolist(),'scan_seconds':round(time.monotonic()-start,2)}
    print(json.dumps({name:result[name]}),flush=True)
app=cells['app_all']
comparison={}
for group in ['all','class_not_2_negative_z','class_1']:
    sv=cells['sonarview_'+group];both=np.intersect1d(app,sv)
    comparison[group]={'app_cells':len(app),'sonarview_cells':len(sv),'shared_cells':len(both),'app_only_cells':len(np.setdiff1d(app,sv)),'sonarview_only_cells':len(np.setdiff1d(sv,app))}
result['coverage_comparison']=comparison
np.savez_compressed(ROOT/'samples.npz',**samples)
np.savez_compressed(ROOT/'coverage.npz',**cells)
(ROOT/'comparison.json').write_text(json.dumps(result,indent=2))
print('COVERAGE',json.dumps(comparison),flush=True)
