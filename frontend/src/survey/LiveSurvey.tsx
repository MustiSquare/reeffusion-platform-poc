import {createPlaybackSnapshot} from './playbackSnapshot';
import { Loading, watchLoading, uploadRecording } from './loading';
import { motionAt, MotionSample } from './motion';
import { confirmedFetch, clearOverwriteApprovals, approveOverwrite, approveRunKey } from '../api/confirm';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { getJson, postJson, assetUrl } from '../api/client';
import { Block, Replay, canProcess, needsProcessing } from './model';
import SurveyMap from './SurveyMap';
import CompletedResults from './CompletedResults';
import { MAX_SELECTED_CELLS, toggleCell } from './selection';
import './survey.css';

type Job = { samples:number; until:number; dataset_id?:string; job_id?:string; status:string; progress?:number; result_processed_dataset_id?:string; error?:string };
const empty={blocks:[],boat:null,boatTime:0,track:[]};
const errorText=(e:unknown)=>e instanceof Error?e.message:String(e);
function savedJobs(id:string,size:number):Record<string,Job>{
  try{return JSON.parse(localStorage.getItem(`reef-survey-jobs:${id}:${size}`)||'{}');}catch{return {};}
}

export default function LiveSurvey({visible,openProcessed,openArea,refresh,archived=false}:{archived?:boolean;visible:boolean;openProcessed:(id:string)=>void;openArea:(ids:string[])=>void|Promise<void>;refresh:()=>void}) {
  const [motionSamples,setMotionSamples]=useState<MotionSample[]>([]),[motionStatus,setMotionStatus]=useState('No recording loaded');
  const restoreCursor=useRef(false);
  const uploadAbort=useRef<AbortController|null>(null);
  const recordingInput=useRef<HTMLInputElement|null>(null);
  useEffect(()=>()=>{uploadAbort.current?.abort();},[]);
  const [loading,setLoading]=useState<Loading|null>(null);
  const [uploadLimit,setUploadLimit]=useState(2*1024**3);
  useEffect(()=>{getJson('/api/survey/configuration').then(c=>{if(c.upload_limit_bytes>0)setUploadLimit(c.upload_limit_bytes);}).catch(()=>{});},[]);
  const updateLoading=(value:Loading)=>setLoading(old=>({...value,percent:value.percent===0?0:Math.max(old?.percent||0,value.percent)}));
  const [surveyName,setSurveyName]=useState('');
  const [selectedFilename,setSelectedFilename]=useState('');
  const [replay,setReplay]=useState<Replay|null>(null), [busy,setBusy]=useState(false), [error,setError]=useState('');
  const [cursor,setCursor]=useState(0), [playing,setPlaying]=useState(false), [speed,setSpeed]=useState(10), [size,setSize]=useState(50);
  const [selected,setSelected]=useState(''), [auto,setAuto]=useState(false), [conditions,setConditions]=useState<any>(null);
  const [jobs,setJobs]=useState<Record<string,Job>>({}), [importing,setImporting]=useState(false);
  const [runStarted,setRunStarted]=useState(false), [showResults,setShowResults]=useState(false);
  const [completedCells,setCompletedCells]=useState<any[]>([]);
  const [freshRun,setFreshRun]=useState(false);
  const [openingArea,setOpeningArea]=useState(false);
  const [multiSelect,setMultiSelect]=useState(false),[selectedCells,setSelectedCells]=useState<string[]>([]);
  useEffect(()=>{if(archived){setPlaying(false);setAuto(false);setRunStarted(false);}},[archived]);
  useEffect(()=>{setSelectedCells([]);setMultiSelect(false);},[replay?.id,size]);
  const inFlight=useRef(false), generation=useRef(0), runApproved=useRef(false);
  const playbackSnapshot=useMemo(()=>replay?createPlaybackSnapshot(replay,size):null,[replay,size]);
  const state=useMemo(()=>playbackSnapshot?playbackSnapshot(Math.floor(cursor)):empty,[playbackSnapshot,Math.floor(cursor)]);
  const block=state.blocks.find(b=>b.key===selected);
  const stamp=replay?new Date(Date.parse(replay.started_at)+cursor*1000):null;
  const day=stamp?.toISOString().slice(0,10);
  const latitude=state.boat?Math.round(state.boat[1]*100)/100:null, longitude=state.boat?Math.round(state.boat[0]*100)/100:null;

  const motion=useMemo(()=>motionAt(motionSamples,Math.floor(cursor)),[motionSamples,Math.floor(cursor)]);
  useEffect(()=>{
    setMotionSamples([]);
    if(!replay){setMotionStatus('No recording loaded');return;}
    let cancelled=false;setMotionStatus('Loading onboard motion...');
    getJson(`/api/survey/replays/${replay.id}/motion`).then(data=>{
      if(cancelled)return;
      const samples=Array.isArray(data.samples)?data.samples:[];
      setMotionSamples(samples);setMotionStatus(samples.length?'No recent attitude samples at this time':'No attitude data in recording');
    }).catch(()=>{if(!cancelled)setMotionStatus('Onboard motion unavailable');});
    return()=>{cancelled=true;};
  },[replay?.id]);

  async function approveRun(){
    if(!replay)return false;
    if(runApproved.current)return true;
    const history=await getJson(`/api/survey/replays/${replay.id}/processing-history`);
    const approved=!history.processed_at||await approveOverwrite(replay.id,history.processed_at);
    if(approved)approveRunKey(replay.id);
    runApproved.current=approved;return approved;
  }
  async function togglePlayback(){
    if(playing){setPlaying(false);return;}
    setBusy(true);
    try{
      if(!await approveRun())return;
      if(replay&&cursor>=replay.duration)setCursor(0);
      setAuto(true);setRunStarted(true);setPlaying(true);
    }catch(e){setError(errorText(e));}finally{setBusy(false);}
  }

  async function load(file:File) {
    if(file.size>uploadLimit){setError(`Maximum file size is ${uploadLimit/1024**3} GB.`);return;}
    restoreCursor.current=false;
    setSelectedFilename(file.name);
    runApproved.current=false;clearOverwriteApprovals();setBusy(true);setPlaying(false);setError('');
    try {
      const fd=new FormData();fd.append('file',file);fd.append('survey_name',surveyName);
      const controller=new AbortController();uploadAbort.current=controller;
      const next=await uploadRecording(fd,value=>{if(!controller.signal.aborted)updateLoading(value);},controller.signal);
      if(controller.signal.aborted)return;
      generation.current++;setReplay(next);setCursor(0);setSelected('');setJobs({});setAuto(false);setConditions(null);setRunStarted(false);setCompletedCells([]);setFreshRun(true);
      try {localStorage.setItem('reef-survey-replay',next.id);}catch{}
      setLoading({percent:100,stage:'Survey ready'});
    }catch(e){setLoading(null);setError(errorText(e));}finally{setBusy(false);}
  }
  useEffect(()=>{
    let cancelled=false;
    let id:string|null=null;try{id=localStorage.getItem('reef-survey-replay');}catch{}
    const progressId=crypto.randomUUID();
    const stop=id?watchLoading(progressId,updateLoading):()=>{};
    if(id){setLoading({percent:0,stage:'Loading previous survey'});setBusy(true);getJson(`/api/survey/replays/${id}?lightweight=true&progress_id=${progressId}`).then(r=>{if(!cancelled){setLoading({percent:100,stage:'Survey ready'});restoreCursor.current=true;setReplay(r);setSelectedFilename(r.source_name||r.name);setJobs(savedJobs(r.id,50));setFreshRun(localStorage.getItem(`reef-survey-fresh:${r.id}:50`)==='true');}}).catch(()=>{if(!cancelled){setLoading(null);setError('Previous replay is unavailable. Load a recording to begin.');}}).finally(()=>{stop();if(!cancelled)setBusy(false);});}
    return()=>{cancelled=true;stop();};
  },[]);
  useEffect(()=>{if(replay){try{localStorage.setItem(`reef-survey-jobs:${replay.id}:${size}`,JSON.stringify(jobs));}catch{}}},[replay?.id,size,jobs]);
  useEffect(()=>{
    if(!playing||!replay) return;
    let previous=performance.now();
    const timer=setInterval(()=>{
      const now=performance.now(),delta=(now-previous)/1000*speed;previous=now;
      setCursor(t=>Math.min(replay.duration,t+delta));
    },250);
    return()=>clearInterval(timer);
  },[playing,speed,replay]);
  useEffect(()=>{if(replay&&cursor>=replay.duration)setPlaying(false);},[cursor,replay]);
  useEffect(()=>{
    if(!day||latitude===null||longitude===null) return;
    let cancelled=false;setConditions(null);
    getJson(`/api/survey/conditions?latitude=${latitude}&longitude=${longitude}&day=${day}`)
      .then(d=>{if(!cancelled)setConditions(d);})
      .catch(()=>{if(!cancelled)setConditions({warnings:['Historical conditions unavailable.']});});
    return()=>{cancelled=true;};
  },[day,latitude,longitude]);
  const active=Object.values(jobs).some(j=>j.job_id&&!['completed','failed'].includes(j.status));
  const completionKey=Object.values(jobs).map(j=>j.result_processed_dataset_id||'').join(',');
  useEffect(()=>{
    if(!replay)return;
    let cancelled=false;
    getJson(`/api/survey/replays/${replay.id}/processed-blocks`).then(data=>{if(!cancelled){
      const cells=Array.isArray(data)?data:[];setCompletedCells(cells);
      if(restoreCursor.current){restoreCursor.current=false;if(!freshRun&&cells.length)setCursor(Math.min(replay.duration,Math.max(...cells.map((c:any)=>c.until||0))));}
    }}).catch(e=>{if(!cancelled)setError(`Cannot restore completed map cells: ${errorText(e)}`);});
    return()=>{cancelled=true;};
  },[replay?.id,completionKey]);
  const mapJobs=useMemo(()=>{
    const merged:Record<string,any>={};
    for(const cell of completedCells){if(!freshRun && cell.size===size && cell.until<=cursor)merged[`${cell.column}:${cell.row}`]=cell;}
    for(const [key,job] of Object.entries(jobs)){if(job.until>cursor)continue;merged[key]={...merged[key],...job,
      result_processed_dataset_id:job.result_processed_dataset_id||merged[key]?.result_processed_dataset_id};}
    return merged;
  },[completedCells,jobs,size,Math.floor(cursor),freshRun]);
  const selectCell=useCallback(async(key:string)=>{
    setSelected(key);
    const id=mapJobs[key]?.result_processed_dataset_id;
    if(multiSelect){
      if(!id){setError('Only cells with a completed result can be selected.');return;}
      setSelectedCells(keys=>toggleCell(keys,key,true));
      return;
    }
    if(id){try{await openProcessed(id);}catch(e){setError(errorText(e));}}
  },[mapJobs,openProcessed,multiSelect]);
  async function openSelectedArea(){
    if(openingArea)return;
    const ids=selectedCells.map(key=>mapJobs[key]?.result_processed_dataset_id);
    if(!ids.length||ids.length>MAX_SELECTED_CELLS||ids.some(id=>!id)){setError('Select between 1 and 20 completed cells.');return;}
    setPlaying(false);setOpeningArea(true);setError('');
    try{if(ids.length===1)await openProcessed(ids[0]!);else await openArea(ids);}catch(e){setError(errorText(e));}finally{setOpeningArea(false);}
  }
  function resetRun(){
    if(active||importing)return;
    runApproved.current=false;clearOverwriteApprovals();generation.current++;setFreshRun(true);setSelectedCells([]);setMultiSelect(false);
    if(replay){try{localStorage.setItem(`reef-survey-fresh:${replay.id}:${size}`,'true');}catch{}}
    setPlaying(false);setCursor(0);setSelected('');setJobs({});setAuto(true);setRunStarted(false);setError('');
  }
  useEffect(()=>{
    if(!active) return;
    let cancelled=false;
    const timer=setInterval(async()=>{
      for(const [key,j] of Object.entries(jobs)){
        if(!j.job_id||['completed','failed'].includes(j.status))continue;
        try{const result=await getJson(`/api/jobs/${j.job_id}`);if(!cancelled)setJobs(all=>({...all,[key]:{...all[key],...result}}));}
        catch(e){if(!cancelled)setError(`Cannot read processing progress: ${errorText(e)}`);}
      }
    },2000);
    return()=>{cancelled=true;clearInterval(timer);};
  },[active,jobs]);

  async function process(block:Block){
    if(!replay||inFlight.current||!canProcess(block))return;
    inFlight.current=true;setImporting(true);setError('');
    try{if(!await approveRun()){inFlight.current=false;setImporting(false);setAuto(false);return;}}
    catch(e){inFlight.current=false;setImporting(false);setAuto(false);setError(errorText(e));return;}
    const revision=generation.current,until=Math.floor(cursor);
    setJobs(all=>({...all,[block.key]:{samples:block.samples,until,status:'importing'}}));
    try{
      const raw=await postJson(`/api/survey/replays/${replay.id}/blocks`,{column:block.column,row:block.row,size,until});
      const job=raw.job_id?await getJson(`/api/jobs/${raw.job_id}`):await postJson(`/api/jobs/process/${raw.dataset_id}`);
      if(revision===generation.current)setJobs(all=>({...all,[block.key]:{...job,samples:block.samples,until,dataset_id:raw.dataset_id,job_id:job.job_id||job.id,status:job.status}}));
      refresh();
    }catch(e){setAuto(false);setPlaying(false);if(revision===generation.current){setError(errorText(e));setJobs(all=>({...all,[block.key]:{samples:block.samples,until,status:'failed',error:errorText(e)}}));}}
    finally{inFlight.current=false;setImporting(false);}
  }
  useEffect(()=>{
    if(!auto||!runStarted||busy||importing||active||!replay)return;
    const candidate=state.blocks.find(b=>needsProcessing(b,jobs[b.key],cursor,replay.duration));
    if(candidate) void process(candidate);
  },[auto,runStarted,busy,importing,active,state.blocks,cursor,jobs,replay]);

  async function download(){
    if(!replay||!block)return;
    try{
      const response=await fetch(assetUrl(`/api/survey/replays/${replay.id}/block.csv`),{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({column:block.column,row:block.row,size,until:Math.floor(cursor)})});
      if(!response.ok)throw new Error(await response.text());
      const url=URL.createObjectURL(await response.blob()),a=document.createElement('a');a.href=url;a.download=`block_${block.key.replace(':','_')}_xyz.csv`;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
    }catch(e){setError(errorText(e));}
  }
  const hour=stamp?.getUTCHours()||0;
  function condition(kind:string,key:string){
    const data=conditions?.[kind],value=data?.hourly?.[key]?.[hour];
    return value===null||value===undefined?'Unavailable':`${value} ${data.units?.[key]||''}`;
  }
  return <div className="live-survey">
    <div className="survey-heading"><div className="survey-title-row"><div><h2>Live Survey</h2><p>BlueBoat recording playback · fixed metre grid · partial coverage preserved</p></div>
      {loading&&<div className="survey-loading" role="status"><span>{loading.stage}: {Math.floor(loading.percent)}%{loading.percent<100?' (estimated)':''}</span><progress aria-label="Survey loading progress" max={100} value={loading.percent}/></div>}
    </div>
    <div className="survey-name-row"><label>Survey name (optional)<input aria-label="Survey name" placeholder="Use recording filename" value={surveyName} onChange={e=>setSurveyName(e.target.value)} disabled={busy||active||importing}/></label></div>
    <div className="survey-upload-row">
      <div className="survey-recording-input"><div className="survey-file">{busy?'Decoding recording…':'Load SonarView recording'}<input ref={recordingInput} className="survey-native-file" aria-label="Load SonarView recording" type="file" accept=".svlz,.svlog" disabled={busy||importing||active} onChange={e=>{if(e.target.files?.[0])void load(e.target.files[0]);e.target.value='';}}/><button type="button" className={`survey-file-button${selectedFilename?' is-selected':''}`} disabled={busy||importing||active} onClick={()=>recordingInput.current?.click()}>{selectedFilename?'File selected':'Choose file'}</button>{selectedFilename&&<small className="survey-selected-file">Selected file: {selectedFilename}</small>}</div>
      <small>Maximum file size: {uploadLimit/1024**3} GB (.svlz / .svlog)</small></div>
    <div className="survey-controls survey-playback-controls">
      <button disabled={!replay||busy} onClick={togglePlayback}>{playing?'Pause':'Play & process'}</button>
      <button disabled={!replay||importing||active} onClick={resetRun}>Reset processing run</button>
      <label>Speed <select aria-label="Playback speed" value={speed} onChange={e=>setSpeed(Number(e.target.value))}>{[1,5,10,30,60].map(s=><option key={s} value={s}>{s}×</option>)}</select></label>
      <label>Grid <select aria-label="Grid size" value={size} disabled={importing||active} onChange={e=>{generation.current++;const next=Number(e.target.value);setSize(next);setJobs(replay?savedJobs(replay.id,next):{});setFreshRun(replay?localStorage.getItem(`reef-survey-fresh:${replay.id}:${next}`)==='true':false);setSelected('');setAuto(false);setRunStarted(false);}}>{[25,50,100,200].map(s=><option key={s} value={s}>{s} × {s} m</option>)}</select></label>
      <label><input type="checkbox" checked={auto} onChange={e=>setAuto(e.target.checked)}/> Auto-process ready blocks</label>
    </div>
    </div>
    </div>
    {error&&<p role="alert" className="survey-warning">{error}</p>}
    {replay&&<p className="survey-note" role="status">
      <strong>{playing?'Playing':cursor>=replay.duration?'Playback finished':'Playback paused'} {Math.floor(100*cursor/Math.max(1,replay.duration))}% ({Math.floor(cursor)} / {replay.duration} s)</strong><br/>
      {state.blocks.filter(b=>mapJobs[b.key]?.status==='completed' && mapJobs[b.key]?.until>=b.last).length} / {state.blocks.length} received cells processed | {state.blocks.filter(b=>!canProcess(b)).length} too sparse for a surface | {Object.values(jobs).filter(j=>j.status==='failed').length} failed
      {cursor>=replay.duration && auto && (active||importing||state.blocks.some(b=>needsProcessing(b,jobs[b.key],cursor,replay.duration)))?' | Processing remaining cells...':playing&&!active&&!importing?' | Collecting measurements; partial cells finish processing at the end.':''}
    </p>}
    <div className="survey-timeline"><input aria-label="Playback position" type="range" min="0" max={replay?.duration||1} value={cursor} step="1" disabled={!replay||importing} onChange={e=>{setCursor(Number(e.target.value));setPlaying(false);setAuto(false);}}/><time>{stamp?stamp.toISOString().replace('T',' ').slice(0,19)+' UTC':'Load a recording to begin'}</time></div>
    <div className="survey-controls">
      <button disabled={!replay||openingArea||(multiSelect&&!selectedCells.length)} onClick={()=>{if(multiSelect){void openSelectedArea();}else{setMultiSelect(true);setSelectedCells([]);setError('');}}}>{openingArea?'Preparing combined reef...':multiSelect?'Open selected area':'Select multiple cells'}</button>
      {multiSelect&&<><span role="status">Selected: {selectedCells.length} / {MAX_SELECTED_CELLS}</span>
        <button onClick={()=>setSelectedCells([])} disabled={!selectedCells.length}>Clear selection</button>
        <button disabled={openingArea} onClick={()=>{setMultiSelect(false);setSelectedCells([]);}}>Cancel selection</button>
        {selectedCells.length===MAX_SELECTED_CELLS&&<span>Limit reached. Deselect a cell to choose another.</span>}
      </>}
    </div>
    <div><div className="survey-layout">
      <div><SurveyMap replay={replay} blocks={state.blocks} boat={state.boat} track={state.track} selected={selected} select={selectCell} jobs={mapJobs} visible={visible} size={size} multiSelect={multiSelect} selectedCells={selectedCells} conditions={{
          windFrom:conditions?.weather?.hourly?.wind_direction_10m?.[hour],
          windSpeed:conditions?.weather?.hourly?.wind_speed_10m?.[hour],
          windUnit:conditions?.weather?.units?.wind_speed_10m,
          waveHeight:conditions?.marine?.hourly?.wave_height?.[hour],
        }}/>
        <div className="survey-legend"><span>● Amber: partial/new measurements</span><span>● Violet: processing</span><span>● Teal: processed snapshot</span><span>Blank space: no survey measurements</span></div>
      </div>
      <aside className="survey-sidebar">
        <h3>Survey feed</h3><p>{replay?.name||'No recording loaded'}</p>
        <dl><dt>Received blocks</dt><dd>{state.blocks.length}</dd><dt>Playback</dt><dd>{Math.floor(cursor)} / {replay?.duration||0} s</dd><dt>Boat heading</dt><dd>{state.boat?`${state.boat[2]}°`:'—'}</dd><dt>Navigation age</dt><dd>{state.boat?`${Math.max(0,Math.floor(cursor-state.boatTime))} s`:'—'}</dd></dl>
        <h3>Onboard motion</h3>
        <p>Recorded IMU attitude ? degrees</p>
        {motion?<><dl>
          <dt>Roll (side to side)</dt><dd>{motion.roll.toFixed(1)}?</dd>
          <dt>Pitch (bow up/down)</dt><dd>{motion.pitch.toFixed(1)}?</dd>
          <dt>Roll variation</dt><dd>{motion.rollVariation.toFixed(1)}? RMS</dd>
          <dt>Pitch variation</dt><dd>{motion.pitchVariation.toFixed(1)}? RMS</dd>
        </dl><small>{motion.seconds} / 30 seconds with data ? {motion.n.toLocaleString()} samples. Variation removes mean tilt. Boat motion, not measured wave height; manoeuvres can contribute.</small></>:<p>{motionStatus}</p>}
        <h3>Historical conditions</h3><p>{day||'Survey date'} · hourly model estimates</p>
        <dl><dt>Wind</dt><dd>{condition('weather','wind_speed_10m')}</dd><dt>Wind direction</dt><dd>{condition('weather','wind_direction_10m')}</dd><dt>Air temperature</dt><dd>{condition('weather','temperature_2m')}</dd><dt>Wave height</dt><dd>{condition('marine','wave_height')}</dd><dt>Wave period</dt><dd>{condition('marine','wave_period')}</dd><dt>Swell height</dt><dd>{condition('marine','swell_wave_height')}</dd></dl>
        {conditions?.warnings?.map((w:string)=><p key={w} className="survey-warning">{w}</p>)}
        <small><a href="https://open-meteo.com/" target="_blank" rel="noreferrer">Open-Meteo</a> / ECMWF ERA5. Regional conditions, not onboard observations.</small>
        <h3>{block?`Block ${block.column}, ${block.row}`:'Select a survey block'}</h3>
        {block&&<><dl><dt>Occupied 5 m cells</dt><dd>{Math.round(block.coverage*100)}%</dd><dt>Measured 1 m bins</dt><dd>{block.points.length}</dd><dt>Soundings</dt><dd>{block.samples.toLocaleString()}</dd></dl>
          <button onClick={download}>Download XYZ</button>
          <button disabled={!canProcess(block)||importing||active} onClick={()=>void process(block)}>Process current measurements</button>
          {jobs[block.key]&&<p>{jobs[block.key].status} {jobs[block.key].progress??0}%{jobs[block.key].samples!==block.samples?' · different from cursor snapshot':''}</p>}
          {mapJobs[block.key]?.result_processed_dataset_id&&<button onClick={()=>openProcessed(mapJobs[block.key].result_processed_dataset_id!)}>Open processed reef</button>}
          {!canProcess(block)&&<p>Points are available now. Surface processing needs four points spread across both axes.</p>}
        </>}
      </aside>
    </div></div>
    <p className="survey-note">Play processes ready cells as data arrives, then processes every usable partial cell at the end. Click a cell with a saved result to open its latest processed dataset. Reset clears the map selection and processed count, then rewinds the feed for a new run; existing files stay available under Browse completed files and previous results. Re-uploading identical recordings reuses the survey; processing updates existing cell results. Processing continues while you inspect a dataset.</p>
    {replay&&<details><summary>Recording quality and processing notes ({replay.warnings.length})</summary><ul>{replay.warnings.map(w=><li key={w}>{w}</li>)}</ul><p>{replay.reduction}. Reef analysis remains provisional; mesh faces are limited to supported areas, while legacy metrics use an interpolated grid.</p></details>}
    <details open={showResults} onToggle={e=>setShowResults(e.currentTarget.open)}><summary>Browse completed files and previous results</summary>{showResults&&<CompletedResults visible={visible} openProcessed={openProcessed}/>}</details>
  </div>;
}
