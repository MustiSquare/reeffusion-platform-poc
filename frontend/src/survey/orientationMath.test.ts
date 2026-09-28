import {expect,it} from 'vitest';
import {seaOrientation,BLUEBOAT_LENGTH_M,BLUEBOAT_WIDTH_M} from './orientationMath';
const bounds={minX:0,maxX:50,minY:0,maxY:50};
it('places geographic directions correctly in a metric scene',()=>{
  const result=seaOrientation({projected_crs:'EPSG:32605',projected_origin:[500000,2200000]},bounds)!;
  expect(result.north[1]).toBeCloseTo(1,5);expect(result.east[0]).toBeCloseTo(1,5);
  expect(result.labels.find(p=>p.label==='N')!.y).toBe(50);
  expect(result.labels.find(p=>p.label==='E')!.x).toBe(50);
  expect(result.labels.find(p=>p.label==='S')!.y).toBeCloseTo(0,8);
  const distance=(a:number[],b:number[])=>Math.hypot(a[0]-b[0],a[1]-b[1]);
  expect(distance(result.boat[0],result.boat[1])).toBeCloseTo(BLUEBOAT_WIDTH_M,10);
  expect(distance(result.boat[1],result.boat[2])).toBeCloseTo(BLUEBOAT_LENGTH_M,10);
});
it('accounts for meridian convergence and does not invent a compass',()=>{
  const result=seaOrientation({projected_crs:'EPSG:32605',projected_origin:[200000,2200000]},bounds)!;
  expect(Math.abs(result.north[0])).toBeGreaterThan(.001);
  expect(seaOrientation({projected_crs:'LOCAL_GRID'},bounds)).toBeNull();
});
