import {BufferGeometry,DoubleSide,Float32BufferAttribute,MeshStandardMaterial} from 'three';
import {depthColour} from './depthPalette';

export function colourSurfaceDepth(geometry:BufferGeometry,range:readonly number[],axis:'y'|'z'='z',scale=1){
  const p=geometry.getAttribute('position'),colours=new Float32Array(p.count*3);
  for(let i=0;i<p.count;i++)colours.set(depthColour((axis==='z'?p.getZ(i):p.getY(i))/scale,range),i*3);
  geometry.setAttribute('color',new Float32BufferAttribute(colours,3));
}

/** Bathymetry is a height field in source XYZ. Orient its top toward +Z. */
export function orientBathymetryUp(geometry:BufferGeometry){
  const p=geometry.getAttribute('position');
  if(!geometry.index)geometry.setIndex(Array.from({length:p.count},(_,i)=>i));
  const indices=geometry.index!;
  for(let i=0;i+2<indices.count;i+=3){
    const a=indices.getX(i),b=indices.getX(i+1),c=indices.getX(i+2);
    const nz=(p.getX(b)-p.getX(a))*(p.getY(c)-p.getY(a))-(p.getY(b)-p.getY(a))*(p.getX(c)-p.getX(a));
    if(nz<0){indices.setX(i+1,c);indices.setX(i+2,b);}
  }
  indices.needsUpdate=true;
  geometry.computeVertexNormals();
}

export function matteSurfaceMaterial(depth=false){
  return new MeshStandardMaterial({color:depth?'#ffffff':'#526777',vertexColors:depth,metalness:0,roughness:.92,
    side:DoubleSide,transparent:false,emissive:depth?'#000000':'#101820',emissiveIntensity:.2});
}
