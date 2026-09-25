import {expect,it} from 'vitest';
import {mapDisplayBlocks,MAX_MAP_POINTS} from './mapDisplay';
import {Block,Point} from './model';
it('bounds a full survey map preview without dropping cells or changing processing data',()=>{
  const blocks:Block[]=Array.from({length:50},(_,i)=>({key:`${i}:0`,column:i,row:0,last:100,samples:6000,coverage:1,points:Array.from({length:6000},(_,j)=>[i*50,j,-2,0,0,1] as Point)}));
  const result=mapDisplayBlocks(blocks);
  expect(result).toHaveLength(50);
  expect(result.reduce((n,b)=>n+b.points.length,0)).toBeLessThanOrEqual(MAX_MAP_POINTS);
  expect(result.every(b=>b.points.length>0)).toBe(true);
  expect(blocks.reduce((n,b)=>n+b.points.length,0)).toBe(300000);
  expect(result[0].samples).toBe(6000);
});
