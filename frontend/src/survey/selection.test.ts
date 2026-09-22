import { describe, expect, it } from 'vitest';
import { Group, Vector3 } from 'three';
import { tilePlacement, toggleCell } from './selection';

describe('multi-cell reef selection',()=>{
  it('caps selection at 20, permits deselection and ignores unfinished cells',()=>{
    let keys:string[]=[];
    for(let i=0;i<21;i++)keys=toggleCell(keys,String(i),true);
    expect(keys).toHaveLength(20);expect(keys).not.toContain('20');
    expect(toggleCell(keys,'unfinished',false)).toBe(keys);
    keys=toggleCell(keys,'3',true);expect(keys).toHaveLength(19);
    keys=toggleCell(keys,'20',true);expect(keys).toHaveLength(20);expect(keys).toContain('20');
  });
  it('aligns adjoining tiles exactly without retaining large world coordinates',()=>{
    const coordinates={projected_crs:'EPSG:32605',projected_origin:[196500,2234500],vertical_datum:'vehicle_origin_uncorrected'};
    const first=tilePlacement(coordinates);
    const next=tilePlacement({...coordinates,projected_origin:[196550,2234550]},first.anchor);
    expect(next.position).toEqual([50,0,-50]);
    const tile=new Group();tile.rotation.x=-Math.PI/2;tile.position.set(...next.position);tile.updateMatrixWorld();
    const vertex=tile.localToWorld(new Vector3(3,4,-12));
    expect(vertex.x).toBeCloseTo(53);expect(vertex.y).toBeCloseTo(-12);expect(vertex.z).toBeCloseTo(-54);
  });
  it('rejects missing placement and incompatible projections or depth references',()=>{
    const c={projected_crs:'EPSG:32605',projected_origin:[0,0],vertical_datum:'vehicle_origin_uncorrected'};
    expect(()=>tilePlacement({})).toThrow();
    expect(()=>tilePlacement({...c,projected_crs:'EPSG:32606'},tilePlacement(c).anchor)).toThrow('incompatible');
    expect(()=>tilePlacement({...c,vertical_datum:'MSL'},tilePlacement(c).anchor)).toThrow('incompatible');
  });
});
