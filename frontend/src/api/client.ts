import { confirmedFetch } from './confirm';
const API = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000';
export async function getJson(path:string){ const r=await fetch(`${API}${path}`); if(!r.ok) throw new Error(await r.text()); return r.json(); }
export async function postJson(path:string, body:any={}){ const r=await confirmedFetch(`${API}${path}`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)}); if(!r.ok) throw new Error(await r.text()); return r.json(); }
export async function putJson(path:string, body:any={}){ const r=await fetch(`${API}${path}`,{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)}); if(!r.ok) throw new Error(await r.text()); return r.json(); }
export async function deleteJson(path:string){ const r=await fetch(`${API}${path}`,{method:'DELETE'}); if(!r.ok) throw new Error(await r.text()); return r.json(); }
export async function uploadFiles(files:FileList, metadata:Record<string,string>={}){ const fd=new FormData(); Array.from(files).forEach(f=>fd.append('files',f)); Object.entries(metadata).forEach(([k,v])=>{ if(v) fd.append(k,v); }); const r=await confirmedFetch(`${API}/api/datasets/upload`,{method:'POST',body:fd}); if(!r.ok) throw new Error(await r.text()); return r.json(); }
export const assetUrl=(url:string)=> url.startsWith('http')?url:`${API}${url}`;
