// @vitest-environment jsdom
import React from 'react';
import { afterEach, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import '@testing-library/jest-dom/vitest';
import { App } from './main';
const mocks=vi.hoisted(()=>({post:vi.fn(),get:vi.fn()}));
vi.mock('react-dom/client',()=>({createRoot:()=>({render:()=>{}})}));
vi.mock('@react-three/fiber',()=>({Canvas:()=> <div data-testid="existing-viewer-canvas"/>,useFrame:vi.fn(),useThree:vi.fn()}));
vi.mock('./api/client',()=>({getJson:mocks.get,postJson:mocks.post,putJson:vi.fn(),deleteJson:vi.fn(),uploadFiles:vi.fn(),assetUrl:(url:string)=>url}));
vi.mock('./survey/LiveSurvey',()=>({default:({openArea}:any)=><button onClick={()=>openArea(['tile-a','tile-b'])}>Open selected area</button>}));
vi.mock('./survey/ArchiveExplorer',()=>({default:({compact,open,openArea}:any)=><div><span>{compact?'Compact cell map':'Full archived map'}</span><button onClick={()=>open('tile-a')}>Open archived cell</button><button onClick={()=>openArea(['tile-a','tile-b'])}>Open archived selection</button></div>,WorldThumbnail:()=>null,ArchiveConditions:()=>null}));
const scrollToViewer=vi.fn();
Element.prototype.scrollIntoView=scrollToViewer;
afterEach(()=>{cleanup();scrollToViewer.mockClear();});
it('opens a multi-cell selection in the full existing viewer with annotation and measurement controls',async()=>{
  mocks.post.mockResolvedValue({dataset_id:'combined'});
  mocks.get.mockImplementation(async(url:string)=>url==='/api/datasets/processed/combined'?{id:'combined',name:'Combined reef area (2 cells)',status:'completed',assets:[],metrics:{}}:url==='/api/datasets/processed'?[{id:'combined',name:'Combined reef area (2 cells)',status:'completed'}]:[]);
  render(<App/>);
  fireEvent.click(screen.getByRole('button',{name:'Live Survey'}));
  fireEvent.click(screen.getByRole('button',{name:'Open selected area'}));
  await screen.findByText('Combined reef area (2 cells)');
  expect(mocks.post).toHaveBeenCalledWith('/api/survey/combined-area',{dataset_ids:['tile-a','tile-b']});
  expect(screen.getByRole('button',{name:'Reef Analysis'})).toHaveClass('active');
  for(const name of ['Inspect','Annotate','Measure','Fit dataset','Top','Side','Front']) expect(screen.getByRole('button',{name})).toBeInTheDocument();
  expect(screen.getByText('Z exaggeration')).toBeInTheDocument();
  expect(screen.getByText('Layers')).toBeInTheDocument();
  expect(screen.getByTestId('existing-viewer-canvas')).toBeInTheDocument();
  await waitFor(()=>expect(scrollToViewer).toHaveBeenCalledWith({block:'start',behavior:'instant'}));
  await waitFor(()=>expect(mocks.get).toHaveBeenCalledWith('/api/annotations/combined'));
});

it('opens an archive map without loading a recording and routes its cells into the same viewer',async()=>{
  const group={id:'survey',name:'Archived reef',raw:[],processed:[{id:'tile-a',name:'Cell A'}],received_cells:2,processed_cells:2,grids:[{size:50,processed:2,received:2}],cells:[]};
  mocks.get.mockClear();mocks.post.mockClear();
  mocks.get.mockImplementation(async(url:string)=>{
    if(url==='/api/survey/archive')return [group];
    if(url==='/api/survey/archive/survey')return group;
    if(url==='/api/datasets/processed/tile-a')return {id:'tile-a',name:'Cell A',status:'completed',assets:[],metrics:{}};
    return [];
  });
  render(<App/>);
  fireEvent.click(screen.getByRole('button',{name:'Live Survey'}));
  fireEvent.click(screen.getByRole('button',{name:'Access previous surveys'}));
  fireEvent.click(await screen.findByRole('button',{name:/Location unavailable/}));
  fireEvent.click(await screen.findByRole('button',{name:'Open survey map'}));
  await screen.findByText('Full archived map');
  expect(mocks.get.mock.calls.some(([url])=>String(url).includes('/replays/'))).toBe(false);
  expect(mocks.post).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole('button',{name:'Open archived cell'}));
  await screen.findByText('Compact cell map');
  expect(screen.getByText('Browse survey cells').closest('details')).not.toHaveAttribute('open');
  expect(screen.getByRole('button',{name:'Reef Analysis'})).toHaveClass('active');
  expect(screen.getByTestId('existing-viewer-canvas')).toBeInTheDocument();
  await waitFor(()=>expect(scrollToViewer).toHaveBeenCalledWith({block:'start',behavior:'instant'}));
  expect(screen.getByRole('button',{name:'Measure'})).toBeInTheDocument();
});

it('does not show a reef when no completed result is available',async()=>{
  mocks.post.mockResolvedValue({dataset_id:'pending'});
  mocks.get.mockImplementation(async(url:string)=>url==='/api/datasets/processed/pending'?{id:'pending',name:'Unprocessed reef',status:'processing',assets:[]}:[]);
  render(<App/>);
  fireEvent.click(screen.getByRole('button',{name:'Reef Analysis'}));
  expect(screen.queryByTestId('existing-viewer-canvas')).not.toBeInTheDocument();
  expect(screen.getByRole('alert')).toHaveTextContent('Process this survey data');
});

it('rejects a result that is still processing even if an archive entry previously allowed Open',async()=>{
  const group={id:'s',name:'Pending survey',raw:[],processed:[{id:'pending',name:'Pending cell',status:'completed'}],received_cells:1,processed_cells:1,grids:[]};
  mocks.get.mockImplementation(async(url:string)=>url==='/api/survey/archive'?[group]:url==='/api/datasets/processed/pending'?{id:'pending',status:'processing',assets:[]}:[]);
  render(<App/>);
  fireEvent.click(screen.getByRole('button',{name:'Data Archive'}));
  fireEvent.click(await screen.findByRole('button',{name:/Location unavailable/}));
  fireEvent.click(await screen.findByRole('button',{name:/Pending survey/}));
  fireEvent.click(screen.getByRole('button',{name:'Open'}));
  await screen.findByRole('alert');
  expect(screen.getByRole('alert')).toHaveTextContent('Process this survey data');
  expect(screen.queryByTestId('existing-viewer-canvas')).not.toBeInTheDocument();
  expect(screen.getByRole('button',{name:'Data Archive'})).toHaveClass('active');
});
