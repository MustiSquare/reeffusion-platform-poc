import {expect,it} from 'vitest';
import {BufferGeometry,Float32BufferAttribute,Matrix4,Mesh,MeshBasicMaterial,PerspectiveCamera,Raycaster,Vector3} from 'three';
import {seaOrientation} from './orientationMath';
import {applyDisplayMatrix,northAzimuth,northView,reefFromWorld} from './viewerOrientation';

for(const origin of [[500000,2200000],[200000,2200000]]){
  for(const preset of ['reset','top']){
    it(`shows true north up and east right in ${preset} at ${origin[0]}`,()=>{
      const o=seaOrientation({projected_crs:'EPSG:32605',projected_origin:origin},{minX:0,maxX:50,minY:0,maxY:50})!;
      const camera=new PerspectiveCamera(55,1,.01,1000);
      camera.position.copy(northView(o.north,preset)).multiplyScalar(100);camera.lookAt(0,0,0);camera.updateMatrixWorld();
      const north=new Vector3(o.north[0],0,-o.north[1]).project(camera);
      const east=new Vector3(o.east[0],0,-o.east[1]).project(camera);
      expect(north.y).toBeGreaterThan(0);expect(Math.abs(north.x)).toBeLessThan(1e-10);
      expect(east.x).toBeGreaterThan(0);expect(Math.abs(east.y)).toBeLessThan(1e-10);
      expect(Math.atan2(camera.position.x,camera.position.z)).toBeCloseTo(northAzimuth(o.north),10);
    });
  }
}

it('preserves stored annotation and measurement coordinates through display conversion',()=>{
  const original={x:12,y:34,z:-15};
  for(const scale of [.52,1,2]){
    expect(reefFromWorld({x:12,y:-15*scale,z:-34},scale,-1)).toEqual(original);
    expect(reefFromWorld({x:12,y:-15*scale,z:34},scale,1)).toEqual(original);
  }
});

for(const indexed of [true,false])it(`keeps reflected GLB surfaces front-facing and pickable (${indexed})`,()=>{
  const geometry=new BufferGeometry();
  geometry.setAttribute('position',new Float32BufferAttribute([0,0,-5,1,0,-5,0,1,-5],3));
  if(indexed)geometry.setIndex([0,1,2]);geometry.computeVertexNormals();
  applyDisplayMatrix(geometry,new Matrix4().set(1,0,0,0,0,0,.52,0,0,1,0,0,0,0,0,1));
  const mesh=new Mesh(geometry,new MeshBasicMaterial());mesh.scale.z=-1;mesh.updateMatrixWorld();
  const hits=new Raycaster(new Vector3(.2,10,-.2),new Vector3(0,-1,0)).intersectObject(mesh);
  expect(hits).toHaveLength(1);
  const point=reefFromWorld(hits[0].point,.52,-1);
  expect(point.x).toBeCloseTo(.2);expect(point.y).toBeCloseTo(.2);expect(point.z).toBeCloseTo(-5);
  geometry.dispose();(mesh.material as MeshBasicMaterial).dispose();
});
