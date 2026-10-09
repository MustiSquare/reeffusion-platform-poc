import {expect,it} from 'vitest';
import {BufferGeometry,Float32BufferAttribute,DoubleSide,Mesh,Raycaster,Vector3,Matrix4} from 'three';
import {orientBathymetryUp,matteSurfaceMaterial,colourSurfaceDepth} from './surfaceAppearance';
import {turboColour,depthColour} from './depthPalette';
import {applyDisplayMatrix,reefFromWorld} from './viewerOrientation';

it('corrects downward and mixed bathymetry faces without moving any measurements',()=>{
  const g=new BufferGeometry();g.setAttribute('position',new Float32BufferAttribute([0,0,-5,1,0,-5,0,1,-5,1,1,-5],3));
  g.setIndex([0,2,1,1,3,2]);const before=Array.from(g.getAttribute('position').array);
  orientBathymetryUp(g);
  expect(Array.from(g.getAttribute('position').array)).toEqual(before);
  expect(Array.from(g.index!.array)).toEqual([0,1,2,1,3,2]);
  for(let i=0;i<4;i++)expect(g.getAttribute('normal').getZ(i)).toBeCloseTo(1);
  g.dispose();
});

it('keeps the transformed surface visible and pickable from above and below',()=>{
  const g=new BufferGeometry();g.setAttribute('position',new Float32BufferAttribute([0,0,-5,0,1,-5,1,0,-5],3));
  orientBathymetryUp(g);applyDisplayMatrix(g,new Matrix4().set(1,0,0,0,0,0,.52,0,0,1,0,0,0,0,0,1));
  const material=matteSurfaceMaterial();expect(material.side).toBe(DoubleSide);expect(material.metalness).toBe(0);expect(material.transparent).toBe(false);
  const mesh=new Mesh(g,material);mesh.scale.z=-1;mesh.updateMatrixWorld();
  for(const y of [-10,10]){
    const hits=new Raycaster(new Vector3(.2,y,-.2),new Vector3(0,y<0?1:-1,0)).intersectObject(mesh);
    expect(hits).toHaveLength(1);expect(reefFromWorld(hits[0].point,.52,-1).z).toBeCloseTo(-5);
  }
  g.dispose();material.dispose();
});

it('shares raw-point depth colours and ignores vertical exaggeration',()=>{
  expect(depthColour(-20,[-20,0])).toEqual(turboColour(0));
  expect(depthColour(0,[-20,0])).toEqual(turboColour(1));
  const a=new BufferGeometry();a.setAttribute('position',new Float32BufferAttribute([0,0,-20,1,0,-10,0,1,0],3));
  const b=a.clone();applyDisplayMatrix(b,new Matrix4().set(1,0,0,0,0,0,.52,0,0,1,0,0,0,0,0,1));
  colourSurfaceDepth(a,[-20,0]);colourSurfaceDepth(b,[-20,0],'y',.52);
  const expected=a.getAttribute('color'),actual=b.getAttribute('color');
  for(let i=0;i<actual.array.length;i++)expect(actual.array[i]).toBeCloseTo(expected.array[i],6);
  expect(depthColour(-30,[-20,0])).toEqual(turboColour(0));
  const material=matteSurfaceMaterial(true);expect(material.vertexColors).toBe(true);expect(material.color.getHexString()).toBe('ffffff');
  a.dispose();b.dispose();material.dispose();
});
