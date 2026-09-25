import { mapDisplayBlocks, MAX_MAP_POINTS } from './mapDisplay';
import { useEffect, useMemo, useRef, useState } from 'react';
import L from 'leaflet';
import 'leaflet/dist/leaflet.css';
import blueBoatSprite from './blueboat.svg';
import ConditionsSprites, { MapConditions } from './ConditionsSprites';
import { Block, Boat, Replay, converter, contours } from './model';

export default function SurveyMap({ replay, blocks, boat, track, selected, select, jobs, visible, size, multiSelect=false, selectedCells=[], conditions={} }: {
  replay: Replay|null; blocks: Block[]; boat: Boat|null; track: Boat[]; selected: string;
  select: (key:string)=>void; jobs: Record<string,any>; visible: boolean; size: number;
  multiSelect?:boolean; selectedCells?:string[]; conditions?:MapConditions;
}) {
  const host=useRef<HTMLDivElement>(null), map=useRef<L.Map|null>(null), overlay=useRef<L.FeatureGroup|null>(null);
  const [follow,setFollow]=useState(true), [showContours,setShowContours]=useState(true);
  const [tileError,setTileError]=useState(false);
  const displayBlocks=useMemo(()=>mapDisplayBlocks(blocks),[blocks]);
  const contourSegments=useMemo(()=>visible&&showContours?contours(blocks.flatMap(b=>b.points)):[],[blocks,visible,showContours]);
  // Grid size is supplied on blocks to ensure the map matches the processing grid.
  useEffect(()=>{
    if(!host.current) return;
    const m=L.map(host.current,{preferCanvas:true}).setView([20,-155],5); map.current=m;
    const coast=L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png',{maxZoom:20,maxNativeZoom:19,attribution:'© <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'}).addTo(m);
    const gebco=L.tileLayer.wms('https://wms.gebco.net/mapserv?',{layers:'GEBCO_LATEST',format:'image/png',version:'1.1.1',attribution:'<a href="https://www.gebco.net">GEBCO Compilation Group</a> — regional bathymetry, ~450 m grid'});
    const ocean=L.tileLayer('https://services.arcgisonline.com/ArcGIS/rest/services/Ocean/World_Ocean_Base/MapServer/tile/{z}/{y}/{x}',{maxNativeZoom:13,maxZoom:20,attribution:'Ocean basemap: Esri, GEBCO, NOAA and contributors'});
    [coast,gebco,ocean].forEach(layer=>layer.on('tileerror',()=>setTileError(true)));
    m.on('baselayerchange',()=>setTileError(false));
    L.control.layers({'GEBCO depths':gebco,'Coastlines / streets':coast,'Regional ocean contours':ocean}).addTo(m);
    L.control.scale({imperial:false}).addTo(m);
    const selectionPane=m.createPane('surveySelection');
    selectionPane.style.zIndex='650';
    selectionPane.style.pointerEvents='none';
    overlay.current=L.featureGroup().addTo(m);
    const resize=new ResizeObserver(()=>m.invalidateSize()); resize.observe(host.current);
    return ()=>{resize.disconnect();m.remove();map.current=null;};
  },[]);
  useEffect(()=>{ if(visible) map.current?.invalidateSize(); },[visible]);
  useEffect(()=>{
    const first=replay?.frames.find(f=>f.boat)?.boat;
    if(first) map.current?.setView([first[1],first[0]],17);
  },[replay?.id]);
  useEffect(()=>{
    const m=map.current, group=overlay.current;
    if(!m||!group||!visible) return;
    group.clearLayers();
    if(!replay) return;
    const projection=converter(replay.crs);
    const ll=(x:number,y:number):L.LatLngTuple=>{const [lon,lat]=projection.forward([x,y]);return [lat,lon];};
    const displayed=displayBlocks;
    for(const block of displayed){
      const s=size;
      const x=block.column*s,y=block.row*s,job=jobs[block.key];
      const current=job && (job.samples===block.samples || job.until>=block.last);
      const picked=multiSelect?selectedCells.includes(block.key):selected===block.key;
      const color=multiSelect&&picked?'#f472b6':current&&job.status==='completed'?'#2dd4bf':job?.status==='failed'?'#ef4444':job&&job.status!=='completed'?'#a78bfa':'#f59e0b';
      L.polygon([ll(x,y),ll(x+s,y),ll(x+s,y+s),ll(x,y+s)],{color,weight:picked?3:1,fillOpacity:picked?.25:.025})
        .on('click',()=>select(block.key)).addTo(group);
      if(picked) L.polygon([ll(x,y),ll(x+s,y),ll(x+s,y+s),ll(x,y+s)],{
        pane:'surveySelection',color:'#f472b6',weight:4,fillColor:'#f472b6',fillOpacity:.35,interactive:false,
      }).addTo(group);
      for(const p of block.points){
        const depth=Math.max(0,-p[2]),color=`hsl(${185+Math.min(70,depth)},80%,${65-Math.min(30,depth/3)}%)`;
        L.circleMarker([p[4],p[3]],{radius:2,color,weight:0,fillOpacity:.85,interactive:false}).addTo(group);
      }
    }
    if(showContours){
      const lines=contourSegments.map(line=>line.map(p=>ll(p[0],p[1])));
      if(lines.length) L.polyline(lines,{color:'#e0f2fe',weight:1,opacity:.8,interactive:false}).addTo(group);
    }
    if(track.length) L.polyline(track.map(p=>[p[1],p[0]]),{color:'#fb923c',weight:2,interactive:false}).addTo(group);
    if(boat){
      L.marker([boat[1],boat[0]],{icon:L.divIcon({className:'survey-boat',html:`<img src="${blueBoatSprite}" alt="BlueBoat USV" draggable="false" style="transform:rotate(${Number.isFinite(boat[2])?boat[2]:0}deg)"/>`,iconSize:[64,64],iconAnchor:[32,32]})}).bindTooltip('BlueBoat USV').addTo(group);
      if(follow&&!multiSelect) m.panTo([boat[1],boat[0]],{animate:false});
    }
  },[replay,blocks,displayBlocks,contourSegments,boat,track,selected,jobs,follow,showContours,size,visible,select,multiSelect,selectedCells]);
  return <div className="survey-map-wrap">
    <div className="survey-map-viewport">
      <div className="survey-map" ref={host} aria-label="BlueBoat survey map" />
      <ConditionsSprites {...conditions}/>
    </div>
    <div className="survey-map-tools">
      <label><input type="checkbox" checked={follow} onChange={e=>setFollow(e.target.checked)}/> Follow BlueBoat</label>
      <label><input type="checkbox" checked={showContours} onChange={e=>setShowContours(e.target.checked)}/> Survey contours (2 m)</label>
      <button onClick={()=>{setFollow(false);map.current?.setZoom(7);}}>Regional view</button>
      <button onClick={()=>{setFollow(true);map.current?.setZoom(18);}}>Survey view</button>
      <button onClick={()=>{setFollow(false);const bounds=overlay.current?.getBounds();if(bounds?.isValid())map.current?.fitBounds(bounds,{padding:[25,25],maxZoom:18});}}>Fit all received cells</button>
    </div>
    {displayBlocks!==blocks&&<small>Map preview limited to {MAX_MAP_POINTS.toLocaleString()} points; all received data is retained for processing.</small>}
    {tileError&&<p className="survey-warning">A background map service is unavailable. Survey measurements remain visible; try another layer.</p>}
  </div>;
}
