import {useEffect,useRef} from 'react';
import {useFrame,useThree} from '@react-three/fiber';
import * as THREE from 'three';
import {depthText,rulerLayout} from './depthRulerMath';

// Screen-sized labels projected from a real vertical metre axis beside the reef.
// This overlay cannot intercept picking, orbiting or zooming.
export default function DepthRuler({bounds,zScale,msl,picked,theme}:{bounds:THREE.Box3;zScale:number;msl:number|null;picked:number|null;theme:string}){
  const {gl,camera,size}=useThree();
  const overlay=useRef<SVGSVGElement|null>(null),previous=useRef('');
  useEffect(()=>{
    const svg=document.createElementNS('http://www.w3.org/2000/svg','svg');
    svg.setAttribute('aria-label','Depth ruler in metres relative to blue sea level');svg.setAttribute('role','img');
    Object.assign(svg.style,{position:'absolute',inset:'0',width:'100%',height:'100%',pointerEvents:'none',overflow:'hidden',zIndex:'2'});
    gl.domElement.parentElement?.appendChild(svg);overlay.current=svg;previous.current='';
    return()=>{svg.remove();overlay.current=null;};
  },[gl]);
  useFrame(()=>{
    const svg=overlay.current;if(!svg)return;
    camera.updateMatrixWorld();
    const key=[...camera.matrixWorld.elements,...camera.projectionMatrix.elements,...bounds.min.toArray(),...bounds.max.toArray(),zScale,msl,picked,theme,size.width,size.height].join(',');
    if(key===previous.current)return;previous.current=key;
    const layout=rulerLayout(camera,bounds,zScale,size.width,size.height);
    if(!layout){svg.innerHTML='';return;}
    const light=theme==='light',ink=light?'#17384a':'#e7f3fc',back=light?'#f5fafc':'#071925';
    const blue=light?'#0963b5':'#62b6ff',yellow=light?'#806000':'#ffe133',pink=light?'#a21b69':'#ff8dcc';
    const text=(x:number,y:number,label:string,color=ink,anchor='start')=>`<text x="${x}" y="${y}" text-anchor="${anchor}" dominant-baseline="middle" fill="${color}" stroke="${back}" stroke-width="3" paint-order="stroke" font-family="system-ui,sans-serif" font-size="12">${label}</text>`;
    const line=(x1:number,y1:number,x2:number,y2:number,color=ink)=>`<line x1="${x1}" y1="${y1}" x2="${x2}" y2="${y2}" stroke="${color}" stroke-width="1.5"/>`;
    const summary=()=>{
      const labels=[['Depth / Z (m)',ink],[`Reef: ${depthText(layout.min)} to ${depthText(bounds.max.y/zScale)}`,ink],['Sea level: 0 m',blue],...(msl===null?[]:[[ `MSL: ${depthText(msl)}`,yellow]]),...(picked===null?[]:[[ `Selected: ${depthText(picked)}`,pink]])];
      return `<rect x="8" y="8" width="214" height="${labels.length*19+28}" rx="7" fill="${back}" fill-opacity=".88"/>`+labels.map(([label,color],i)=>text(18,23+i*19,label,color)).join('')+text(18,23+labels.length*19,layout.top?'Top view · depth range':'Depth axis outside view');
    };
    // Keep the ruler readable when zoom pushes the reef edge off screen.
    // Only its horizontal placement moves; projected depth heights stay exact.
    const sourceAt=layout.project,midpoint=sourceAt?.((layout.min+layout.max)/2);
    const shift=midpoint?Math.max(0,76-midpoint.x)+Math.min(0,size.width-76-midpoint.x):0;
    const at=sourceAt?(depth:number)=>{const p=sourceAt(depth);return {...p,x:p.x+shift};}:null;
    if(layout.top||!at){svg.innerHTML=summary();return;}
    const marks=[{depth:0,label:'0 m · Sea level',color:blue},...(msl===null?[]:[{depth:msl,label:`${depthText(msl)} · MSL`,color:yellow}]),...(picked===null?[]:[{depth:picked,label:`${depthText(picked)} · Selected`,color:pink}])];
    const visible=(p:ReturnType<typeof at>)=>p.visible&&p.x>8&&p.x<size.width-8&&p.y>36&&p.y<size.height-18;
    const visibleTicks=layout.ticks.map(depth=>({depth,p:at(depth)})).filter(t=>visible(t.p));
    const visibleMarks=marks.map(mark=>({...mark,p:at(mark.depth)})).filter(m=>visible(m.p));
    if(!visibleTicks.length&&!visibleMarks.length){svg.innerHTML=summary();return;}
    const a=at(layout.min),b=at(layout.max);
    let content=text(14,20,'Depth / Z (m)');
    if(a.visible&&b.visible)content+=line(a.x,a.y,b.x,b.y);
    const occupied:number[]=[];
    for(const mark of visibleMarks){
      content+=line(mark.p.x-5,mark.p.y,mark.p.x+7,mark.p.y,mark.color);
      let y=mark.p.y;while(occupied.some(v=>Math.abs(v-y)<17))y+=17;
      if(y>size.height-14)continue;occupied.push(y);
      const onRight=mark.p.x<155,x=mark.p.x+(onRight?11:-11);
      if(y!==mark.p.y)content+=line(mark.p.x,mark.p.y,x,y,mark.color);
      content+=text(x,y,mark.label,mark.color,onRight?'start':'end');
    }
    for(const {depth,p} of visibleTicks){
      if(marks.some(m=>Math.abs(m.depth-depth)<1e-8))continue;
      content+=line(p.x-4,p.y,p.x+4,p.y);
      if(occupied.some(v=>Math.abs(v-p.y)<17))continue;
      occupied.push(p.y);const right=p.x<72;
      content+=text(p.x+(right?9:-9),p.y,depthText(depth),ink,right?'start':'end');
    }
    svg.innerHTML=content;
  });
  return null;
}
