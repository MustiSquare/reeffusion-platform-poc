import { useEffect, useState } from 'react';
import { assetUrl, getJson, postJson } from '../api/client';

export default function CompletedResults({visible,openProcessed}:{visible:boolean;openProcessed:(id:string)=>void}) {
  const [results,setResults]=useState<any[]>([]),[error,setError]=useState(''),[saving,setSaving]=useState('');
  async function reload(){
    try{const data=await getJson('/api/survey/results');setResults(Array.isArray(data)?data:[]);setError('');}
    catch(e){setError(String(e));}
  }
  useEffect(()=>{
    if(!visible)return;
    let cancelled=false;
    const update=async()=>{try{const data=await getJson('/api/survey/results');if(!cancelled){setResults(Array.isArray(data)?data:[]);setError('');}}catch(e){if(!cancelled)setError(String(e));}};
    void update();const timer=setInterval(update,3000);
    return()=>{cancelled=true;clearInterval(timer);};
  },[visible]);
  async function save(id:string){setSaving(id);try{await postJson(`/api/survey/results/${id}/export`);await reload();}catch(e){setError(String(e));}finally{setSaving('');}}
  return <section className="survey-results" aria-label="Completed survey results">
    <div className="survey-heading"><h3>Completed results ({results.length})</h3><button onClick={reload}>Refresh results</button></div>
    <p>Latest 100 completed datasets. Files are saved under test_data using the survey date (UTC).</p>
    {error&&<p role="alert" className="survey-warning">{error}</p>}
    {!results.length&&<p>No completed datasets yet. Playback displays measurements; select a block and process it, or enable automatic processing.</p>}
    {results.map(result=><details key={result.id} className="survey-result" open={results.length===1}>
      <summary>{result.name} · {result.files.length} output files · {result.export.status==='saved'?'Saved to disk':'Local save needed'}</summary>
      <button onClick={()=>openProcessed(result.id)}>Open processed dataset</button>
      {result.export.status==='saved'?<p>Folder: <code>test_data/{result.export.relative_path}</code></p>:<><p className="survey-warning">{result.export.error||'This older result has not yet been saved to the local folder.'}</p><button disabled={!!saving} onClick={()=>void save(result.id)}>{saving===result.id?'Saving…':'Save to dated folder'}</button></>}
      <ul>{result.files.map((file:any)=><li key={file.url}><a href={assetUrl(file.url)} download={file.name}>{file.name}</a> <small>{file.asset_type}</small></li>)}</ul>
      {result.export.status==='saved'&&<p>The folder also contains source bathymetry (when available) and metadata.json with coordinates, quality notes and checksums.</p>}
    </details>)}
  </section>;
}
