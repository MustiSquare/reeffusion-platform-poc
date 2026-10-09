import React,{useCallback,useEffect,useMemo,useRef,useState} from 'react';
import * as THREE from 'three';
import {useThree} from '@react-three/fiber';
import {assetUrl,getJson,postJson} from '../api/client';
import {Area,LoadedChunk,RawManifest,intersects} from './rawPointData';
import {depthPaletteGLSL,turboGLSL,turboGradient} from './depthPalette';

export function useRawPoints(dataset:any){
  const [enabled,setEnabled]=useState(false),[source,setSource]=useState<any>(null),[job,setJob]=useState<any>({status:'idle'});
  const [manifest,setManifest]=useState<RawManifest|null>(null),[chunks,setChunks]=useState<LoadedChunk[]>([]);
  const [area,setArea]=useState<Area|null>(null),[selecting,setSelecting]=useState(false);
  const [scope,setScope]=useState<'overview'|'area'|'all'>('overview');
  const [progress,setProgress]=useState({loaded:0,total:0,points:0,complete:false});
  const [error,setError]=useState(''),[request,setRequest]=useState(0),[stopped,setStopped]=useState(false);
  const [pollRequest,setPollRequest]=useState(0);
  const active=useRef<AbortController|null>(null),workerRef=useRef<Worker|null>(null);
  const areaRef=useRef<Area|null>(null);areaRef.current=area;
  const root=source?.survey_id?`/api/survey/archive/${source.survey_id}/raw-points`:'';
  const areas:Area[]=useMemo(()=>source?.areas||[],[source]);
  const cellBounds=useMemo<Area|null>(()=>areas.length?[
    Math.min(...areas.map(a=>a[0])),Math.min(...areas.map(a=>a[1])),
    Math.max(...areas.map(a=>a[2])),Math.max(...areas.map(a=>a[3])),
  ]:null,[areas]);
  useEffect(()=>{
    let live=true;setEnabled(false);setSource(null);setManifest(null);setChunks([]);setArea(null);setSelecting(false);setError('');setJob({status:'idle'});setScope('overview');setStopped(false);
    if(dataset)getJson(`/api/survey/processed/${dataset.id}/raw-point-source`).then(s=>{if(live)setSource(s);}).catch(e=>{if(live)setSource({reason:e.message});});
    return()=>{live=false;active.current?.abort();workerRef.current?.terminate();};
  },[dataset?.id]);
  useEffect(()=>{
    if(!root)return;
    let live=true,timer:ReturnType<typeof setTimeout>;
    const poll=async()=>{try{
      const state=await getJson(root);if(!live)return;setJob(state);
      if(state.status==='completed'){
        const m=await getJson(`${root}/manifest`);
        if(m.crs!==dataset?.coordinate_system?.projected_crs)throw new Error('Raw recording and selected dataset use different coordinate systems. Select a matching survey dataset.');
        if(live)setManifest(m);
      }else if(state.status==='preparing'||state.status==='queued')timer=setTimeout(poll,1500);
    }catch(e:any){if(live){setError(e.message);timer=setTimeout(poll,5000);}}};
    poll();return()=>{live=false;clearTimeout(timer);};
  },[enabled,root,pollRequest]);
  const prepare=async()=>{setError('');try{setJob(await postJson(root));setPollRequest(n=>n+1);}catch(e:any){setError(e.message);}};
  const load=useCallback((mode:'overview'|'area'|'all')=>{setScope(mode);setStopped(false);setError('');setRequest(n=>n+1);},[]);
  const cancel=useCallback(()=>{active.current?.abort();workerRef.current?.terminate();setStopped(true);setProgress(p=>({...p,complete:false}));},[]);
  const contextLost=useCallback(()=>{cancel();setChunks([]);setError('Graphics context lost. Restore the viewer and use Overview or a smaller area; loading is incomplete.');},[cancel]);
  const renderFailed=useCallback(()=>{cancel();setChunks([]);setError('Could not allocate raw-point rendering resources. Use Overview or a smaller area; loading is incomplete.');},[cancel]);
  useEffect(()=>{if(!enabled)setSelecting(false);},[enabled]);
  useEffect(()=>{
    if(!enabled||!manifest||stopped){if(!enabled)setChunks([]);return;}
    const controller=new AbortController();active.current=controller;
    const worker=new Worker(new URL('./rawPoints.worker.ts',import.meta.url),{type:'module'});workerRef.current=worker;
    const clip=scope==='area'?areaRef.current:null;
    if(scope==='area'&&!clip){worker.terminate();return;}
    const list=(scope==='overview'?manifest.overview:manifest.chunks).filter(c=>areas.some(a=>intersects(c,a))&&(!clip||intersects(c,clip)));
    let next=0,done=0,points=0;const pending=new Map<string,{resolve:(v:Float32Array)=>void;reject:(e:Error)=>void}>();
    worker.onmessage=e=>{const p=pending.get(e.data.id);if(p){pending.delete(e.data.id);e.data.error?p.reject(new Error(e.data.error)):p.resolve(e.data.positions);}};
    worker.onerror=()=>{for(const p of pending.values())p.reject(new Error('Raw-point preparation failed; try a smaller area.'));pending.clear();};
    setChunks([]);setError('');setProgress({loaded:0,total:list.length,points:0,complete:list.length===0});
    async function consume(){while(next<list.length&&!controller.signal.aborted){
      const c=list[next++];const response=await fetch(assetUrl(`${root}/chunks/${c.id}`),{signal:controller.signal});
      if(!response.ok)throw new Error('Could not load raw-point chunk. Retry loading.');
      const buffer=await response.arrayBuffer();if(buffer.byteLength!==c.bytes)throw new Error('Incomplete raw-point chunk. Retry loading.');
      if(controller.signal.aborted)return;
      const positions=await new Promise<Float32Array>((resolve,reject)=>{pending.set(c.id,{resolve,reject});worker.postMessage({id:c.id,buffer,origin:c.origin,area:clip,areas},[buffer]);});
      if(controller.signal.aborted)return;
      done++;points+=positions.length/3;
      if(positions.length)setChunks(previous=>[...previous,{...c,positions}]);
      setProgress({loaded:done,total:list.length,points,complete:done===list.length});
    }}
    Promise.all(Array.from({length:4},consume)).then(()=>worker.terminate()).catch(e=>{if(!controller.signal.aborted){setError(`${e.message} Loading incomplete; retry or choose a smaller area.`);setProgress(p=>({...p,complete:false}));controller.abort();worker.terminate();for(const p of pending.values())p.reject(new Error('Loading stopped'));pending.clear();}});
    return()=>{controller.abort();worker.terminate();for(const p of pending.values())p.reject(new Error('Cancelled'));pending.clear();};
  },[enabled,manifest,scope,request,stopped,root,areas]);
  const setDefaultArea=useCallback((a:Area)=>setArea(old=>old||a),[]);
  const cellChunks=manifest?.chunks.filter(c=>areas.some(a=>intersects(c,a)))||[];
  const selected=area?cellChunks.filter(c=>intersects(c,area)):[];
  const estimate=(mode:'area'|'all')=>(mode==='all'?cellChunks:selected).reduce((n,c)=>n+c.bytes,0)*2;
  const chooseArea=(value:Area)=>{setArea(value);if(scope==='area'){cancel();setChunks([]);setProgress({loaded:0,total:0,points:0,complete:false});}};
  const chooseSource=(id:string)=>{active.current?.abort();setSource((s:any)=>({...s,...s.surveys.find((v:any)=>v.survey_id===id)}));setManifest(null);setChunks([]);setJob({status:'idle'});setError('');setStopped(false);setScope('overview');};
  return {enabled,setEnabled,source,chooseSource,job,manifest,chunks,area,cellBounds,setArea:chooseArea,selecting,setSelecting,scope,progress,error,prepare,load,cancel,contextLost,renderFailed,stopped,setDefaultArea,estimate,request};
}
export type RawState=ReturnType<typeof useRawPoints>;

export function RawPointControls({raw,onEnable,onSelect}:{raw:RawState;onEnable:()=>void;onSelect:()=>void}){
  return <section><h3>Raw sonar detections</h3>
    <label><input type="checkbox" checked={raw.enabled} disabled={!raw.source?.survey_id} onChange={e=>{raw.setEnabled(e.target.checked);if(e.target.checked)onEnable();}}/>Show raw detections</label>
    {!raw.source?.survey_id&&<small>{raw.source?.reason||'Finding original recording…'}</small>}
    {raw.source?.surveys?.length>1&&<label>Source survey<select value={raw.source.survey_id} onChange={e=>raw.chooseSource(e.target.value)}>{raw.source.surveys.map((s:any)=><option key={s.survey_id} value={s.survey_id}>{s.name}</option>)}</select></label>}
    {raw.enabled&&<>
      <small>Recording: {raw.source?.name}</small>
      {!raw.manifest&&<><p>{raw.job.stage||raw.job.reason||raw.job.error||'Prepare a full-detection index once for this survey.'} {raw.job.percent!==undefined?`${raw.job.percent}%`:''}</p>
        {!['queued','preparing','unavailable'].includes(raw.job.status)&&<button onClick={raw.prepare}>Prepare / retry raw points</button>}</>}
      {raw.manifest&&<>
        <p>Showing detections only within the selected cells.</p>
        <div aria-label="Turbo depth colour scale" style={{height:8,background:turboGradient}}/>
        <small>Turbo depth: deep Z {raw.manifest.min[2].toFixed(2)} m → shallow Z {raw.manifest.max[2].toFixed(2)} m</small>
        {raw.manifest.partial&&<p role="alert">Partial recording: {raw.manifest.warnings.join(' ')}</p>}
        <button onClick={()=>raw.load('overview')}>Overview (reduced)</button>
        <button onClick={()=>{raw.setSelecting(!raw.selecting);if(!raw.selecting)onSelect();}}>{raw.selecting?'Cancel selection':'Select inspection rectangle'}</button>
        {raw.area&&<small>Area: {(raw.area[2]-raw.area[0]).toFixed(1)} × {(raw.area[3]-raw.area[1]).toFixed(1)} m</small>}
        <button disabled={!raw.area} onClick={()=>raw.load('area')}>Full detail in selected area</button>
        <small>Area load: up to {Math.round(raw.estimate('area')/24).toLocaleString()} detections; {(raw.estimate('area')/1048576).toFixed(0)} MiB of CPU + GPU buffers. Other overhead additional.</small>
        <button onClick={()=>raw.load('all')}>Full detail in selected cells</button>
        <small>Selected-cell buffers: {(raw.estimate('all')/1048576).toFixed(0)} MiB; navigation may be slower.</small>
        <p role="status">{raw.scope==='overview'?'Reduced overview':raw.progress.complete?'Full detail':'Full detail — incomplete'} · {raw.progress.points.toLocaleString()} points loaded · {raw.progress.loaded}/{raw.progress.total} chunks{raw.stopped?' · Cancelled':''}</p>
        {!raw.progress.complete&&!raw.stopped&&<button onClick={raw.cancel}>Cancel loading</button>}
        <small>Raw depth colouring. Annotation and measurement tools act on the processed surface. Sea-level references and the depth ruler remain independent layers.</small>
      </>}
      {raw.error&&<p role="alert">{raw.error} <button onClick={()=>raw.load(raw.scope)}>Retry loading</button></p>}
    </>}
  </section>;
}

function ChunkPoints({chunk,anchor,zScale,size,range}:{chunk:LoadedChunk;anchor:number[];zScale:number;size:number;range:number[]}){
  const geometry=useMemo(()=>{const g=new THREE.BufferGeometry();g.setAttribute('position',new THREE.BufferAttribute(chunk.positions,3));g.computeBoundingSphere();return g;},[chunk]);
  const material=useMemo(()=>new THREE.ShaderMaterial({
    uniforms:{pointSize:{value:size},low:{value:range[0]},high:{value:range[1]},baseZ:{value:chunk.origin[2]}},
    vertexShader:`uniform float pointSize,low,high,baseZ; varying float depthColour; void main(){depthColour=clamp((position.y+baseZ-low)/max(0.001,high-low),0.0,1.0);gl_Position=projectionMatrix*modelViewMatrix*vec4(position,1.0);gl_PointSize=pointSize;}`,
    fragmentShader:`${turboGLSL} varying float depthColour; void main(){if(distance(gl_PointCoord,vec2(0.5))>0.5)discard;gl_FragColor=vec4(${depthPaletteGLSL},1.0);}`,
  }),[chunk]);
  material.uniforms.pointSize.value=size;material.uniforms.low.value=range[0];material.uniforms.high.value=range[1];
  useEffect(()=>()=>{geometry.dispose();material.dispose();},[geometry,material]);
  return <points geometry={geometry} material={material} raycast={()=>{}} position={[chunk.origin[0]-anchor[0],chunk.origin[2]*zScale,chunk.origin[1]-anchor[1]]} scale={[1,zScale,1]}/>;
}

export function RawPointLayer({raw,anchor,zScale,size}:{raw:RawState;anchor:number[];zScale:number;size:number}){
  const {gl}=useThree();
  useEffect(()=>{const lost=(e:Event)=>{e.preventDefault();raw.contextLost();};gl.domElement.addEventListener('webglcontextlost',lost);return()=>gl.domElement.removeEventListener('webglcontextlost',lost);},[gl,raw.contextLost]);
  if(!raw.enabled||!raw.manifest)return null;
  return <RawRenderBoundary key={raw.request} onError={raw.renderFailed}><group>{raw.chunks.map(c=><ChunkPoints key={c.id} chunk={c} anchor={anchor} zScale={zScale} size={Math.max(1,size*160)} range={[raw.manifest!.min[2],raw.manifest!.max[2]]}/>)}</group></RawRenderBoundary>;
}

class RawRenderBoundary extends React.Component<{children:React.ReactNode;onError:()=>void},{failed:boolean}>{
  state={failed:false};
  static getDerivedStateFromError(){return {failed:true};}
  componentDidCatch(){this.props.onError();}
  render(){return this.state.failed?null:this.props.children;}
}

/** Selection is a plane above the data, independent of any mesh or raw density. */
export function RawAreaSelection({raw,bounds,anchor,northSign}:{raw:RawState;bounds:THREE.Box3;anchor:number[];northSign:number}){
  const start=useRef<THREE.Vector3|null>(null);
  const [end,setEnd]=useState<THREE.Vector3|null>(null);
  if(!raw.selecting)return null;
  const center=bounds.getCenter(new THREE.Vector3()),size=bounds.getSize(new THREE.Vector3());
  const height=bounds.max.y+1;
  return <group>
    <mesh rotation={[-Math.PI/2,0,0]} position={[center.x,height,center.z]}
      onPointerDown={(e:any)=>{e.stopPropagation();start.current=e.point.clone();setEnd(e.point.clone());e.target.setPointerCapture(e.pointerId);}}
      onPointerMove={(e:any)=>{if(start.current){e.stopPropagation();setEnd(e.point.clone());}}}
      onPointerUp={(e:any)=>{e.stopPropagation();const p=start.current;if(!p)return;const q=e.point;const x1=p.x+anchor[0],x2=q.x+anchor[0],y1=p.z*northSign+anchor[1],y2=q.z*northSign+anchor[1];
        if(Math.abs(x1-x2)>.01&&Math.abs(y1-y2)>.01)raw.setArea([Math.min(x1,x2),Math.min(y1,y2),Math.max(x1,x2),Math.max(y1,y2)]);
        start.current=null;setEnd(null);raw.setSelecting(false);e.target.releasePointerCapture(e.pointerId);}}>
      <planeGeometry args={[Math.max(100,size.x*4),Math.max(100,size.z*4)]}/><meshBasicMaterial transparent opacity={0} depthWrite={false}/>
    </mesh>
    {start.current&&end&&<mesh raycast={()=>{}} position={[(start.current.x+end.x)/2,height+.01,(start.current.z+end.z)/2]} rotation={[-Math.PI/2,0,0]}><planeGeometry args={[Math.abs(start.current.x-end.x),Math.abs(start.current.z-end.z)]}/><meshBasicMaterial color="#22d3ee" transparent opacity={.3} depthWrite={false}/></mesh>}
  </group>;
}
