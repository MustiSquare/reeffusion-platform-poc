export type Area=[number,number,number,number];
export type RawChunk={id:string;count:number;origin:number[];min:number[];max:number[];bytes:number};
export type RawManifest={point_count:number;overview_count:number;chunks:RawChunk[];overview:RawChunk[];min:number[];max:number[];crs:string;partial:boolean;warnings:string[]};
export type LoadedChunk=RawChunk&{positions:Float32Array};
export function intersects(c:RawChunk,a:Area){return c.max[0]>=a[0]&&c.min[0]<=a[2]&&c.max[1]>=a[1]&&c.min[1]<=a[3];}
/** Filter before display conversion; preserve multiplicity and original depth. */
export function prepareRawBuffer(buffer:ArrayBuffer,origin:number[],area?:Area,areas?:Area[]){
  const points=new Float32Array(buffer);let count=0;
  for(let i=0;i<points.length;i+=3){
    const x=points[i],y=points[i+1],z=points[i+2];
    if(area&&(x+origin[0]<area[0]||x+origin[0]>area[2]||y+origin[1]<area[1]||y+origin[1]>area[3]))continue;
    if(areas&&!areas.some(a=>x+origin[0]>=a[0]&&x+origin[0]<=a[2]&&y+origin[1]>=a[1]&&y+origin[1]<=a[3]))continue;
    points[count++]=x;points[count++]=z;points[count++]=y;
  }
  return points.subarray(0,count);
}
