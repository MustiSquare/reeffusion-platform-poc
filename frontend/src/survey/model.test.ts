import { describe, expect, it } from 'vitest';
import { Replay, canProcess, contours, converter, snapshot, needsProcessing } from './model';

const replay:Replay={id:'test',name:'test',started_at:'2026-07-10T20:00:00Z',duration:10,crs:'EPSG:32605',point_count:3,warnings:[],reduction:'test',frames:[
  {t:0,boat:[-155.9,20.18,90,0,0],points:[[49,1,-2,-155.9,20.18,2],[50,1,-4,-155.9,20.18,1]]},
  {t:10,boat:[-155.9,20.18,180,0,0],points:[[49,1,-8,-155.9,20.18,1]]},
]};
describe('survey replay snapshots',()=>{
  it('flushes all usable partial blocks and even small revisions at end of recording',()=>{
    const b={key:'0:0',column:0,row:0,coverage:.04,last:5,samples:101,points:[[0,0,-1,0,0,1],[1,0,-1,0,0,1],[0,1,-1,0,0,1],[1,1,-1,0,0,1]] as any};
    expect(needsProcessing(b,undefined,9,10)).toBe(false);
    expect(needsProcessing(b,undefined,10,10)).toBe(true);
    expect(needsProcessing(b,{status:'completed',samples:100},10,10)).toBe(true);
    expect(needsProcessing(b,{status:'completed',samples:101},10,10)).toBe(false);
    expect(needsProcessing(b,{status:'failed',samples:101},10,10)).toBe(false);
    expect(needsProcessing({...b,points:b.points.slice(0,2)},undefined,10,10)).toBe(false);
  });
  it('does not leak future measurements or boat positions',()=>{
    const s=snapshot(replay,0,50);expect(s.boat?.[2]).toBe(90);expect(s.blocks).toHaveLength(2);expect(s.blocks[0].points[0][2]).toBe(-2);
    expect(snapshot(replay,10,50).blocks[0].points[0][2]).toBe(-4);
    expect(snapshot(replay,0,50).blocks[0].points[0][2]).toBe(-2);
  });
  it('uses fixed grid boundaries and occupied-cell coverage',()=>{
    const s=snapshot(replay,0,50);expect(s.blocks.map(b=>b.column)).toEqual([0,1]);expect(s.blocks[0].coverage).toBe(.01);expect(canProcess(s.blocks[0])).toBe(false);
  });
  it('round trips UTM metre coordinates',()=>{
    const p=converter('EPSG:32605'),utm=p.inverse([-155.9,20.18]),ll=p.forward(utm);
    expect(ll[0]).toBeCloseTo(-155.9,6);expect(ll[1]).toBeCloseTo(20.18,6);
  });
  it('does not draw contours across missing measurements',()=>{
    expect(contours(replay.frames.flatMap(f=>f.points))).toEqual([]);
  });
});
