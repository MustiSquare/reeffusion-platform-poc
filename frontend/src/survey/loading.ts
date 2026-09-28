import { assetUrl, getJson } from '../api/client';
import { approveOverwrite } from '../api/confirm';
export type Loading = {percent:number;stage:string};
export function watchLoading(id:string, update:(v:Loading)=>void){
  let stopped=false, pending=false;
  const timer=setInterval(async()=>{
    if(pending)return; pending=true;
    try{const p=await getJson(`/api/survey/loading/${id}`);if(!stopped&&typeof p.percent==='number'&&p.percent>0)update(p);}catch{}finally{pending=false;}
  },1000);
  return ()=>{stopped=true;clearInterval(timer);};
}
export async function uploadRecording(fd:FormData, update:(v:Loading)=>void, signal?:AbortSignal){
  async function attempt(confirmed:boolean):Promise<any>{
    if(signal?.aborted)throw new Error('Loading cancelled');
    const id=crypto.randomUUID();update({percent:0,stage:confirmed?'Uploading confirmed recording':'Uploading recording'});
    const stop=watchLoading(id,update);
    let result:{status:number;body:any};
    let removeAbort=()=>{};
    try{result=await new Promise((resolve,reject)=>{
      const xhr=new XMLHttpRequest();xhr.open('POST',assetUrl(`/api/survey/replays?lightweight=true&progress_id=${id}`));
      if(confirmed)xhr.setRequestHeader('X-Confirm-Overwrite','true');
      const abort=()=>xhr.abort();signal?.addEventListener('abort',abort);removeAbort=()=>signal?.removeEventListener('abort',abort);
      xhr.onabort=()=>reject(new Error('Loading cancelled'));
      xhr.upload.onprogress=e=>{if(e.lengthComputable)update({percent:25*e.loaded/e.total,stage:'Uploading recording'});};
      xhr.onerror=()=>reject(new Error('Recording upload failed. Check your connection and retry.'));
      xhr.onload=()=>{try{resolve({status:xhr.status,body:JSON.parse(xhr.responseText)});}catch{reject(new Error('Invalid recording response'));}};
      xhr.send(fd);
    });}finally{stop();removeAbort();}
    if(result.status===409&&result.body.detail?.code==='overwrite_confirmation_required'){
      const d=result.body.detail;
      if(!confirmed&&await approveOverwrite(d.confirmation_key,d.processed_at))return attempt(true);
      throw new Error('Overwrite cancelled. Existing survey unchanged.');
    }
    if(result.status>=400)throw new Error(typeof result.body.detail==='string'?result.body.detail:JSON.stringify(result.body));
    return result.body;
  }
  return attempt(false);
}
