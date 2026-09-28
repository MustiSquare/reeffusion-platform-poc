import * as THREE from 'three';
export function depthStep(raw:number){
  const base=10**Math.floor(Math.log10(Math.max(raw,1e-6)));
  return ([1,2,5,10].find(n=>n*base>=raw)||10)*base;
}
export function depthText(value:number){
  return `${Math.abs(value)<1e-8?'0':Number(value.toFixed(3)).toString().replace('-','−')} m`;
}
export function rulerLayout(camera:THREE.Camera,bounds:THREE.Box3,zScale:number,width:number,height:number){
  if(bounds.isEmpty()||zScale<=0||width<=0||height<=0)return null;
  const min=Math.min(0,bounds.min.y/zScale),max=Math.max(0,bounds.max.y/zScale);
  if(!Number.isFinite(min)||!Number.isFinite(max)||max-min<1e-6)return null;
  const direction=camera.getWorldDirection(new THREE.Vector3());
  const top=Math.abs(direction.y)>.985;
  const margin=Math.max(bounds.max.x-bounds.min.x,bounds.max.z-bounds.min.z)*.035;
  const project=(x:number,z:number,depth:number)=>{
    const point=new THREE.Vector3(x,depth*zScale,z).project(camera);
    return {x:(point.x+1)*width/2,y:(1-point.y)*height/2,visible:point.z>=-1&&point.z<=1&&Number.isFinite(point.x)&&Number.isFinite(point.y)};
  };
  const candidates=[bounds.min.x-margin,bounds.max.x+margin].flatMap(x=>[bounds.min.z-margin,bounds.max.z+margin].map(z=>({x,z,p:project(x,z,(min+max)/2)})));
  const anchor=candidates.filter(c=>c.p.visible).sort((a,b)=>a.p.x-b.p.x)[0];
  if(!anchor)return {min,max,top,project:null,ticks:[],step:0};
  const at=(depth:number)=>project(anchor.x,anchor.z,depth);
  const a=at(min),b=at(max),pixels=Math.hypot(a.x-b.x,a.y-b.y);
  const step=depthStep(Math.max((max-min)*44/Math.max(1,pixels),(max-min)/400));
  const ticks:number[]=[];
  for(let i=Math.ceil(min/step);i<=Math.floor(max/step);i++)ticks.push(Number((i*step).toPrecision(12)));
  return {min,max,top,project:at,ticks,step};
}
