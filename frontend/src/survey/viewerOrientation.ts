import {BufferGeometry,Matrix4,Vector3} from 'three';

/** Keep front faces and picking consistent when baking an axis reflection. */
export function applyDisplayMatrix(geometry:BufferGeometry,matrix:Matrix4){
  geometry.applyMatrix4(matrix);
  if(matrix.determinant()<0){
    if(!geometry.index)geometry.setIndex(Array.from({length:geometry.getAttribute('position').count},(_,i)=>i));
    const indices=geometry.index!;
    for(let i=0;i+2<indices.count;i+=3){
      const b=indices.getX(i+1);indices.setX(i+1,indices.getX(i+2));indices.setX(i+2,b);
    }
    indices.needsUpdate=true;
  }
}

/** With east=X and elevation=Y, geographic north must be -Z in Three.js. */
export function northView(north:readonly number[],preset:string){
  const south=new Vector3(-north[0],0,north[1]);
  if(preset==='top')return south.multiplyScalar(.0001).add(new Vector3(0,1,0)).normalize();
  if(preset==='side')return new Vector3(north[1],0,north[0]);
  if(preset==='front')return south;
  return south.multiplyScalar(7).add(new Vector3(0,4,0)).normalize();
}

export function northAzimuth(north:readonly number[]){
  return Math.atan2(-north[0],north[1]);
}

/** Undo the display-only axis conversion when saving picks or measuring. */
export function reefFromWorld(point:{x:number;y:number;z:number},zScale:number,northSign:number){
  return {x:point.x,y:point.z*northSign,z:point.y/zScale};
}
