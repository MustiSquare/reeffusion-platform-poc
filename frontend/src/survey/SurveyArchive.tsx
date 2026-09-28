import SurveyTiming from './SurveyTiming';
import { useEffect, useState } from 'react';
import { getJson, deleteJson, putJson, assetUrl } from '../api/client';
import {WorldThumbnail, ArchiveConditions} from './ArchiveExplorer';
import RegionalThumbnail from './RegionalThumbnail';
import {archiveAreas,areaLabel,areaLocation} from './archiveAreas';
import { confirmAction } from '../api/confirm';

function Files({dataset,kind}:{dataset:any;kind:string}){
  const [assets,setAssets]=useState<any[]>([]),[error,setError]=useState('');
  useEffect(()=>{let cancelled=false;getJson(`/api/datasets/${kind}/${dataset.id}`).then(d=>{if(!cancelled)setAssets(d.assets||[]);}).catch(e=>{if(!cancelled)setError(e.message);});return()=>{cancelled=true;};},[dataset.id,kind]);
  return <>{error&&<p role="alert">{error}</p>}<ul className="archive-files">{assets.map(a=><li key={a.id}><a href={assetUrl(a.url)} target="_blank" rel="noreferrer">{a.file_name}</a></li>)}</ul></>;
}
export default function SurveyArchive({raw,proc,open,openRaw,openSurvey,onSurveyDeleted,refresh}:any){
  const [expanded,setExpanded]=useState<string|null>(null),[busy,setBusy]=useState(false),[error,setError]=useState('');
  const [renaming,setRenaming]=useState<string|null>(null),[name,setName]=useState('');
  const [expandedArea,setExpandedArea]=useState<string|null>(null);
  const [groups,setGroups]=useState<any[]>([]);
  useEffect(()=>{let cancelled=false;getJson('/api/survey/archive').then(data=>{if(!cancelled)setGroups(data);}).catch(e=>{if(!cancelled)setError(e.message);});return()=>{cancelled=true;};},[raw,proc]);
  async function rename(group:any){
    const trimmed=name.trim();if(!trimmed||trimmed.length>30)return;
    setBusy(true);setError('');
    try{
      const result=await putJson(`/api/survey/archive/${group.id}/name`,{name:trimmed});
      setGroups(current=>current.map(g=>g.id===group.id?{...g,name:result.name}:g));
      setRenaming(null);await refresh();
    }catch(e:any){setError(e.message);}finally{setBusy(false);}
  }
  async function remove(dataset:any,kind:string){
    if(!await confirmAction(`Delete ${dataset.name}? This permanently removes its database entry, stored files and local exports${kind==='raw'?', its processed results':''}, and any combined views that use it.`))return;
    setBusy(true);setError('');
    try{await deleteJson(`/api/datasets/${kind}/${dataset.id}`);await refresh();}
    catch(e:any){setError(e.message);}finally{setBusy(false);}
  }
  async function removeSurvey(group:any){
    if(!await confirmAction(`Delete entire survey "${group.name}"? Proceeding will permanently lose all data stored for this survey, including raw recordings, processed cells, files, annotations and combined views that use it. Continue?`))return;
    setBusy(true);setError('');
    try{
      const result=await deleteJson(`/api/survey/archive/${group.id}?confirmed=true`);
      setGroups(current=>current.filter(g=>g.id!==group.id));setExpanded(null);
      onSurveyDeleted?.(result);await refresh();
    }catch(e:any){setError(e.message);}finally{setBusy(false);}
  }
  return <div className="survey-archive"><h2>Data Archive</h2><p>Choose a survey to show its raw datasets and processed files.</p>
    {error&&<p role="alert">{error}</p>}
    {!groups.length&&<p>No archived surveys.</p>}
    {archiveAreas(groups).map(areaGroup=><section className="archive-area" key={areaGroup.id}>
      <div className="archive-area-heading">
        <div className="archive-thumbnails"><WorldThumbnail location={areaLocation(areaGroup.area)}/><RegionalThumbnail area={areaGroup.area} members={areaGroup.surveys.flatMap(s=>s.area_memberships||[])}/></div>
        <button aria-expanded={expandedArea===areaGroup.id} onClick={()=>{setExpandedArea(expandedArea===areaGroup.id?null:areaGroup.id);setExpanded(null);setRenaming(null);}}>
          <strong>{areaLabel(areaGroup.area)}</strong><small>{areaGroup.surveys.length} {areaGroup.surveys.length===1?'survey':'surveys'}{areaGroup.area?' · 10 × 10 km area':''}</small>
        </button>
      </div>
      {expandedArea===areaGroup.id&&areaGroup.surveys.map(group=><section className="archive-survey" key={group.id}>
      <SurveyTiming survey={group}/>
      <div className="archive-row-heading">
        <div className="archive-thumbnails"><RegionalThumbnail area={areaGroup.area} members={group.area_memberships||[]}/></div>
      <button className="archive-survey-heading" aria-expanded={expanded===group.id} onClick={()=>setExpanded(expanded===group.id?null:group.id)}>
        <span>{expanded===group.id?'−':'+'} {group.name}<small style={{display:'block'}}>{group.started_at?new Date(group.started_at).toLocaleString('en-GB',{timeZone:'UTC'})+' UTC':'Survey date unavailable'}{group.duration_seconds!=null?` · ${(group.duration_seconds/60).toFixed(1)} min recorded`:''}</small><small style={{display:'block'}}>{group.processed_cells} processed / {group.received_cells} received cells · {group.grids.map((g:any)=>`${g.size} m × ${g.size} m (${g.processed}/${g.received})`).join(', ')||'Grid size unavailable'}</small></span>
      </button>
      </div>
      <ArchiveConditions id={group.id}/>
      <div className="archive-survey-actions">
      <button disabled={busy||!group.processed_cells} title={!group.processed_cells?'Process survey data first':undefined} onClick={()=>openSurvey?.(group.id)}>Open survey map</button>
      <button disabled={busy} onClick={()=>{setRenaming(group.id);setName(group.name);setError('');}}>Rename</button>
      <button className="archive-delete-survey" disabled={busy} onClick={()=>removeSurvey(group)}>Delete entire survey</button>
      </div>
      {renaming===group.id&&<form onSubmit={e=>{e.preventDefault();void rename(group);}} className="survey-controls">
        <label>Survey name<input aria-label="New survey name" autoFocus maxLength={30} value={name} onChange={e=>setName(e.target.value)} disabled={busy}/><small>{name.length}/30 characters</small></label>
        <button type="submit" disabled={busy||!name.trim()||name.trim().length>30}>Save name</button>
        <button type="button" disabled={busy} onClick={()=>setRenaming(null)}>Cancel</button>
      </form>}
      {!group.processed_cells&&<small>Process survey data before opening the map.</small>}
      {expanded===group.id&&<div className="archive-survey-content">{(['raw','processed'] as const).map(kind=><div key={kind}><h3>{kind==='raw'?'Raw datasets':'Processed datasets and files'}</h3>
        {group[kind].map((dataset:any)=><article className="archive-dataset" key={dataset.id}>
          <div className="archive-dataset-heading"><strong>{dataset.name}</strong><div><button disabled={busy||(kind==='processed'&&dataset.status!=='completed')} onClick={()=>kind==='raw'?openRaw(dataset):open(dataset,group.id)}>Open</button><button disabled={busy} onClick={()=>remove(dataset,kind)}>Delete</button></div></div>
          <Files dataset={dataset} kind={kind}/>
        </article>)}
      </div>)}</div>}
    </section>)}
    </section>)}
  </div>;
}
