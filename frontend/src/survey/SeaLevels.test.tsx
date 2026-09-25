import {afterEach,expect,it} from 'vitest';
import {cleanup,fireEvent,render,screen} from '@testing-library/react';
import '@testing-library/jest-dom/vitest';
import {Sounding,referenceHeight,referenceHeights,referenceTopology,nearestSounding,SeaLevelControls,SeaLevelReadout,useSeaLevels} from './SeaLevels';
afterEach(()=>{cleanup();localStorage.clear();});
it('uses sea level Z=0 and places MSL below it by the supplied offset',()=>{
  expect(referenceHeights(3)).toEqual({blue:0,yellow:-3});
  expect(referenceHeights(2)).toEqual({blue:0,yellow:-2});
  expect(referenceHeights(null)).toEqual({blue:0,yellow:null});
  expect(referenceHeight('')).toBeNull();expect(referenceHeight('0')).toBe(0);
});
it('spans gaps with flat reference surfaces without changing seabed soundings',()=>{
  const points:Sounding[]=[[0,0,-20,18],[1,0,-21,19],[0,1,-19,17],[1,1,-20,18],[20,20,-30,28]];
  const topology=referenceTopology(points);
  expect(topology.faces).toEqual([0,1,2,0,2,3]);
  expect(topology.positions.slice(0,4)).toEqual([[0,0],[20,0],[20,20],[0,20]]);
  expect(points[4]).toEqual([20,20,-30,28]);
  const large=referenceTopology([[0,0,-18,18],[100000,100000,-18,18]]);
  expect(large.positions.length).toBeLessThan(210);
  expect(referenceTopology([]).faces).toEqual([]);
  expect(nearestSounding(points,{x:100,y:100})).toBeNull();
  expect(nearestSounding(points,{x:.1,y:.1})).toEqual(points[0]);
});
function Harness({id}:{id:string}){const [levels,update]=useSeaLevels(id);return <><SeaLevelControls levels={levels} update={update} status="Recorded" count={1}/><SeaLevelReadout levels={levels} point={[0,0,-18,18]}/></>;}
it('defaults to the approved 3 m offset and shows MSL 15 m above a -18 m seabed',()=>{
  localStorage.setItem('reef-sounding-levels-v2:a',JSON.stringify({offset:'-18',draft:'20'}));
  const {rerender}=render(<Harness id="a"/>);
  expect(screen.getByLabelText('MSL below sea level')).toHaveValue(3);
  expect(screen.getByText('Blue sea level: Z = 0.00 m')).toBeInTheDocument();
  expect(screen.getByText('Blue height above point: 18.00 m')).toBeInTheDocument();
  expect(screen.getByText('MSL Z: -3.00 m')).toBeInTheDocument();
  expect(screen.getByText('MSL height above point: 15.00 m')).toBeInTheDocument();
  fireEvent.change(screen.getByLabelText('MSL below sea level'),{target:{value:'2'}});
  expect(screen.getByText('MSL height above point: 16.00 m')).toBeInTheDocument();
  rerender(<Harness id="b"/>);expect(screen.getByLabelText('MSL below sea level')).toHaveValue(3);
  rerender(<Harness id="a"/>);expect(screen.getByLabelText('MSL below sea level')).toHaveValue(2);
});
