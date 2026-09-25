"""Recorded navigation references; never infer a waterline from GPS altitude."""
import math


def summarize_references(samples,total):
    samples=[s for s in samples if s.get('soundings',0)>0]
    if not samples:return None
    n=sum(s['soundings'] for s in samples)
    mean=sum(s['vehicle_altitude_msl_m']*s['soundings'] for s in samples)/n
    return {'version':1,'source':'GLOBAL_POSITION_INT.alt (mm converted to metres)',
        'vehicle_altitude_msl_m':mean,
        'vehicle_altitude_msl_range_m':[min(s['vehicle_altitude_msl_range_m'][0] for s in samples),max(s['vehicle_altitude_msl_range_m'][1] for s in samples)],
        'soundings':n,'total_soundings':total,'coverage':n/total if total else 0,
        'msl_z_m':None,'sea_surface_z_m':None,'status':'navigation_altitude_only',
        'note':'Navigation altitude is retained for provenance, not used as sonar altitude or a sea-level plane. Waterline and MSL offsets are not recorded.'}


def block_reference(replay,column,row,size,until):
    samples=[];total=0
    for frame in replay['frames']:
        if frame['t']>until:break
        for p in frame['points']:
            if math.floor(p[0]/size)==column and math.floor(p[1]/size)==row:total+=p[5]
        for x,y,alt_sum,n,low,high in frame.get('vertical_samples',[]):
            if math.floor(x/size)==column and math.floor(y/size)==row:
                samples.append({'soundings':n,'vehicle_altitude_msl_m':alt_sum/n,'vehicle_altitude_msl_range_m':[low,high]})
    return summarize_references(samples,total)


def sounding_reference(replay,column,row,size,until):
    bins={}
    for f in replay['frames']:
        if f['t']>until:break
        for x,y,z,alt,n in f.get('sounding_altitudes',[]):
            if math.floor(x/size)!=column or math.floor(y/size)!=row:continue
            if not all(math.isfinite(v) for v in [x,y,z,alt,n]) or alt<=0 or n<=0:continue
            key=(math.floor(x),math.floor(y));v=bins.setdefault(key,[0.,0.,0.,0.,0])
            for i,value in enumerate([x-column*size,y-row*size,z,alt]):v[i]+=value*n
            v[4]+=n
    return {'version':2,'columns':['x','y','seabed_z','altitude_m'],
        'points':[[round(v[i]/v[4],6) for i in range(4)] for v in bins.values()],
        'source':'Beam-angle and attitude-corrected vertical sonar distance',
        'waterline_offset_m':None,'msl_offset_m':None,
        'note':'Blue shows seabed Z + sonar altitude. A known transducer-to-waterline offset is needed to label it sea surface. Yellow requires sea-surface height above MSL.'}


def processed_sounding_reference(dataset,db,storage,load_replay,seen=None):
    import json
    from app.models.tables import RawDataset,ProcessedDataset
    from fastapi import HTTPException
    seen=set() if seen is None else set(seen)
    if dataset.id in seen:raise HTTPException(422,'Circular survey source references')
    seen.add(dataset.id)
    asset=next((a for a in dataset.assets if a.asset_type=='sounding_references'),None)
    if asset:return json.loads(storage.get_bytes(asset.object_key))
    source_ids=(dataset.viewer_config_json or {}).get('source_dataset_ids',[])
    if source_ids:
        anchor=(dataset.coordinate_system_json or {}).get('projected_origin')
        if not anchor:return {'version':2,'points':[],'note':'Projected origin unavailable'}
        parts=[]
        for source_id in source_ids:
            source=db.get(ProcessedDataset,source_id)
            if not source:continue
            data=processed_sounding_reference(source,db,storage,load_replay,seen)
            origin=(source.coordinate_system_json or {}).get('projected_origin')
            if origin:parts.extend([[p[0]+origin[0]-anchor[0],p[1]+origin[1]-anchor[1],*p[2:]] for p in data.get('points',[])])
        return {'version':2,'points':parts,'waterline_offset_m':None,'msl_offset_m':None,'source':'Combined per-sounding vertical distances'}
    raw=db.get(RawDataset,dataset.raw_dataset_id) if dataset.raw_dataset_id else None
    meta=(raw.metadata_json or {}) if raw else {}
    block=(dataset.viewer_config_json or {}).get('block_snapshot') or meta.get('block',{})
    if not meta.get('replay_id') or not all(k in block for k in ['column','row','size','until']):
        return {'version':2,'points':[],'note':'No recorded sonar distances for this dataset'}
    replay=load_replay(meta['replay_id'])
    return sounding_reference(replay,block['column'],block['row'],block['size'],block['until'])
