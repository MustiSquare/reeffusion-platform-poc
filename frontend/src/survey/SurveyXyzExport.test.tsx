import {afterEach, expect, it, vi} from 'vitest';
import {cleanup, fireEvent, render, screen, waitFor} from '@testing-library/react';
import '@testing-library/jest-dom/vitest';
import SurveyXyzExport from './SurveyXyzExport';

const mocks=vi.hoisted(()=>({get:vi.fn(),post:vi.fn()}));
vi.mock('../api/client',()=>({getJson:mocks.get,postJson:mocks.post,assetUrl:(s:string)=>s}));
afterEach(()=>{cleanup();vi.resetAllMocks();vi.useRealTimers();});

it('starts a full export and shows progress followed by a partial download and warning',async()=>{
  mocks.get.mockResolvedValueOnce({status:'idle'}).mockResolvedValue({status:'preparing',percent:45,stage:'Decoding individual detections'});
  mocks.post.mockResolvedValue({status:'queued',percent:0});
  render(<SurveyXyzExport surveyId="reef"/>);
  await waitFor(()=>expect(screen.getByRole('button',{name:'Export XYZ CSV'})).toBeEnabled());
  fireEvent.click(screen.getByRole('button',{name:'Export XYZ CSV'}));
  expect(await screen.findByText(/45%/)).toBeInTheDocument();
  expect(mocks.post).toHaveBeenCalledWith('/api/survey/archive/reef/xyz-export');
  expect(screen.getByRole('button',{name:'Preparing XYZ CSV…'})).toBeDisabled();
  mocks.get.mockResolvedValue({status:'completed',partial:true,point_count:654321,warnings:['Damaged recording; recovered the valid prefix.']});
  const link=await screen.findByRole('link',{name:'Download partial CSV'},{timeout:3000});
  expect(link).toHaveAttribute('href','/api/survey/archive/reef/xyz-export/download');
  expect(screen.getByText(/654,321 recovered detections/)).toBeInTheDocument();
  expect(screen.getByText(/Damaged recording/)).toBeInTheDocument();
});

it('explains unavailable originals and does not offer a download',async()=>{
  mocks.get.mockResolvedValue({status:'unavailable',reason:'Original recording is missing.'});
  render(<SurveyXyzExport surveyId="reef"/>);
  expect(await screen.findByText(/Original recording is missing/)).toBeInTheDocument();
  expect(screen.getByRole('button',{name:'Export XYZ CSV'})).toBeDisabled();
  expect(screen.queryByRole('link')).not.toBeInTheDocument();
});

it('allows failed jobs to retry and reuses completed exports on refresh',async()=>{
  mocks.get.mockResolvedValue({status:'failed',error:'Worker was interrupted. Retry.'});
  mocks.post.mockResolvedValue({status:'completed',point_count:12,partial:false});
  render(<SurveyXyzExport surveyId="reef"/>);
  fireEvent.click(await screen.findByRole('button',{name:'Retry XYZ export'}));
  expect(await screen.findByRole('link',{name:'Download XYZ CSV'})).toBeInTheDocument();
  expect(screen.getByText(/12 valid detections/)).toBeInTheDocument();
});
