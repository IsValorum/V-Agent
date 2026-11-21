"""The "Use model" button with an OpenAI-compatible API (no account: a local fake provider).

    .venv\\Scripts\\python tests\\smoke\\api_use_model_ui.py

Connects an isolated core to a local provider listing two models, opens the interface in the bundled
headless browser, picks each model in the list and presses "Use model": the model must become the one in
use, and switching to the other one must work too. Then the case that left the button dead: a "preparing"
state left over from an earlier load and the hidden Load button disabled; the click must still work.
The same for "Disconnect API". During a reply, buttons that cannot act (file access, approvals, "Add
files") must say why instead of ignoring the click.
"""
import asyncio
import json
import re
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from headless import Browser
from isolated_core import IsolatedCore

MODELS = ['DeepSeek-V4-Pro', 'DeepSeek-V4.1-Flash']
IDS = ['deepseek-v4-pro', 'deepseek-flash']


class Provider(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def _send(self, body, kind='application/json'):
        raw = body.encode()
        self.send_response(200)
        self.send_header('Content-Type', kind)
        self.send_header('Content-Length', str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):
        self._send(json.dumps({'object': 'list', 'data': [{'id': i, 'display_name': m, 'object': 'model', 'owned_by': 'deepseek', 'context_length': 1048576} for i, m in zip(IDS, MODELS)]}))

    def do_POST(self):
        body = self.rfile.read(int(self.headers.get('Content-Length') or 0))
        if b'slow reply' in body:  # a reply that lasts a few seconds, streamed
            self.send_response(200)
            self.send_header('Content-Type', 'text/event-stream')
            self.end_headers()
            for _ in range(12):
                self.wfile.write(('data: ' + json.dumps({'choices': [{'delta': {'content': 'tick '}}]}) + '\n\n').encode())
                self.wfile.flush()
                time.sleep(.5)
            self.wfile.write(('data: ' + json.dumps({'choices': [{'delta': {}, 'finish_reason': 'stop'}]}) + '\n\ndata: [DONE]\n\n').encode())
            return
        packet = {'choices': [{'delta': {'content': 'ok'}, 'finish_reason': 'stop'}]}
        self._send('data: ' + json.dumps(packet) + '\n\ndata: [DONE]\n\n', 'text/event-stream')


PICK = """const w=ms=>new Promise(r=>setTimeout(r,ms));const $=id=>document.getElementById(id);
if(!window.VALWindows?.isOpen('model'))$('modelBtn').click();await w(1200);
const chooser=$('modelChooser');if(chooser&&chooser.getAttribute('aria-expanded')!=='true')chooser.click();await w(500);
const option=[...document.querySelectorAll('#modelResults .model-option')].find(o=>o.textContent.includes(%s));
if(!option)return {error:'model not in the list',list:[...document.querySelectorAll('#modelResults .model-option')].map(o=>o.textContent)};
option.click();await w(600);
const action=$('modelSummaryAction');
if(%s){/* A local load still "preparing" in the core (stuck or left over): in the model list and in the load status. */
  const of=window.fetch;window.__realFetch=of;const stuck={active:true,stage:'loading',model:'llama--old',request_id:'old',revision:1,started_at:Date.now()/1000};
  const reply=body=>new Response(JSON.stringify(body),{status:200,headers:{'Content-Type':'application/json'}});
  window.fetch=async(...a)=>{const r=await of(...a);const u=String(a[0]?.url||a[0]);if(u.includes('/api/load/status'))return reply(stuck);
    if(/[/]api[/]models([?]|$)/.test(u)&&(!a[1]?.method||a[1].method==='GET')){const d=await r.clone().json();d.preparation=stuck;return reply(d);}return r;};
  $('refreshModels')?.click();await w(1500);}
const before={text:action?.textContent,disabled:action?.disabled,hidden:action?.hidden,value:$('model').value,busy:typeof engineBusy!=='undefined'?engineBusy:null};
action.click();
for(let k=0;k<40;k++){await w(250);if(/Dejar de usar|Stop using/.test(action.textContent)&&$('model').value.endsWith(%s))break;}
if(window.__realFetch){window.fetch=window.__realFetch;delete window.__realFetch;}
return {before,after:{text:action.textContent,status:$('modelStatus')?.textContent,value:$('model').value}};"""

STUCK_FETCH = """const of=window.fetch;window.__realFetch=of;const stuck={active:true,stage:'loading',model:'llama--old',request_id:'old',revision:1,started_at:Date.now()/1000};
const reply=body=>new Response(JSON.stringify(body),{status:200,headers:{'Content-Type':'application/json'}});
window.fetch=async(...a)=>{const r=await of(...a);const u=String(a[0]?.url||a[0]);if(u.includes('/api/load/status'))return reply(stuck);
  if(/[/]api[/]models([?]|$)/.test(u)&&(!a[1]?.method||a[1].method==='GET')){const d=await r.clone().json();d.preparation=stuck;return reply(d);}return r;};
$('refreshModels')?.click();await w(1500);"""

POWER = """const w=ms=>new Promise(r=>setTimeout(r,ms));const $=id=>document.getElementById(id);
if(!window.VALWindows?.isOpen('model'))$('modelBtn').click();await w(800);
""" + STUCK_FETCH + """
const t=$('engineToggle');const before=t.textContent;t.click();
for(let k=0;k<40&&!/Conectar API|Connect API/.test(t.textContent);k++)await w(250);const off=/Conectar API|Connect API/.test(t.textContent);
t.click();for(let k=0;k<60&&!/Desconectar API|Disconnect API/.test(t.textContent);k++)await w(250);const on=/Desconectar API|Disconnect API/.test(t.textContent);
window.fetch=window.__realFetch;delete window.__realFetch;return {before,off,on,after:t.textContent,toast:$('toastText').textContent};"""

BUSY = """const w=ms=>new Promise(r=>setTimeout(r,ms));const $=id=>document.getElementById(id);
window.VALWindows?.close?.('model');await w(400);
const input=$('input');input.value='slow reply please';input.dispatchEvent(new Event('input',{bubbles:true}));await w(200);$('send').click();
for(let k=0;k<20&&!/Detener|Stop/i.test($('send').getAttribute('aria-label')||$('send').title||'')&&!$('stop')?.offsetParent;k++)await w(150);await w(800);
const said={};const toast=()=>$('toastText').textContent;
const clickSays=async(name,el)=>{$('toastText').textContent='';el?.click();await w(300);said[name]=el?toast():'(missing)';};
await clickSays('the file-access choice',document.querySelector('#permissionMenu [data-scope=full_pc]'));
await clickSays('the approvals choice',document.querySelector('#permissionMenu [data-mode=ask]'));
await clickSays('"Add files"',$('addFilesMenu'));
for(let k=0;k<60&&$('chatwrap').dataset.generating==='true';k++)await w(250);
return {said};"""


async def run(core):
    ok = []
    async with Browser(1280, 900) as browser:
        await browser.open(core.base + '/')
        await asyncio.sleep(2)
        for name, model_id, stuck in ((MODELS[1], IDS[1], False), (MODELS[0], IDS[0], False), (MODELS[1], IDS[1], True)):
            if stuck:  # from "not in use", as in the report
                await browser.run("const a=document.getElementById('modelSummaryAction');if(/Dejar de usar|Stop using/.test(a.textContent)){a.click();await new Promise(r=>setTimeout(r,2000));}return 1")
            state = await browser.run(PICK % (json.dumps(name), 'true' if stuck else 'false', json.dumps(model_id)))
            after = state.get('after') or {}
            good = bool(re.search('Dejar de usar|Stop using', after.get('text', ''))) and after.get('value', '').endswith(model_id)
            ok.append(good)
            label = ' (a local load still "preparing" in the core)' if stuck else ''
            print(f"  {'OK  ' if good else 'FAIL'} Use model → {name}{label}: {json.dumps(state, ensure_ascii=False)[:400]}", flush=True)
        state = await browser.run(POWER)
        good = state.get('off') and state.get('on')
        ok.append(bool(good))
        print(f"  {'OK  ' if good else 'FAIL'} Disconnect / connect API with a local load still \"preparing\": {json.dumps(state, ensure_ascii=False)[:300]}", flush=True)
        await browser.run(PICK % (json.dumps(MODELS[1]), 'false', json.dumps(IDS[1])))
        state = await browser.run(BUSY)
        for name, said in (state.get('said') or {}).items():
            good = bool(re.search('Espera|Wait', said or ''))
            ok.append(good)
            print(f"  {'OK  ' if good else 'FAIL'} during a reply, {name} says why: {said!r}", flush=True)
        if not state.get('said'):
            ok.append(False)
            print('  FAIL the reply did not start:', state, flush=True)
        errors = await browser.run("return (window.__errors||[]).slice(-5)")
        print('  page errors:', errors)
    return all(ok)


def main():
    server = ThreadingHTTPServer(('127.0.0.1', 0), Provider)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    with IsolatedCore(port=19391) as core:
        # A named, saved connection (its id goes into the model id), as made from "Add or edit connection".
        core.post('/api/harness/configure', {'engine': 'api', 'connection_id': 'b8c94473905a4b99b53ab75b9612c08f', 'name': 'DeepSeek',
                                             'base_url': f'http://127.0.0.1:{server.server_port}/v1', 'api_key': 'fixture-only-key'})
        core.post('/api/harness/connect', {})
        passed = asyncio.run(run(core))
        # A KV cache value left from a local engine must not make the save (and so "Use model") fail.
        status, data = core.request('POST', '/api/models/preferences', {'model': 'api--b8c94473905a4b99b53ab75b9612c08f--' + IDS[0], 'settings': {'kv': 'q8_0'}})
        good = status == 200
        passed = passed and good
        print(f"  {'OK  ' if good else 'FAIL'} preferences with a local KV value on an API model: {status} {str(data)[:200]}", flush=True)
        # A provider model is not "loaded" in memory: it must not block updates with "unload the model".
        status, data = core.request('POST', '/api/harness/app-update', {'action': 'launch'})
        good = 'Descarga el modelo' not in str(data)
        passed = passed and good
        print(f"  {'OK  ' if good else 'FAIL'} app update not blocked by an API model: {status} {str(data)[:200]}", flush=True)
    print('RESULT', 'OK' if passed else 'FAIL')
    sys.exit(0 if passed else 1)


if __name__ == '__main__':
    main()
