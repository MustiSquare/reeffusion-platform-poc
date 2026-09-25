// @vitest-environment jsdom
import {afterEach,beforeEach,expect,it,vi} from 'vitest';
import {screen,fireEvent} from '@testing-library/dom';
import {confirmedFetch,clearOverwriteApprovals} from './confirm';
beforeEach(()=>{HTMLDialogElement.prototype.showModal=vi.fn();HTMLDialogElement.prototype.close=vi.fn();clearOverwriteApprovals();});
afterEach(()=>{document.body.innerHTML='';vi.unstubAllGlobals();});
const conflict=()=>new Response(JSON.stringify({detail:{code:'overwrite_confirmation_required',confirmation_key:'survey',processed_at:'2026-07-10T12:00:00Z'}}),{status:409});
it('No cancels without sending an overwrite request',async()=>{
  const fetch=vi.fn().mockResolvedValue(conflict());vi.stubGlobal('fetch',fetch);
  const pending=confirmedFetch('/upload',{method:'POST'}).catch(e=>e.message);
  fireEvent.click(await screen.findByText('No'));
  expect(await pending).toMatch(/cancelled/);expect(fetch).toHaveBeenCalledTimes(1);
});
it('Yes retries with explicit overwrite confirmation',async()=>{
  const fetch=vi.fn().mockResolvedValueOnce(conflict()).mockResolvedValueOnce(new Response('{}'));vi.stubGlobal('fetch',fetch);
  const pending=confirmedFetch('/upload',{method:'POST'});
  fireEvent.click(await screen.findByText('Yes'));await pending;
  expect(fetch.mock.calls[1][1].headers['X-Confirm-Overwrite']).toBe('true');
});
