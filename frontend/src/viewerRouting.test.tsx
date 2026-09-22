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
afterEach(cleanup);
it('opens a multi-cell selection in the full existing viewer with annotation and measurement controls',async()=>{
  mocks.post.mockResolvedValue({dataset_id:'combined'});
  mocks.get.mockImplementation(async(url:string)=>url==='/api/datasets/processed/combined'?{id:'combined',name:'Combined reef area (2 cells)',assets:[],metrics:{}}:[]);
  render(<App/>);
  fireEvent.click(screen.getByRole('button',{name:'Live Survey'}));
  fireEvent.click(screen.getByRole('button',{name:'Open selected area'}));
  await screen.findByText('Combined reef area (2 cells)');
  expect(mocks.post).toHaveBeenCalledWith('/api/survey/combined-area',{dataset_ids:['tile-a','tile-b']});
  expect(screen.getByRole('button',{name:'Processed Data Viewer'})).toHaveClass('active');
  for(const name of ['Inspect','Annotate','Measure','Fit dataset','Top','Side','Front']) expect(screen.getByRole('button',{name})).toBeInTheDocument();
  expect(screen.getByText('Z exaggeration')).toBeInTheDocument();
  expect(screen.getByText('Layers')).toBeInTheDocument();
  expect(screen.getByTestId('existing-viewer-canvas')).toBeInTheDocument();
  await waitFor(()=>expect(mocks.get).toHaveBeenCalledWith('/api/annotations/combined'));
});
