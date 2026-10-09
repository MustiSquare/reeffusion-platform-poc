import React from 'react';
import {afterEach,expect,it,vi} from 'vitest';
import {act,cleanup,fireEvent,render,renderHook,screen,waitFor} from '@testing-library/react';
import '@testing-library/jest-dom/vitest';
import {RawPointControls,useRawPoints} from './RawPoints';
import {prepareRawBuffer} from './rawPointData';
import {referenceTopology,referenceHeights} from './SeaLevels';
const api=vi.hoisted(()=>({get:vi.fn(),post:vi.fn()}));
vi.mock('../api/client',()=>({getJson:api.get,postJson:api.post,assetUrl:(s:string)=>s}));
afterEach(()=>{cleanup();vi.unstubAllGlobals();vi.resetAllMocks();});
const chunk={id:'0-0',origin:[500000,2200000,-10],min:[500000,2200000,-10],max:[500025,2200025,-1],count:3,bytes:36};
const manifest={point_count:3,overview_count:3,overview:[{...chunk,id:'0-overview-0'}],chunks:[chunk],min:chunk.min,max:chunk.max,crs:'EPSG:32605',partial:true,warnings:['Damaged recording']};
const dataset={id:'reef',coordinate_system:{projected_crs:'EPSG:32605'}};
function setup(){
  api.get.mockImplementation(async(path:string)=>path.endsWith('raw-point-source')?{survey_id:'survey',areas:[[500000,2200000,500025,2200025]]}:path.endsWith('manifest')?manifest:{status:'completed'});
  vi.stubGlobal('Worker',class{
    onmessage:any;terminate=vi.fn();
    postMessage({id,buffer,origin,area,areas}:any){queueMicrotask(()=>this.onmessage?.({data:{id,positions:prepareRawBuffer(buffer,origin,area,areas)}}));}
  });
  vi.stubGlobal('fetch',vi.fn(async()=>({ok:true,arrayBuffer:async()=>new Float32Array([1,2,0,1,2,0,25,25,9]).buffer})));
}
it('reads the shared depth range without downloading raw points when the layer is off',async()=>{
  setup();const {result}=renderHook(()=>useRawPoints(dataset));
  await waitFor(()=>expect(result.current.manifest?.min[2]).toBe(-10));
  expect(result.current.enabled).toBe(false);expect(fetch).not.toHaveBeenCalled();
});
it('loads real buffers, preserves repeats and explicitly labels reduced versus full detail',async()=>{
  setup();const {result}=renderHook(()=>useRawPoints(dataset));
  await waitFor(()=>expect(result.current.source?.survey_id).toBe('survey'));
  act(()=>result.current.setEnabled(true));
  await waitFor(()=>expect(result.current.progress.complete).toBe(true));
  expect(result.current.progress.points).toBe(3);
  expect([...result.current.chunks[0].positions]).toEqual([1,0,2,1,0,2,25,9,25]);
  const controls=render(<RawPointControls raw={result.current} onEnable={()=>{}} onSelect={()=>{}}/>);
  expect(screen.getByText(/Reduced overview · 3 points loaded/)).toBeInTheDocument();
  expect(screen.getByText(/Partial recording: Damaged recording/)).toBeInTheDocument();
  act(()=>{result.current.setArea([500000,2200000,500002,2200003]);});
  act(()=>result.current.load('area'));
  await waitFor(()=>expect(result.current.progress.points).toBe(2));
  expect(result.current.progress.complete).toBe(true);
  controls.rerender(<RawPointControls raw={result.current} onEnable={()=>{}} onSelect={()=>{}}/>);
  expect(screen.getByText(/Full detail · 2 points loaded/)).toBeInTheDocument();
  act(()=>result.current.load('all'));
  await waitFor(()=>expect(result.current.progress.points).toBe(3));
});
it('clips overview and full detail to separate selected cells and skips outside chunks',async()=>{
  setup();
  const outside={...chunk,id:'outside',min:[500050,2200000,-10],max:[500075,2200025,-1]};
  api.get.mockImplementation(async(path:string)=>path.endsWith('raw-point-source')?
    {survey_id:'survey',areas:[[500000,2200000,500002,2200003],[500020,2200020,500025,2200025]]}:
    path.endsWith('manifest')?{...manifest,overview:[...manifest.overview,outside],chunks:[chunk,outside]}:{status:'completed'});
  vi.stubGlobal('fetch',vi.fn(async()=>({ok:true,arrayBuffer:async()=>new Float32Array([1,2,0,10,10,4,25,25,9]).buffer})));
  const {result}=renderHook(()=>useRawPoints(dataset));
  await waitFor(()=>expect(result.current.manifest).not.toBeNull());
  act(()=>result.current.setEnabled(true));
  await waitFor(()=>expect(result.current.progress.complete).toBe(true));
  expect(result.current.progress.points).toBe(2);
  expect(result.current.progress.total).toBe(1);
  expect([...result.current.chunks[0].positions]).toEqual([1,0,2,25,9,25]);
  act(()=>result.current.load('all'));
  await waitFor(()=>expect(result.current.chunks[0]?.id).toBe(chunk.id));
  expect(result.current.progress.points).toBe(2);
  expect(result.current.cellBounds).toEqual([500000,2200000,500025,2200025]);
  expect(vi.mocked(fetch).mock.calls.every(([url])=>!String(url).includes('outside'))).toBe(true);
});
it('cancels incomplete loads and releases the layer on disable',async()=>{
  setup();vi.stubGlobal('fetch',vi.fn(()=>new Promise(()=>{})));
  const {result}=renderHook(()=>useRawPoints(dataset));
  await waitFor(()=>expect(result.current.source?.survey_id).toBe('survey'));
  act(()=>result.current.setEnabled(true));
  await waitFor(()=>expect(fetch).toHaveBeenCalled());
  act(()=>result.current.cancel());
  expect(result.current.stopped).toBe(true);expect(result.current.progress.complete).toBe(false);
  act(()=>result.current.setEnabled(false));expect(result.current.chunks).toHaveLength(0);
});
it('reports failed chunks as incomplete and supports retry',async()=>{
  setup();vi.stubGlobal('fetch',vi.fn(async()=>({ok:false})));
  const {result}=renderHook(()=>useRawPoints(dataset));
  await waitFor(()=>expect(result.current.source?.survey_id).toBe('survey'));
  act(()=>result.current.setEnabled(true));
  await waitFor(()=>expect(result.current.error).toContain('Loading incomplete'));
  expect(result.current.progress.complete).toBe(false);
  vi.stubGlobal('fetch',vi.fn(async()=>({ok:true,arrayBuffer:async()=>new Float32Array(9).buffer})));
  act(()=>result.current.load('overview'));
  await waitFor(()=>expect(result.current.progress.complete).toBe(true));
});
it('keeps reference planes available over a raw footprint without surface soundings',()=>{
  const topology=referenceTopology([],{minX:0,minY:0,maxX:250,maxY:150});
  expect(topology.positions.slice(0,4)).toEqual([[0,0],[250,0],[250,150],[0,150]]);
  expect(topology.faces).toHaveLength(6);
  expect(referenceHeights(3)).toEqual({blue:0,yellow:-3});
  expect(referenceHeights(null).yellow).toBeNull();
});
