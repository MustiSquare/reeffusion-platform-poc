import {useMemo,useEffect} from 'react';
import * as THREE from 'three';
import {useLoader} from '@react-three/fiber';
import {seaOrientation} from './orientationMath';
import boatUrl from './blueboat-scale.svg';
function CompassLabel({text,position,size}:{text:string;position:[number,number,number];size:number}){
  const texture=useMemo(()=>{
    const canvas=document.createElement('canvas');canvas.width=128;canvas.height=128;
    const ctx=canvas.getContext('2d')!;ctx.font='bold 86px sans-serif';ctx.textAlign='center';ctx.textBaseline='middle';
    ctx.lineWidth=9;ctx.strokeStyle='#082438';ctx.strokeText(text,64,66);ctx.fillStyle='#e8f6ff';ctx.fillText(text,64,66);
    const texture=new THREE.CanvasTexture(canvas);texture.colorSpace=THREE.SRGBColorSpace;return texture;
  },[text]);
  useEffect(()=>()=>texture.dispose(),[texture]);
  return <sprite position={position} scale={[size,size,1]} raycast={()=>{}}><spriteMaterial map={texture} transparent depthWrite={false}/></sprite>;
}
export default function SeaOrientation({coords,bounds}:{coords:any;bounds:{minX:number;maxX:number;minY:number;maxY:number}}){
  const orientation=useMemo(()=>seaOrientation(coords,bounds),[coords,bounds.minX,bounds.maxX,bounds.minY,bounds.maxY]);
  const texture=useLoader(THREE.TextureLoader,boatUrl);
  texture.colorSpace=THREE.SRGBColorSpace;
  const geometry=useMemo(()=>{
    const g=new THREE.BufferGeometry();
    if(orientation){g.setAttribute('position',new THREE.Float32BufferAttribute(orientation.boat.flatMap(p=>[p[0],.015,p[1]]),3));g.setAttribute('uv',new THREE.Float32BufferAttribute([0,0,1,0,1,1,0,1],2));g.setIndex([0,2,1,0,3,2]);}
    return g;
  },[orientation]);
  useEffect(()=>()=>geometry.dispose(),[geometry]);
  if(!orientation)return null;
  const labelSize=Math.max(.6,Math.min(10,Math.max(bounds.maxX-bounds.minX,bounds.maxY-bounds.minY)*.025));
  return <group>
    {orientation.labels.map(p=><CompassLabel key={p.label} text={p.label} position={[p.x,.04,p.y]} size={labelSize}/>)}
    <mesh geometry={geometry} raycast={()=>{}} renderOrder={7}><meshBasicMaterial map={texture} transparent alphaTest={.05} side={THREE.DoubleSide} depthWrite={false}/></mesh>
  </group>;
}
