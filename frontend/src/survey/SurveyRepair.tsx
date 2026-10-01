import {useEffect,useRef,useState} from 'react';
import {getJson,postJson} from '../api/client';

export default function SurveyRepair({surveyId,disabled=false,onComplete}:{surveyId:string;disabled?:boolean;onComplete?:()=>void}){
  const [state,setState]=useState<any>(null),[error,setError]=useState(''),[requesting,setRequesting]=useState(false);
  const notified=useRef(false),callback=useRef(onComplete);callback.current=onComplete;
  const active=state?.status==='queued'||state?.status==='preparing';
  const path=`/api/survey/archive/${surveyId}/repair`;
  useEffect(()=>{
    let cancelled=false;let timer:ReturnType<typeof setTimeout>;
    async function poll(){
      try{
        const data=await getJson(path);if(cancelled)return;
        setState(data);setError('');
        if(data.status==='queued'||data.status==='preparing')timer=setTimeout(poll,2000);
        if(data.status==='completed'&&notified.current){notified.current=false;callback.current?.();}
      }catch(e:any){if(!cancelled){setError(e.message);timer=setTimeout(poll,5000);}}
    }
    void poll();return()=>{cancelled=true;clearTimeout(timer);};
  },[path,active]);
  async function start(){
    setRequesting(true);setError('');
    try{setState(await postJson(path));notified.current=true;}catch(e:any){setError(e.message);}finally{setRequesting(false);}
  }
  return <div className="survey-xyz-export">
    {state?.status!=='completed'&&<button disabled={disabled||requesting||active||!state||state.status==='unavailable'} onClick={()=>void start()}>
      {active?'Rebuilding survey…':state?.status==='failed'?'Retry coordinate rebuild':'Rebuild survey coordinates'}
    </button>}
    <span role="status">{active?`${state.percent||0}% · ${state.stage}`:state?.status==='completed'
      ?`Corrected coordinates · ${state.cells} cells · ${state.point_count?.toLocaleString()} detections${state.partial?' · Partial recording':''}`
      :state?.status==='unavailable'?state.reason:'Legacy coverage may need rebuilding from the original recording.'}</span>
    {state?.sparse_cells>0&&<small>{state.sparse_cells} cells have too few measurements for a surface; detections remain in the coverage overlay.</small>}
    {state?.warnings?.map((w:string)=><small key={w}>{w}</small>)}
    {(error||state?.error)&&<small role="alert">{error||state.error}</small>}
  </div>;
}
