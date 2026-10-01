import {afterEach,expect,it,vi} from 'vitest';
import {cleanup,fireEvent,render,screen,waitFor} from '@testing-library/react';
import '@testing-library/jest-dom/vitest';
import SurveyRepair from './SurveyRepair';
const mocks=vi.hoisted(()=>({get:vi.fn(),post:vi.fn()}));
vi.mock('../api/client',()=>({getJson:mocks.get,postJson:mocks.post}));
afterEach(()=>{cleanup();vi.resetAllMocks();});

it('starts a rebuild, polls progress and refreshes the archive after activation',async()=>{
  mocks.get.mockResolvedValueOnce({status:'idle'}).mockResolvedValue({status:'preparing',percent:40,stage:'Decoding complete recording to disk'});
  mocks.post.mockResolvedValue({status:'queued'});
  const done=vi.fn();render(<SurveyRepair surveyId="reef" onComplete={done}/>);
  await waitFor(()=>expect(screen.getByRole('button',{name:'Rebuild survey coordinates'})).toBeEnabled());
  fireEvent.click(screen.getByRole('button',{name:'Rebuild survey coordinates'}));
  expect(await screen.findByText(/40%/)).toBeInTheDocument();
  expect(mocks.post).toHaveBeenCalledWith('/api/survey/archive/reef/repair');
  mocks.get.mockResolvedValue({status:'completed',point_count:600001,cells:12,sparse_cells:1,partial:true,warnings:['Damaged recording']});
  expect(await screen.findByText(/Corrected coordinates/,{},{timeout:3500})).toHaveTextContent('Partial recording');
  expect(screen.getByText(/600,001/)).toBeInTheDocument();
  expect(screen.getByText(/too few measurements/)).toBeInTheDocument();
  expect(done).toHaveBeenCalledOnce();
});

it('explains missing originals and allows interrupted jobs to retry',async()=>{
  mocks.get.mockResolvedValue({status:'unavailable',reason:'Original recording unavailable'});
  const view=render(<SurveyRepair surveyId="missing"/>);
  expect(await screen.findByText('Original recording unavailable')).toBeInTheDocument();
  expect(screen.getByRole('button')).toBeDisabled();
  view.unmount();
  mocks.get.mockResolvedValue({status:'failed',error:'Worker was interrupted. Previous results retained; retry.'});
  render(<SurveyRepair surveyId="retry"/>);
  expect(await screen.findByRole('button',{name:'Retry coordinate rebuild'})).toBeEnabled();
  expect(screen.getByRole('alert')).toHaveTextContent('Previous results retained');
});
