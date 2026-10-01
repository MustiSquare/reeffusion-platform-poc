"""Lightweight archive index built from database metadata, never sonar payloads."""
import math
from datetime import datetime, timedelta, timezone
from uuid import uuid5, NAMESPACE_URL
from pyproj import Transformer
from pyproj.exceptions import CRSError
from sqlalchemy.orm import joinedload
from app.models.tables import RawDataset, ProcessedDataset
from app.services.overwrite import survey_date_key
from app.services.archive_grid import memberships
from app.services.survey_repair import visible


def dataset_info(d):
    meta = getattr(d,"metadata_json",None) or getattr(d,"viewer_config_json",None) or {}
    return {"id":d.id,"name":d.name,"status":d.status,"raw_dataset_id":getattr(d,"raw_dataset_id",None),
            "generation_state":meta.get("generation_state","active"), "coordinate_version":meta.get("coordinate_version",1)}


def archive_surveys(db):
    groups, raw_groups, proc_groups = {}, {}, {}
    raws = db.query(RawDataset).options(joinedload(RawDataset.location)).order_by(RawDataset.created_at.desc()).all()
    raw_by_id={r.id:r for r in raws}
    transforms={}
    processed = db.query(ProcessedDataset).order_by(ProcessedDataset.created_at.desc()).all()
    def group(key,name):
        key=str(uuid5(NAMESPACE_URL,"archive:"+key))
        if key not in groups:
            groups[key]={"id":key,"name":name,"raw":[],"processed":[],"cells":{},"starts":[],"ends":[],"locations":[]}
        return groups[key]
    for raw in raws:
        meta=raw.metadata_json or {}
        date=survey_date_key(raw.acquisition_started_at)
        identity=(meta.get("source_sha256")+":"+str(date)) if meta.get("source_sha256") else meta.get("replay_id",raw.id)
        g=group(identity,meta.get("survey_name") or raw.name.split(" \u00b7 ")[0])
        raw_groups[raw.id]=g["id"];g["raw"].append(dataset_info(raw))
        if not visible(raw): continue
        if date:g["starts"].append(date)
        if raw.acquisition_ended_at:g["ends"].append(survey_date_key(raw.acquisition_ended_at))
        cell=meta.get("block",{})
        if all(k in cell for k in ("size","column","row")):
            key=f"{cell['size']}:{cell['column']}:{cell['row']}"
            coords=raw.coordinate_system_json or {}
            footprint=None
            try:
                crs=coords["projected_crs"]
                if crs not in transforms:transforms[crs]=Transformer.from_crs(crs,4326,always_xy=True)
                convert=transforms[crs]
                x,y=cell["column"]*cell["size"],cell["row"]*cell["size"];s=cell["size"]
                footprint=[list(convert.transform(a,b)) for a,b in ((x,y),(x+s,y),(x+s,y+s),(x,y+s))]
                if not all(math.isfinite(v) for p in footprint for v in p):footprint=None
            except (KeyError,ValueError,TypeError,CRSError):pass
            previous=g["cells"].get(key,{})
            g["cells"][key]={**previous,"key":key,"size":cell["size"],"column":cell["column"],"row":cell["row"],"footprint":footprint or previous.get("footprint")}
        if raw.location and raw.location.latitude is not None and raw.location.longitude is not None:
            g["locations"].append([raw.location.longitude,raw.location.latitude])
    for p in processed:
        if p.raw_dataset_id in raw_groups:proc_groups[p.id]=raw_groups[p.raw_dataset_id]
    for p in processed:
        source_groups={proc_groups[i] for i in (p.viewer_config_json or {}).get("source_dataset_ids",[]) if i in proc_groups}
        gid=proc_groups.get(p.id) or (next(iter(source_groups)) if len(source_groups)==1 else None)
        g=groups[gid] if gid else group(p.id,(p.viewer_config_json or {}).get("survey_name") or p.name)
        g["processed"].append(dataset_info(p))
        if visible(p) and p.raw_dataset_id in raw_groups and p.status=="completed":
            raw=raw_by_id[p.raw_dataset_id]
            cell=(p.viewer_config_json or {}).get("block_snapshot") or (raw.metadata_json or {}).get("block",{})
            if all(k in cell for k in ("size","column","row")):
                key=f"{cell['size']}:{cell['column']}:{cell['row']}"
                c=g["cells"].get(key)
                if c is not None and (not c.get("dataset_id") or cell.get("until",0)>c.get("until",-1)):
                    c.update(dataset_id=p.id,until=cell.get("until",0))
    result=[]
    for g in groups.values():
        cells=list(g.pop("cells").values());locations=g.pop("locations")
        pts=[p for c in cells for p in c["footprint"] or []] or locations
        location=None
        if pts:
            longitude=math.degrees(math.atan2(sum(math.sin(math.radians(p[0])) for p in pts),sum(math.cos(math.radians(p[0])) for p in pts)))
            location={"longitude":longitude,"latitude":sum(p[1] for p in pts)/len(pts)}
        starts,ends=g.pop("starts"),g.pop("ends")
        start=min(starts) if starts else None;end=max(ends) if ends else None
        duration=max(0,(datetime.fromisoformat(end)-datetime.fromisoformat(start)).total_seconds()) if start and end else None
        sizes=sorted({c["size"] for c in cells})
        result.append({**g,"location":location,"started_at":start,"ended_at":end,"duration_seconds":duration,
            "area_memberships":memberships(cells),"received_cells":len(cells),"processed_cells":sum(bool(c.get("dataset_id")) for c in cells),"cells":cells,
            "grids":[{"size":s,"received":sum(c["size"]==s for c in cells),"processed":sum(c["size"]==s and bool(c.get("dataset_id")) for c in cells)} for s in sizes]})
    return result


def aggregate_conditions(summary,provider):
    location=summary["location"];start=summary["started_at"];end=summary["ended_at"]
    if not location or not start or not end:return {"available":False,"reason":"Survey location or acquisition interval unavailable"}
    start=datetime.fromisoformat(start);end=datetime.fromisoformat(end)
    if end<start or end-start>timedelta(days=31):return {"available":False,"reason":"Survey interval unavailable or exceeds 31 days"}
    hour=start.replace(minute=0,second=0,microsecond=0);stop=end if end>start else end+timedelta(microseconds=1)
    waves=[];winds=[];directions=[];expected=0;days={};warnings=[];wind_unit="km/h"
    while hour<stop:
        day=hour.date().isoformat()
        if day not in days:
            days[day]=provider(round(location["latitude"],2),round(location["longitude"],2),day)
            warnings.extend(days[day].get("warnings",[]))
        data=days[day];expected+=1
        def value(kind,key):
            series=(data.get(kind) or {}).get("hourly",{}).get(key,[])
            v=series[hour.hour] if len(series)>hour.hour else None
            return v if isinstance(v,(int,float)) and math.isfinite(v) else None
        wave=value("marine","wave_height");speed=value("weather","wind_speed_10m");direction=value("weather","wind_direction_10m")
        if wave is not None and wave>=0:waves.append(wave)
        if speed is not None and speed>=0:
            winds.append(speed)
            if direction is not None:directions.append((speed,math.radians(direction)))
        wind_unit=(data.get("weather") or {}).get("units",{}).get("wind_speed_10m",wind_unit)
        hour+=timedelta(hours=1)
    total=sum(s for s,_ in directions);x=sum(s*math.cos(d) for s,d in directions);y=sum(s*math.sin(d) for s,d in directions)
    bearing=(math.degrees(math.atan2(y,x))+360)%360 if total and math.hypot(x,y)/total>=.1 else None
    return {"available":bool(waves or winds),"wave_height_range":[min(waves),max(waves)] if waves else None,
        "wind_speed_range":[min(winds),max(winds)] if winds else None,"wind_unit":wind_unit,"wind_from_degrees":bearing,
        "wind_direction_label":"Variable / calm" if directions and bearing is None else None,
        "expected_hours":expected,"wave_hours":len(waves),"wind_hours":len(winds),"direction_hours":len(directions),
        "partial":len(waves)<expected or len(winds)<expected or len(directions)<expected,
        "warnings":list(dict.fromkeys(warnings)),"source":"Historical hourly model estimates","started_at":summary["started_at"],"ended_at":summary["ended_at"]}
