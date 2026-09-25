import React, {useState} from 'react';
import {afterEach,expect,it,vi} from 'vitest';
import {act,cleanup,render,screen,fireEvent,waitFor} from '@testing-library/react';
import '@testing-library/jest-dom/vitest';
import ArchiveExplorer,{WorldThumbnail} from './ArchiveExplorer';
const mocks=vi.hoisted(()=>({clicks:[] as any[],get:vi.fn(async(_url:string)=>({available:false})),polygons:vi.fn()}));
vi.mock('../api/client',()=>({getJson:mocks.get}));
vi.mock('leaflet',()=>{
  const layer=()=>{const item:any={};for(const key of ['addTo','on','bindTooltip','setView','clearLayers','remove','invalidateSize','fitBounds'])item[key]=()=>item;return item;};
  return {default:{map:()=>{const m=layer();m.createPane=()=>({style:{}});return m;},tileLayer:()=>layer(),featureGroup:()=>{const l=layer();l.clearLayers=()=>{mocks.clicks=[];};return l;},latLngBounds:(p:any)=>p,
    polygon:(p:any,options:any)=>{mocks.polygons(options);const l=layer();l.on=(event:string,callback:any)=>{mocks.clicks.push(callback);return l;};return l;}}};
});
vi.stubGlobal('ResizeObserver',class {observe(){} disconnect(){}});
afterEach(()=>{cleanup();vi.clearAllMocks();mocks.clicks=[];});
const survey={id:'survey',name:'Reef',grids:[{size:50,processed:22}],cells:Array.from({length:22},(_,i)=>({key:`cell${i}`,dataset_id:`p${i}`,size:50,column:i,row:0,footprint:[[1,1],[1,2],[2,2],[2,1]]}))};

it('limits archived selection to 20 and opens the existing combined-view callback without processing',async()=>{
  const open=vi.fn(),openArea=vi.fn();
  function Harness(){const [selected,setSelected]=useState<string[]>([]);return <ArchiveExplorer survey={survey} selected={selected} setSelected={setSelected} open={open} openArea={openArea}/>;}
  render(<Harness/>);
  fireEvent.click(screen.getByRole('button',{name:'Select multiple cells'}));
  expect(screen.queryByRole('button',{name:'Select multiple cells'})).not.toBeInTheDocument();
  for(let i=0;i<21;i++){await act(async()=>{await mocks.clicks[i]();});}
  expect(screen.getByRole('alert')).toHaveTextContent('maximum of 20');
  fireEvent.click(screen.getByRole('button',{name:'Open 20/20 selected cells'}));
  await waitFor(()=>expect(openArea).toHaveBeenCalledWith(Array.from({length:20},(_,i)=>`p${i}`)));
  expect(open).not.toHaveBeenCalled();
  expect(mocks.get.mock.calls.every(args=>String(args[0]).endsWith('/conditions'))).toBe(true);
  expect(mocks.polygons).toHaveBeenCalledWith(expect.objectContaining({pane:'archiveSelection',interactive:false}));
});

it('compact map opens a single cell and offers the full survey map',async()=>{
  const open=vi.fn(),fullMap=vi.fn();
  render(<ArchiveExplorer compact survey={survey} selected={['p1']} setSelected={vi.fn()} open={open} fullMap={fullMap}/>);
  await act(async()=>{await mocks.clicks[3]();});
  expect(open).toHaveBeenCalledWith('p3');
  fireEvent.click(screen.getByRole('button',{name:/Open entire survey map/}));
  expect(fullMap).toHaveBeenCalled();
});

it('places a red location marker correctly on the world thumbnail',()=>{
  const {container}=render(<WorldThumbnail location={{latitude:20,longitude:-156}}/>);
  expect(container.querySelector('circle')).toHaveAttribute('cx','24');
  expect(container.querySelector('circle')).toHaveAttribute('cy','70');
});
