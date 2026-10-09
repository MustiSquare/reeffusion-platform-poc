import {describe,it,expect} from 'vitest';
import {prepareRawBuffer,intersects,RawChunk} from './rawPointData';
describe('raw point buffers',()=>{
  it('keeps repeated detections and negative depths while swapping display axes',()=>{
    const a=new Float32Array([1,2,-4,1,2,-4,3,5,-6]);
    expect([...prepareRawBuffer(a.buffer,[500000,2200000,0])]).toEqual([1,-4,2,1,-4,2,3,-6,5]);
  });
  it('includes rectangle boundaries without including outside detections',()=>{
    const a=new Float32Array([0,0,-1,25,25,-2,25.1,25,-3,0,0,-1]);
    expect([...prepareRawBuffer(a.buffer,[500000,2200000,0],[500000,2200000,500025,2200025])]).toEqual([0,-1,0,25,-2,25,0,-1,0]);
  });
  it('uses inclusive tile bounds for selected-area loading',()=>{
    const c={min:[0,0,-5],max:[25,25,-1]} as RawChunk;
    expect(intersects(c,[25,25,50,50])).toBe(true);
    expect(intersects(c,[26,26,50,50])).toBe(false);
  });
});
