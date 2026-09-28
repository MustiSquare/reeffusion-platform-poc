import {expect,it} from 'vitest';
import {Box3,PerspectiveCamera,Vector3} from 'three';
import {depthStep,depthText,rulerLayout} from './depthRulerMath';
const bounds=(scale=1)=>new Box3(new Vector3(0,-30*scale,0),new Vector3(50,-10*scale,50));
function camera(distance=100,top=false){
  const c=new PerspectiveCamera(55,1,0.1,10000);
  c.position.set(25,top?distance:-10,top?25.001:25+distance);c.lookAt(25,-10,25);c.updateMatrixWorld();return c;
}
it('uses readable metre steps and negative elevations',()=>{
  expect([.13,.7,1.1,2.1,5.1].map(depthStep)).toEqual([.2,1,2,5,10]);
  expect(depthText(-18)).toBe('−18 m');expect(depthText(-0)).toBe('0 m');
});
it('adapts tick spacing to camera distance without changing physical depths',()=>{
  const far=rulerLayout(camera(200),bounds(),1,800,800)!;
  const near=rulerLayout(camera(45),bounds(),1,800,800)!;
  expect(near.step).toBeLessThan(far.step);
  expect(near.min).toBe(-30);expect(far.min).toBe(-30);expect(near.max).toBe(0);
  expect(near.project!(-18).y).toBeGreaterThan(near.project!(0).y);
});
it('keeps metre values independent of vertical exaggeration',()=>{
  const normal=rulerLayout(camera(),bounds(),1,800,800)!;
  const exaggerated=rulerLayout(camera(),bounds(1.4),1.4,800,800)!;
  expect(exaggerated.min).toBeCloseTo(normal.min,10);
  expect(exaggerated.project!(-18).y).not.toBe(normal.project!(-18).y);
});
it('uses range mode for top views and rejects empty geometry',()=>{
  expect(rulerLayout(camera(100,true),bounds(),1,800,800)!.top).toBe(true);
  expect(rulerLayout(camera(),new Box3(),1,800,800)).toBeNull();
});
