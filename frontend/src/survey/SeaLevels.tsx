import {useEffect,useMemo,useState} from 'react';
import * as THREE from 'three';
export type Sounding=[number,number,number,number];
export type SeaLevels={offset:string;showSurface:boolean;showMsl:boolean};
const empty:SeaLevels={offset:'3',showSurface:true,showMsl:true};
export function referenceHeight(value:string):number|null{if(!value.trim())return null;const n=Number(value);return Number.isFinite(n)?n:null;}
export function referenceHeights(offset:number|null){
  return {blue:0,yellow:offset===null?null:-offset};
}
function read(key:string):SeaLevels{try{const s=JSON.parse(localStorage.getItem(`reef-sea-zero-v3:${key}`)||'null');if(s&&typeof s.offset==='string')return {...empty,...s};}catch{}return {...empty};}
export function useSeaLevels(key:string){
  const [stored,setStored]=useState(()=>({key,value:read(key)}));const levels=useMemo(()=>stored.key===key?stored.value:read(key),[stored,key]);
  function update(value:SeaLevels){setStored({key,value});try{localStorage.setItem(`reef-sea-zero-v3:${key}`,JSON.stringify(value));}catch{}}
  return [levels,update] as const;
}
export function SeaLevelControls({levels,update,status,count}: {levels:SeaLevels;update:(v:SeaLevels)=>void;status:string;count:number}){
  return <div className="sea-level-controls"><h3>Sea level and MSL</h3>
    <small>{status} {count>0?`${count.toLocaleString()} measured positions.`:''}</small>
    <b style={{color:'#249fff'}}>Blue sea level: Z = 0.00 m</b>
    <label>MSL below sea level (m)<input aria-label="MSL below sea level" type="number" step="0.01" placeholder="Set offset" value={levels.offset} onChange={e=>update({...levels,offset:e.target.value})}/></label>
    <small>Positive means below blue: 3 m places yellow at Z = -3 m. This is a user-set display reference; XYZ heights are unchanged.</small>
    <label><input type="checkbox" checked={levels.showSurface} onChange={e=>update({...levels,showSurface:e.target.checked})}/> Blue sea-level grid</label>
    <label><input type="checkbox" checked={levels.showMsl} onChange={e=>update({...levels,showMsl:e.target.checked})}/> Yellow MSL surface</label>
  </div>;
}
export function nearestSounding(points:Sounding[],picked?:{x:number;y:number}|null){
  if(!picked)return null;let best:Sounding|null=null,dist=4;
  for(const p of points){const d=(p[0]-picked.x)**2+(p[1]-picked.y)**2;if(d<dist){best=p;dist=d;}}
  return best;
}
export function SeaLevelReadout({point,levels}:{point:Sounding|null;levels:SeaLevels}){
  if(!point)return <small>Select a seabed point to inspect its nearest recorded sounding (within 2 m).</small>;
  const h=referenceHeights(referenceHeight(levels.offset));
  return <div className="sea-level-readout"><span>Nearest sounding Z: {point[2].toFixed(2)} m</span><span>Vertical sonar altitude: {point[3].toFixed(2)} m</span>
    <span style={{color:'#249fff'}}>Blue height above point: {(h.blue-point[2]).toFixed(2)} m</span>
    <span style={{color:'#d49b22'}}>MSL Z: {h.yellow===null?'offset required':`${h.yellow.toFixed(2)} m`}</span>
    <span style={{color:'#d49b22'}}>MSL height above point: {h.yellow===null?'offset required':`${(h.yellow-point[2]).toFixed(2)} m`}</span>
    <small>Distances use original metres; both surfaces follow Z exaggeration.</small></div>;
}
// Continuous reference water surfaces span the selected footprint, independently of seabed gaps.
export function referenceTopology(points:Sounding[]){
  let minX=Infinity,minY=Infinity,maxX=-Infinity,maxY=-Infinity;
  for(const p of points)if(p.length>=4&&p.every(Number.isFinite)&&p[3]>0){minX=Math.min(minX,p[0]);minY=Math.min(minY,p[1]);maxX=Math.max(maxX,p[0]);maxY=Math.max(maxY,p[1]);}
  const positions:number[][]=[],edges:number[]=[],faces:number[]=[];
  if(!Number.isFinite(minX))return {positions,edges,faces};
  minX=Math.floor(minX);minY=Math.floor(minY);maxX=Math.max(minX+1,Math.ceil(maxX));maxY=Math.max(minY+1,Math.ceil(maxY));
  positions.push([minX,minY],[maxX,minY],[maxX,maxY],[minX,maxY]);
  faces.push(0,1,2,0,2,3);edges.push(0,1,1,2,2,3,3,0);
  // Limit grid density for large multi-cell selections.
  const step=Math.max(1,Math.ceil(Math.max(maxX-minX,maxY-minY)/50));
  function line(a:number[],b:number[]){const i=positions.length;positions.push(a,b);edges.push(i,i+1);}
  for(let x=minX+step;x<maxX;x+=step)line([x,minY],[x,maxY]);
  for(let y=minY+step;y<maxY;y+=step)line([minX,y],[maxX,y]);
  return {positions,edges,faces};
}
export function SoundingSurfaces({points,levels,zScale,picked}:{points:Sounding[];levels:SeaLevels;zScale:number;picked?:{x:number;y:number;z:number}|null}){
  const topology=useMemo(()=>referenceTopology(points),[points]);
  const offset=referenceHeight(levels.offset);
  const geometry=useMemo(()=>{
    const blue=new THREE.BufferGeometry(),yellow=new THREE.BufferGeometry();
    const a:number[]=[],b:number[]=[];
    for(const p of topology.positions){const h=referenceHeights(offset);a.push(p[0],h.blue*zScale,p[1]);b.push(p[0],(h.yellow??h.blue)*zScale,p[1]);}
    blue.setAttribute('position',new THREE.Float32BufferAttribute(a,3));blue.setIndex(topology.edges);
    yellow.setAttribute('position',new THREE.Float32BufferAttribute(b,3));yellow.setIndex(topology.faces);
    return {blue,yellow};
  },[topology,offset,zScale]);
  useEffect(()=>()=>Object.values(geometry).forEach(g=>g.dispose()),[geometry]);
  const guide=useMemo(()=>{const p=nearestSounding(points,picked);if(!p)return null;const h=referenceHeights(offset);return new THREE.BufferGeometry().setFromPoints([new THREE.Vector3(p[0],p[2]*zScale,p[1]),new THREE.Vector3(p[0],h.blue*zScale,p[1])]);},[points,picked,offset,zScale]);
  useEffect(()=>()=>guide?.dispose(),[guide]);
  return <group>
    {levels.showSurface&&<lineSegments geometry={geometry.blue} raycast={()=>{}} renderOrder={6}><lineBasicMaterial color="#168fff" transparent opacity={.55} depthWrite={false}/></lineSegments>}
    {levels.showMsl&&offset!==null&&<mesh geometry={geometry.yellow} raycast={()=>{}} renderOrder={5}><meshBasicMaterial color="#ffe133" transparent opacity={.2} depthWrite={false} side={THREE.DoubleSide}/></mesh>}
    {guide&&levels.showSurface&&<lineSegments geometry={guide} raycast={()=>{}}><lineBasicMaterial color="#168fff"/></lineSegments>}
  </group>;
}
