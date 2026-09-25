const approvals = new Set<string>();
export function approveRunKey(key:string){approvals.add(key);}
export function clearOverwriteApprovals(){approvals.clear();}
export function confirmAction(message:string):Promise<boolean>{
  return new Promise(resolve=>{
    const dialog=document.createElement('dialog');
    dialog.className='survey-confirm-dialog';
    const text=document.createElement('p');text.textContent=message;
    const actions=document.createElement('div');actions.className='survey-controls';
    const yes=document.createElement('button');yes.textContent='Yes';
    const no=document.createElement('button');no.textContent='No';
    const finish=(value:boolean)=>{dialog.close();dialog.remove();resolve(value);};
    yes.onclick=()=>finish(true);no.onclick=()=>finish(false);
    dialog.oncancel=e=>{e.preventDefault();finish(false);};
    actions.append(no,yes);dialog.append(text,actions);document.body.append(dialog);dialog.showModal();no.focus();
  });
}
export async function approveOverwrite(key:string,processedAt:string){
  if(approvals.has(key))return true;
  const date=new Date(processedAt.replace(' ','T'));
  const when=Number.isNaN(date.getTime())?processedAt:date.toLocaleString();
  if(!await confirmAction(`Survey processed before on ${when}. Are you sure you want to overwrite?`))return false;
  approvals.add(key);return true;
}
export async function confirmedFetch(url:string,init:RequestInit={}){
  const response=await fetch(url,init);
  if(response.status!==409)return response;
  const problem=await response.clone().json().catch(()=>null);
  const detail=problem?.detail;
  if(detail?.code!=='overwrite_confirmation_required')return response;
  const key=detail.confirmation_key;
  if(!await approveOverwrite(key,detail.processed_at))throw new Error('Overwrite cancelled. Existing survey unchanged.');
  return fetch(url,{...init,headers:{...Object.fromEntries(new Headers(init.headers).entries()),'X-Confirm-Overwrite':'true'}});
}
