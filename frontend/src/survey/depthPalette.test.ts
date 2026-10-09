import {expect,it} from 'vitest';
import {depthColour,turboColour} from './depthPalette';

it('covers blue, green and red across the full depth range',()=>{
  const blue=turboColour(.15),green=turboColour(.5),red=turboColour(.85);
  expect(blue[2]).toBeGreaterThan(blue[0]);expect(blue[2]).toBeGreaterThan(blue[1]);
  expect(green[1]).toBeGreaterThan(green[0]);expect(green[1]).toBeGreaterThan(green[2]);
  expect(red[0]).toBeGreaterThan(red[1]);expect(red[0]).toBeGreaterThan(red[2]);
  for(let i=0;i<=100;i++)for(const c of turboColour(i/100)){expect(c).toBeGreaterThanOrEqual(0);expect(c).toBeLessThanOrEqual(1);}
});
it('clamps out-of-range depths and handles flat surveys',()=>{
  expect(depthColour(-100,[-20,0])).toEqual(turboColour(0));
  expect(depthColour(100,[-20,0])).toEqual(turboColour(1));
  expect(depthColour(-5,[-5,-5])).toEqual(turboColour(0));
});
