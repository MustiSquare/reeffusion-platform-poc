import { afterEach, expect, it, vi } from 'vitest';
import { watchLoading, uploadRecording } from './loading';
vi.mock('../api/client',()=>({assetUrl:(x:string)=>x,getJson:vi.fn()}));
import { getJson } from '../api/client';
afterEach(()=>{vi.useRealTimers();vi.unstubAllGlobals();});
it('polls measured progress and stops after disposal',async()=>{
  vi.useFakeTimers();vi.mocked(getJson).mockResolvedValue({percent:64,stage:'Decoding'});
  const update=vi.fn(),stop=watchLoading('id',update);
  await vi.advanceTimersByTimeAsync(1000);expect(update).toHaveBeenCalledWith({percent:64,stage:'Decoding'});
  stop();update.mockClear();await vi.advanceTimersByTimeAsync(2000);expect(update).not.toHaveBeenCalled();
});
it('uses upload events and returns the decoded replay',async()=>{
  class XHR {
    upload:any={};status=200;responseText='{"id":"survey"}';onload=()=>{};
    open=vi.fn();setRequestHeader=vi.fn();
    send(){this.upload.onprogress({lengthComputable:true,loaded:50,total:100});this.onload();}
  }
  vi.stubGlobal('XMLHttpRequest',XHR);const update=vi.fn();
  expect(await uploadRecording(new FormData(),update)).toEqual({id:'survey'});
  expect(update).toHaveBeenCalledWith({percent:12.5,stage:'Uploading recording'});
});
