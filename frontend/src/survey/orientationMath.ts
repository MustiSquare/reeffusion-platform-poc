import {converter} from './model';
export const BLUEBOAT_LENGTH_M=1.20;
export const BLUEBOAT_WIDTH_M=.93;
export function seaOrientation(coords:any,bounds:{minX:number;maxX:number;minY:number;maxY:number}){
  const crs=coords?.projected_crs,origin=coords?.projected_origin;
  if(!/^EPSG:32[67](0[1-9]|[1-5][0-9]|60)$/.test(crs||'')||!Array.isArray(origin)||origin.length!==2||!origin.every(Number.isFinite))return null;
  try{
    const centre:[number,number]=[(bounds.minX+bounds.maxX)/2,(bounds.minY+bounds.maxY)/2];
    const project=converter(crs),global=[centre[0]+origin[0],centre[1]+origin[1]];
    const [lon,lat]=project.forward(global),q=project.inverse([lon,lat+.0001]);
    const length=Math.hypot(q[0]-global[0],q[1]-global[1]);
    if(!Number.isFinite(length)||length===0)return null;
    const north:[number,number]=[(q[0]-global[0])/length,(q[1]-global[1])/length];
    const east:[number,number]=[north[1],-north[0]];
    const halfX=(bounds.maxX-bounds.minX)/2,halfY=(bounds.maxY-bounds.minY)/2;
    const labels=([['N',north],['E',east],['S',north.map(v=>-v)],['W',east.map(v=>-v)]] as [string,number[]][]).map(([label,d])=>{
      const reach=Math.min(Math.abs(d[0])>1e-12?halfX/Math.abs(d[0]):Infinity,Math.abs(d[1])>1e-12?halfY/Math.abs(d[1]):Infinity);
      return {label,x:centre[0]+d[0]*reach,y:centre[1]+d[1]*reach};
    });
    const boat=([[-1,-1],[1,-1],[1,1],[-1,1]]).map(([e,n])=>[centre[0]+east[0]*e*BLUEBOAT_WIDTH_M/2+north[0]*n*BLUEBOAT_LENGTH_M/2,centre[1]+east[1]*e*BLUEBOAT_WIDTH_M/2+north[1]*n*BLUEBOAT_LENGTH_M/2]);
    return {centre,north,east,labels,boat};
  }catch{return null;}
}
