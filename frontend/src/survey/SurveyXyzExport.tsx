import {useEffect, useState} from 'react';
import {assetUrl, getJson, postJson} from '../api/client';

type ExportState = {
  status: 'idle'|'queued'|'preparing'|'completed'|'failed'|'unavailable';
  percent?: number; stage?: string; point_count?: number; partial?: boolean;
  warnings?: string[]; reason?: string; error?: string;
};

export default function SurveyXyzExport({surveyId, disabled=false}:{surveyId:string;disabled?:boolean}){
  const path=`/api/survey/archive/${surveyId}/xyz-export`;
  const [state,setState]=useState<ExportState|null>(null);
  const [requesting,setRequesting]=useState(false);
  const [error,setError]=useState('');
  const active=state?.status==='queued'||state?.status==='preparing';
  useEffect(()=>{
    let cancelled=false;
    let timer:ReturnType<typeof setTimeout>;
    async function poll(){
      try{
        const next:ExportState=await getJson(path);
        if(cancelled)return;
        setState(next);setError('');
        if(next.status==='queued'||next.status==='preparing')timer=setTimeout(poll,1500);
      }catch(e:any){
        if(!cancelled){setError(e.message);timer=setTimeout(poll,5000);}
      }
    }
    void poll();
    return()=>{cancelled=true;clearTimeout(timer);};
  },[path,active]);
  async function prepare(){
    setRequesting(true);setError('');
    try{setState(await postJson(path));}
    catch(e:any){setError(e.message);}
    finally{setRequesting(false);}
  }
  return <div className="survey-xyz-export">
    {state?.status==='completed'
      ? <a href={assetUrl(`${path}/download`)}>{state.partial?'Download partial CSV':'Download XYZ CSV'}</a>
      : <button disabled={disabled||requesting||active||!state||state.status==='unavailable'} onClick={()=>void prepare()}>
          {requesting||active?'Preparing XYZ CSV…':state?.status==='failed'?'Retry XYZ export':'Export XYZ CSV'}
        </button>}
    <span role="status" aria-live="polite">
      {!state&&!error&&' Checking original recording…'}
      {active&&` ${Math.round(state?.percent||0)}% · ${state?.stage||'Preparing'}`}
      {state?.status==='completed'&&` ${state.point_count?.toLocaleString()} ${state.partial?'recovered':'valid'} detections${state.partial?' · Partial recording':''}`}
      {state?.status==='unavailable'&&` ${state.reason}`}
    </span>
    {state?.warnings?.map((warning,i)=><small className="survey-export-warning" key={i}>{warning}</small>)}
    {(error||state?.error)&&<small role="alert">{error||state?.error}</small>}
  </div>;
}
