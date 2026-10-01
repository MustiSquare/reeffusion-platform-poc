import {useEffect,useRef,useState} from 'react';
import L from 'leaflet';
import 'leaflet/dist/leaflet.css';
import {getJson} from '../api/client';
import world from './world.svg';
import './survey.css';

export function WorldThumbnail({location}:any){
  return <svg viewBox="0 0 360 180" width="180" height="90" role="img" aria-label={location?'Survey location on world map':'Survey location unavailable'}>
    <image href={world} width="360" height="180"/>
    {location&&<circle cx={180+location.longitude} cy={90-location.latitude} r="6" fill="#ff3333" stroke="white" strokeWidth="2"/>}
  </svg>;
}

export function ArchiveConditions({id}: {id:string}){
  const host=useRef<HTMLDivElement>(null),[visible,setVisible]=useState(false),[data,setData]=useState<any>();
  useEffect(()=>{
    if(!host.current)return;
    if(typeof IntersectionObserver==='undefined'){setVisible(true);return;}
    const observer=new IntersectionObserver(entries=>{if(entries.some(e=>e.isIntersecting)){setVisible(true);observer.disconnect();}},{rootMargin:'150px'});
    observer.observe(host.current);return()=>observer.disconnect();
  },[]);
  useEffect(()=>{if(!visible)return;let cancelled=false;setData(undefined);
    getJson(`/api/survey/archive/${id}/conditions`).then(d=>{if(!cancelled)setData(d);}).catch(()=>{if(!cancelled)setData({available:false,reason:'Historical conditions unavailable'});});
    return()=>{cancelled=true;};
  },[id,visible]);
  const range=(v:any,unit:string)=>v?`${v[0].toFixed(1)}–${v[1].toFixed(1)} ${unit}`:'unavailable';
  return <div ref={host} className="archive-conditions">{!data?'Loading historical conditions…':!data.available?(data.reason||'Historical conditions unavailable'):<>
    <span>Historical sea state (wave height): {range(data.wave_height_range,'m')}</span>{' · '}
    <span>Wind: {range(data.wind_speed_range,data.wind_unit)}; from {data.wind_from_degrees!=null?`${Math.round(data.wind_from_degrees)%360}°`:data.wind_direction_label||'unavailable'}</span>
    <small> {data.source}{data.partial?` · Partial coverage: waves ${data.wave_hours}/${data.expected_hours} hours, wind ${data.wind_hours}/${data.expected_hours} hours`:''}</small>
  </>}</div>;
}

export function CellMap({cells,selected,onCell,compact=false,coverage=[],detectionPolygons=[]}:any){
  const host=useRef<HTMLDivElement>(null),map=useRef<L.Map|null>(null),layer=useRef<L.FeatureGroup|null>(null),callback=useRef(onCell);
  callback.current=onCell;
  const [tileError,setTileError]=useState(false);
  useEffect(()=>{
    if(!host.current)return;
    const m=L.map(host.current,{preferCanvas:true}).setView([0,0],2);map.current=m;
    L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png',{maxZoom:22,maxNativeZoom:19,attribution:'© OpenStreetMap contributors'}).on('tileerror',()=>setTileError(true)).addTo(m);
    const pane=m.createPane('archiveSelection');pane.style.zIndex='650';pane.style.pointerEvents='none';
    const soundings=m.createPane('archiveSoundings');soundings.style.zIndex='450';soundings.style.pointerEvents='none';
    layer.current=L.featureGroup().addTo(m);
    const resize=new ResizeObserver(()=>m.invalidateSize());resize.observe(host.current);
    return()=>{resize.disconnect();m.remove();map.current=null;};
  },[]);
  const geometry=JSON.stringify(cells.map((c:any)=>[c.key,c.footprint]));
  useEffect(()=>{
    const pts=cells.flatMap((c:any)=>(c.footprint||[]).map((p:number[])=>[p[1],p[0]]));
    if(pts.length)map.current?.fitBounds(L.latLngBounds(pts),{padding:[20,20],maxZoom:19});
  },[geometry]);
  useEffect(()=>{
    if(!layer.current)return;layer.current.clearLayers();
    for(const polygon of detectionPolygons){
      L.polygon(polygon.map((p:number[])=>[p[1],p[0]]),{pane:'archiveSoundings',stroke:false,fillColor:'#e9e36c',fillOpacity:.45,interactive:false}).addTo(layer.current!);
    }
    cells.forEach((c:any)=>{
      if(!c.footprint)return;
      const points=c.footprint.map((p:number[])=>[p[1],p[0]]);
      const p=L.polygon(points,{color:c.dataset_id?'#16b8aa':'#d89e32',weight:2,fillOpacity:.25}).addTo(layer.current!);
      p.on('click',()=>callback.current(c));
      if(selected.includes(c.dataset_id))L.polygon(points,{pane:'archiveSelection',interactive:false,color:'#ff4ea0',weight:4,fillOpacity:.45}).addTo(layer.current!);
    });
    for(const point of coverage){
      const depth=Math.max(0,-point[2]);
      L.circleMarker([point[1],point[0]],{pane:'archiveSoundings',radius:2,color:`hsl(${185+Math.min(70,depth)},80%,${65-Math.min(30,depth/3)}%)`,weight:0,fillOpacity:.85,interactive:false}).addTo(layer.current!);
    }
  },[cells,selected,coverage,detectionPolygons]);
  return <><div ref={host} style={{height:compact?230:540,borderRadius:12,margin:'12px 0'}} aria-label="Archived survey cells map"/>{tileError&&<small>Basemap unavailable; survey cells remain selectable.</small>}</>;
}

export default function ArchiveExplorer({survey,selected,setSelected,open,openArea,compact=false,fullMap}:any){
  const [size,setSize]=useState<number>(),[multi,setMulti]=useState(false),[error,setError]=useState(''),[busy,setBusy]=useState(false);
  useEffect(()=>{setSize(survey.cells.find((c:any)=>selected.includes(c.dataset_id))?.size??survey.grids[0]?.size);setError('');},[survey.id,compact]);
  const grid=size??survey.grids[0]?.size;
  const [coverage,setCoverage]=useState<any>(null),[coverageError,setCoverageError]=useState('');
  const [showDetections,setShowDetections]=useState(false),[detections,setDetections]=useState<any>(null);
  useEffect(()=>{
    let cancelled=false;setDetections(null);
    if(showDetections)getJson(`/api/survey/archive/${survey.id}/detection-coverage`).then(data=>{if(!cancelled)setDetections(data);}).catch(e=>{if(!cancelled)setDetections({reason:e.message});});
    return()=>{cancelled=true;};
  },[survey.id,showDetections]);
  useEffect(()=>{
    let cancelled=false;setCoverage(null);setCoverageError('');
    if(grid!=null)getJson(`/api/survey/archive/${survey.id}/coverage?size=${grid}`).then(data=>{if(!cancelled)setCoverage(data);}).catch(()=>{if(!cancelled)setCoverageError('Measured point coverage unavailable.');});
    return()=>{cancelled=true;};
  },[survey.id,grid]);
  const cells=(survey.cells||[]).filter((c:any)=>c.size===grid);
  async function click(c:any){
    if(!c.dataset_id){setError('This cell has not been processed yet.');return;}
    setError('');
    if(multi&&!compact){
      if(selected.includes(c.dataset_id))setSelected(selected.filter((id:string)=>id!==c.dataset_id));
      else if(selected.length<20)setSelected([...selected,c.dataset_id]);
      else setError('Select a maximum of 20 cells. Deselect one to choose another.');
    }else {setBusy(true);try{await open(c.dataset_id);setSelected([c.dataset_id]);}catch(e:any){setError(e.message);}finally{setBusy(false);}}
  }
  return <div className="archive-explorer"><h3>{survey.name}{compact?' · Cell navigator':' · Archived survey'}</h3>
    <div className="survey-controls">
      <label>Cell size <select value={grid??''} onChange={e=>{setSize(Number(e.target.value));setSelected([]);}}>{survey.grids.map((g:any)=><option key={g.size} value={g.size}>{g.size} m × {g.size} m ({g.processed} processed)</option>)}</select></label>
      {compact?<button onClick={fullMap}>Open entire survey map · select up to 20 cells</button>:<>
        <button disabled={busy||(multi&&!selected.length)} onClick={async()=>{
          if(!multi){setMulti(true);setSelected([]);setError('');return;}
          setBusy(true);setError('');
          try{await (selected.length===1?open(selected[0]):openArea(selected));}
          catch(e:any){setError(e.message);}finally{setBusy(false);}
        }}>{busy?'Opening...':multi?`Open ${selected.length}/20 selected cells`:'Select multiple cells'}</button>
        {multi&&<button disabled={busy} onClick={()=>{setMulti(false);setSelected([]);setError('');}}>Cancel selection</button>}
      </>}
    </div>
    {error&&<p role="alert">{error}</p>}
    <p>Teal: processed · Amber: not processed · Pink: selected. Click a processed cell to {multi&&!compact?'select it':'open it in the processed viewer'}.</p>
    <p>{compact?`Viewing ${selected.length} selected cells of ${cells.length} survey cells.`:`Whole survey map: ${cells.length} cells. The 3D viewer opens selected processed surfaces.`}</p>
    <label><input type="checkbox" checked={showDetections} onChange={e=>setShowDetections(e.target.checked)}/> Show full detection footprint (yellow, 1 m squares)</label>
    {showDetections&&<small>{detections?.reason||(!detections?'Loading full detection coverage…':`${detections.occupied_square_metres?.toLocaleString()} occupied 1 m squares · no sampling`)}</small>}
    {cells.some((c:any)=>c.footprint)?<CellMap cells={cells} selected={selected} onCell={busy?()=>{}:click} compact={compact} coverage={coverage?.points||[]} detectionPolygons={showDetections?detections?.polygons||[]:[]}/>:<p>Cell footprints unavailable for this dataset.</p>}
    <small>{coverageError||(!coverage?'Loading measured point coverage...':`Measured point coverage: ${coverage.total_points?.toLocaleString()??0} points${coverage.sampled?' (sampled map preview)':''}.`)}</small>
    {coverage?.warnings?.map((warning:string)=><small key={warning}>{warning}</small>)}
    {!compact&&<ArchiveConditions id={survey.id}/>}
  </div>;
}
