// @vitest-environment jsdom
import React from 'react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import '@testing-library/jest-dom/vitest';
import LiveSurvey from './LiveSurvey';

const mocks=vi.hoisted(()=>({get:vi.fn(),post:vi.fn(),openArea:vi.fn()}));
vi.mock('../api/client',()=>({getJson:mocks.get,postJson:mocks.post,assetUrl:(s:string)=>s}));
vi.mock('./SurveyMap',()=>({default:({blocks,select,jobs}:any)=><div><output data-testid="map-point-count">{blocks.reduce((n:number,b:any)=>n+b.points.length,0)}</output><output data-testid="map-jobs">{JSON.stringify(jobs)}</output>{blocks.map((b:any)=><button key={b.key} onClick={()=>select(b.key)}>Select block {b.key}</button>)}</div>}));
const replay={id:'test',name:'boat.svlz',started_at:'2026-07-10T20:00:00Z',duration:10,crs:'EPSG:32605',point_count:5,warnings:['Recovered incomplete recording'],frames:[
  {t:0,boat:[-155.9,20.18,90,0,0],points:[[1,1,-2,0,0,1]]},
  {t:10,boat:[-155.9,20.18,90,0,0],points:[[2,1,-2,0,0,1],[1,2,-2,0,0,1],[2,2,-2,0,0,1]]},
]};
beforeEach(()=>{
  localStorage.clear();localStorage.setItem('reef-survey-replay','test');
  mocks.get.mockImplementation(async(path:string)=>path.includes('/replays/')?replay:{warnings:['Historical marine unavailable.']});
  mocks.post.mockReset();
});
afterEach(()=>{cleanup();vi.useRealTimers();vi.clearAllMocks();});
describe('Live Survey controls',()=>{
  it('uses one selection button and opens a single selected cell directly',async()=>{
    mocks.get.mockImplementation(async(path:string)=>path.endsWith('/processed-blocks')?[{column:0,row:0,size:50,until:10,status:'completed',result_processed_dataset_id:'processed'}]:path.includes('/replays/')?replay:{});
    const open=vi.fn();
    render(<LiveSurvey visible openArea={mocks.openArea} refresh={()=>{}} openProcessed={open}/>);
    await screen.findByText('boat.svlz');await act(async()=>{});
    fireEvent.change(screen.getByLabelText('Playback position'),{target:{value:'10'}});
    fireEvent.click(screen.getByText('Select multiple cells'));
    fireEvent.click(screen.getByText('Select block 0:0'));
    expect(open).not.toHaveBeenCalled();expect(screen.getByText('Selected: 1 / 20')).toBeInTheDocument();
    fireEvent.click(screen.getByText('Open selected area'));
    expect(open).toHaveBeenCalledWith('processed');
    expect(mocks.openArea).not.toHaveBeenCalled();
    expect(screen.queryByText('Select multiple cells')).not.toBeInTheDocument();
    expect(screen.queryByText('Combined tiles: processed')).not.toBeInTheDocument();
    fireEvent.click(screen.getByText('Clear selection'));
    expect(await screen.findByText('Open selected area')).toBeDisabled();
  });
  it('hides future results and resets the count without restoring old completions',async()=>{
    const saved={column:0,row:0,size:50,until:10,status:'completed',result_processed_dataset_id:'old'};
    localStorage.setItem('reef-survey-jobs:test:50',JSON.stringify({'0:0':saved}));
    mocks.get.mockImplementation(async(path:string)=>path.endsWith('/processed-blocks')?[saved]:path.includes('/replays/')?replay:{});
    render(<LiveSurvey visible openArea={mocks.openArea} refresh={()=>{}} openProcessed={()=>{}}/>);
    await screen.findByText('boat.svlz');await act(async()=>{});
    expect(screen.getByLabelText('Playback position')).toHaveValue('10');
    expect(screen.getByTestId('map-point-count')).toHaveTextContent('4');
    expect(screen.getByText(/1 \/ 1 received cells processed/)).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText('Playback position'),{target:{value:'0'}});
    expect(screen.getByText(/0 \/ 1 received cells processed/)).toBeInTheDocument();
    expect(screen.getByTestId('map-jobs')).toHaveTextContent('{}');
    fireEvent.change(screen.getByLabelText('Playback position'),{target:{value:'10'}});
    expect(screen.getByText(/1 \/ 1 received cells processed/)).toBeInTheDocument();
    fireEvent.click(screen.getByText('Select multiple cells'));
    fireEvent.click(screen.getByText('Select block 0:0'));
    fireEvent.click(screen.getByText('Open selected area'));
    fireEvent.click(screen.getByText('Reset processing run'));
    await act(async()=>{});
    expect(screen.queryByText('Combined tiles: old')).not.toBeInTheDocument();
    expect(screen.getByText(/0 \/ 1 received cells processed/)).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText('Playback position'),{target:{value:'10'}});
    expect(screen.getByTestId('map-jobs')).toHaveTextContent('{}');
    expect(screen.getByText(/0 \/ 1 received cells processed/)).toBeInTheDocument();
    cleanup();
    render(<LiveSurvey visible openArea={mocks.openArea} refresh={()=>{}} openProcessed={()=>{}}/>);
    await screen.findByText('boat.svlz');await act(async()=>{});
    fireEvent.change(screen.getByLabelText('Playback position'),{target:{value:'10'}});
    expect(screen.getByTestId('map-jobs')).toHaveTextContent('{}');
  });
  it('reset followed by play processes a low-coverage block when playback ends',async()=>{
    mocks.post.mockImplementation(async(path:string)=>path.endsWith('/blocks')?{dataset_id:'raw'}:{job_id:'job',status:'queued'});
    render(<LiveSurvey visible openArea={mocks.openArea} refresh={()=>{}} openProcessed={()=>{}}/>);
    await screen.findByText('boat.svlz');
    fireEvent.click(screen.getByText('Reset processing run'));
    expect(mocks.post).not.toHaveBeenCalled();
    expect(screen.getByLabelText('Playback position')).toHaveValue('0');
    fireEvent.change(screen.getByLabelText('Playback speed'),{target:{value:'60'}});
    vi.useFakeTimers();
    fireEvent.click(screen.getByText('Play & process'));
    await act(async()=>{});
    await act(async()=>{await vi.advanceTimersByTimeAsync(500);});
    expect(mocks.post).toHaveBeenCalledWith('/api/survey/replays/test/blocks',{column:0,row:0,size:50,until:10});
    expect(mocks.post).toHaveBeenCalledWith('/api/jobs/process/raw');
  });
  it('opens a restored completed dataset directly from its map cell',async()=>{
    mocks.get.mockImplementation(async(path:string)=>path.endsWith('/processed-blocks')?[{column:0,row:0,size:50,until:10,status:'completed',result_processed_dataset_id:'processed'}]:path.includes('/replays/')?replay:{});
    const open=vi.fn();
    render(<LiveSurvey visible openArea={mocks.openArea} refresh={()=>{}} openProcessed={open}/>);
    await screen.findByText('boat.svlz');
    await act(async()=>{});
    fireEvent.change(screen.getByLabelText('Playback position'),{target:{value:'10'}});
    fireEvent.click(screen.getByText('Select block 0:0'));
    expect(open).toHaveBeenCalledWith('processed');
  });
  it('restores a recording, retains partial points and enables processing only with enough data',async()=>{
    render(<LiveSurvey visible openArea={mocks.openArea} refresh={()=>{}} openProcessed={()=>{}}/>);
    await screen.findByText('boat.svlz');
    fireEvent.click(await screen.findByText('Select block 0:0'));
    expect(screen.getByText('Process current measurements')).toBeDisabled();
    expect(screen.getByText('Download XYZ')).toBeEnabled();
    fireEvent.change(screen.getByLabelText('Playback position'),{target:{value:'10'}});
    expect(screen.getByText('Process current measurements')).toBeEnabled();
    expect(screen.getByText('Recovered incomplete recording')).toBeInTheDocument();
    expect(mocks.post).not.toHaveBeenCalled();
  });
  it('imports the selected cursor snapshot and queues the normal pipeline',async()=>{
    mocks.post.mockImplementation(async(path:string)=>path.endsWith('/blocks')?{dataset_id:'raw'}:{job_id:'job',status:'queued'});
    render(<LiveSurvey visible openArea={mocks.openArea} refresh={()=>{}} openProcessed={()=>{}}/>);
    await screen.findByText('boat.svlz');
    fireEvent.change(screen.getByLabelText('Playback position'),{target:{value:'10'}});
    fireEvent.click(screen.getByText('Select block 0:0'));
    fireEvent.click(screen.getByText('Process current measurements'));
    await waitFor(()=>expect(mocks.post).toHaveBeenCalledWith('/api/jobs/process/raw'));
    expect(mocks.post).toHaveBeenCalledWith('/api/survey/replays/test/blocks',{column:0,row:0,size:50,until:10});
  });
});
