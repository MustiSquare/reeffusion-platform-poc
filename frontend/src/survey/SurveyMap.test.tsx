// @vitest-environment jsdom
import React from 'react';
import { afterEach, expect, it, vi } from 'vitest';
import { cleanup, render } from '@testing-library/react';
import SurveyMap from './SurveyMap';
const mocks=vi.hoisted(()=>({polygon:vi.fn(),markers:vi.fn(),soundings:{style:{} as Record<string,string>},pane:{style:{} as Record<string,string>}}));
vi.mock('leaflet',()=>{
  const layer=()=>{const item:any={};for(const key of ['addTo','on','bindTooltip','setView','clearLayers','remove','invalidateSize'])item[key]=()=>item;return item;};
  const tileLayer:any=()=>layer();tileLayer.wms=()=>layer();
  return {default:{map:()=>{const m=layer();m.createPane=(name:string)=>name==='surveySelection'?mocks.pane:mocks.soundings;return m;},tileLayer,
    control:{layers:()=>layer(),scale:()=>layer()},featureGroup:()=>layer(),
    polygon:(...args:any[])=>{mocks.polygon(...args);return layer();},circleMarker:(...args:any[])=>{mocks.markers(...args);return layer();},polyline:()=>layer()}};
});
vi.stubGlobal('ResizeObserver',class {observe(){} disconnect(){}});
afterEach(()=>{cleanup();mocks.polygon.mockClear();});
it('draws selection in a top non-interactive pane and never invents future cells from saved jobs',()=>{
  render(<SurveyMap replay={{id:'test',crs:'EPSG:32605',frames:[]} as any}
    blocks={[{key:'0:0',column:0,row:0,points:[[0,0,-18,-155,20,1]],coverage:0,last:0,samples:0}]}
    boat={null} track={[]} selected="" select={()=>{}} visible size={50}
    jobs={{'2:2':{result_processed_dataset_id:'future',status:'completed'}}}
    multiSelect selectedCells={['0:0']}/>);
  expect(mocks.polygon).toHaveBeenCalledTimes(2);
  expect(mocks.polygon.mock.calls[1][1]).toMatchObject({pane:'surveySelection',interactive:false,fillOpacity:.35});
  expect(mocks.pane.style).toMatchObject({zIndex:'650',pointerEvents:'none'});
  expect(mocks.soundings.style).toMatchObject({zIndex:'450',pointerEvents:'none'});
  expect(mocks.markers).toHaveBeenCalledWith([20,-155],expect.objectContaining({pane:'surveySoundings',interactive:false}));
});

