// @vitest-environment jsdom
import React from 'react';
import {afterEach,expect,it,vi} from 'vitest';
import {render,screen,fireEvent,waitFor,cleanup} from '@testing-library/react';
import '@testing-library/jest-dom/vitest';
import SurveyArchive from './SurveyArchive';
const mocks=vi.hoisted(()=>({confirm:vi.fn(),remove:vi.fn(),get:vi.fn()}));
vi.mock('../api/client',()=>({getJson:mocks.get,deleteJson:mocks.remove,assetUrl:(url:string)=>url}));
vi.mock('./RegionalThumbnail',()=>({default:()=> <div>Regional thumbnail</div>}));
vi.mock('../api/confirm',()=>({confirmAction:mocks.confirm}));
afterEach(()=>{cleanup();vi.clearAllMocks();});
const raw=[{id:'r1',name:'cell 1',metadata:{replay_id:'s1',survey_name:'Reef Alpha'}},{id:'r2',name:'cell 2',metadata:{replay_id:'s1',survey_name:'Reef Alpha'}},{id:'r3',name:'Reef Beta'}];
const proc=[{id:'p1',name:'Processed cell',raw_dataset_id:'r1'},{id:'combined',name:'Combined',viewer_config:{source_dataset_ids:['p1']}}];
const groups=[{id:'s1',name:'Reef Alpha',raw:raw.slice(0,2),processed:proc},{id:'s2',name:'Reef Beta',raw:raw.slice(2),processed:[]}];
it('expands one survey at a time, lists files and confirms deletion beside Open',async()=>{
  mocks.get.mockImplementation(async(url:string)=>url==='/api/survey/archive'?groups.map(g=>({...g,received_cells:g.raw.length,processed_cells:1,grids:[{size:50,processed:1,received:g.raw.length}]})):url.endsWith('/conditions')?{available:false,reason:'Historical conditions unavailable'}:{assets:[{id:'asset',file_name:'mesh.glb',url:'/asset'}]});mocks.remove.mockResolvedValue({deleted:true});
  const refresh=vi.fn(),open=vi.fn();
  render(<SurveyArchive raw={raw} proc={proc} open={open} openRaw={open} refresh={refresh}/>);
  fireEvent.click(await screen.findByRole('button',{name:/Location unavailable/}));
  fireEvent.click(await screen.findByRole('button',{name:/Reef Alpha/}));
  await screen.findAllByText('mesh.glb');
  expect(screen.getAllByRole('button',{name:'Delete'})).toHaveLength(4);
  mocks.confirm.mockResolvedValueOnce(false);
  fireEvent.click(screen.getAllByRole('button',{name:'Delete'})[0]);
  await waitFor(()=>expect(mocks.confirm).toHaveBeenCalled());expect(mocks.remove).not.toHaveBeenCalled();
  mocks.confirm.mockResolvedValueOnce(true);
  fireEvent.click(screen.getAllByRole('button',{name:'Delete'})[0]);
  await waitFor(()=>expect(mocks.remove).toHaveBeenCalledWith('/api/datasets/raw/r1'));
  expect(refresh).toHaveBeenCalled();
  fireEvent.click(screen.getByRole('button',{name:/Reef Beta/}));
  expect(screen.getByRole('button',{name:/Reef Alpha/})).toHaveAttribute('aria-expanded','false');
  expect(screen.queryByText('Processed cell')).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole('button',{name:/Reef Beta/}));
  expect(screen.queryByRole('button',{name:'Delete'})).not.toBeInTheDocument();
});

it('blocks unprocessed survey maps and deletes whole surveys only after Yes',async()=>{
  mocks.get.mockResolvedValue([{id:'new',name:'New survey',raw:[],processed:[],received_cells:3,processed_cells:0,grids:[]}]);
  const deleted=vi.fn(),openSurvey=vi.fn();
  render(<SurveyArchive raw={[]} proc={[]} refresh={vi.fn()} openSurvey={openSurvey} onSurveyDeleted={deleted}/>);
  fireEvent.click(await screen.findByRole('button',{name:/Location unavailable/}));
  expect(await screen.findByRole('button',{name:'Open survey map'})).toBeDisabled();
  mocks.confirm.mockResolvedValueOnce(false);
  fireEvent.click(screen.getByRole('button',{name:'Delete entire survey'}));
  await waitFor(()=>expect(mocks.confirm).toHaveBeenCalledWith(expect.stringContaining('permanently lose all data')));
  expect(mocks.remove).not.toHaveBeenCalled();
  mocks.confirm.mockResolvedValueOnce(true);mocks.remove.mockResolvedValue({deleted:true,survey_id:'new',raw_ids:[],processed_ids:[]});
  fireEvent.click(screen.getByRole('button',{name:'Delete entire survey'}));
  await waitFor(()=>expect(mocks.remove).toHaveBeenCalledWith('/api/survey/archive/new?confirmed=true'));
  expect(deleted).toHaveBeenCalled();expect(openSurvey).not.toHaveBeenCalled();
  expect(screen.queryByRole('button',{name:'Delete entire survey'})).not.toBeInTheDocument();
});

it('keeps the world location beside the regional map on the area header only',async()=>{
  const area={id:'5N:20:220',zone:5,hemisphere:'N',column:20,row:220,crs:'EPSG:32605',block_column:2,block_row:22};
  mocks.get.mockImplementation(async(url:string)=>url==='/api/survey/archive'?[{id:'s',name:'Survey',area_memberships:[area],raw:[],processed:[],processed_cells:1,received_cells:1,grids:[]}]:{available:false});
  const {container}=render(<SurveyArchive raw={[]} proc={[]} refresh={vi.fn()}/>);
  fireEvent.click(await screen.findByRole('button',{name:/UTM 5N/}));
  const header=container.querySelector('.archive-area-heading')!;
  expect(header.querySelector('svg circle')).not.toBeNull();
  expect(header).toHaveTextContent('Regional thumbnail');
  expect(container.querySelector('.archive-row-heading svg')).toBeNull();
  expect(container.querySelector('.archive-row-heading')).toHaveTextContent('Regional thumbnail');
});
