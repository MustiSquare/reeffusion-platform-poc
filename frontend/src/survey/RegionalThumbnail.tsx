import {useEffect,useRef,useState} from 'react';
import L from 'leaflet';
import {converter} from './model';
import {Area,thumbnailMembers} from './archiveAreas';
export default function RegionalThumbnail({area,members}:{area:Area|null;members:Area[]}){
  const host=useRef<HTMLDivElement>(null),[visible,setVisible]=useState(false);
  const key=JSON.stringify([area,members.map(m=>m.id).sort()]);
  useEffect(()=>{
    if(!host.current)return;
    if(typeof IntersectionObserver==='undefined'){setVisible(true);return;}
    const observer=new IntersectionObserver(entries=>{if(entries.some(e=>e.isIntersecting)){setVisible(true);observer.disconnect();}});
    observer.observe(host.current);return()=>observer.disconnect();
  },[]);
  useEffect(()=>{
    if(!host.current||!area||!visible)return;
    const map=L.map(host.current,{preferCanvas:true,zoomControl:false,attributionControl:true,dragging:false,scrollWheelZoom:false,doubleClickZoom:false,boxZoom:false,keyboard:false,touchZoom:false});
    map.attributionControl.setPrefix(false);
    L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png',{attribution:'© OpenStreetMap',maxZoom:19}).addTo(map);
    const project=converter(area.crs),x=area.block_column*100000,y=area.block_row*100000;
    const ll=(e:number,n:number):L.LatLngTuple=>{const [lon,lat]=project.forward([e,n]);return [lat,lon];};
    map.fitBounds(L.latLngBounds([ll(x,y),ll(x+100000,y),ll(x+100000,y+100000),ll(x,y+100000)]),{padding:[3,3]});
    const selected=new Set(thumbnailMembers(area,members).map(m=>`${m.column}:${m.row}`));
    for(let i=0;i<10;i++)for(let j=0;j<10;j++){
      const e=x+i*10000,n=y+j*10000,hit=selected.has(`${area.block_column*10+i}:${area.block_row*10+j}`);
      L.polygon([ll(e,n),ll(e+10000,n),ll(e+10000,n+10000),ll(e,n+10000)],{color:'#365577',weight:.65,fillColor:'#ffe133',fillOpacity:hit?.65:0,interactive:false}).addTo(map);
    }
    const resize=new ResizeObserver(()=>{map.invalidateSize();});resize.observe(host.current);
    return()=>{resize.disconnect();map.remove();};
  },[key,visible]);
  const outside=area&&members.some(m=>!thumbnailMembers(area,[m]).length);
  return <div className="regional-thumbnail"><div ref={host} className="regional-thumbnail-map" role="img" aria-label={area?'100 km regional map; yellow squares show survey coverage':'Regional location unavailable'}/><small>{area?'100 × 100 km · 10 km squares · N ↑':'Location unavailable'}{outside?' · extends beyond map':''}</small></div>;
}
