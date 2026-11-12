"""Use the interface like a person and compare what the screen says with what the core really did.

    .venv\\Scripts\\python tests\\smoke\\ui_consistency.py --model D:\\models\\small.gguf

Starts its own isolated core (see isolated_core.py) with llama.cpp and a small model, opens the
interface in the bundled headless browser and, through clicks only:

- selects and loads the model, changes the context, sends a request and approves its write, stops a
  reply half way, unloads, switches engine, changes response settings, language, deletes a chat;
- after each action compares the screen with the core's own API (loaded model, context limit,
  engine, files on disk, generation state, conversations), and reloads to see what survives;
- watches the whole run with a MutationObserver for status text written into elements nobody can
  see (a message that is hidden is a message the user never gets).

Screenshots of every step go to build/ui-consistency/. Exit code 1 when any check fails.
"""
import argparse
import asyncio
import base64
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from headless import ROOT, Browser  # noqa: E402
from isolated_core import IsolatedCore  # noqa: E402

HELPERS = r"""
window.w=ms=>new Promise(r=>setTimeout(r,ms));
window.$=id=>document.getElementById(id);
window.t=id=>($(id)?.innerText||$(id)?.textContent||'').trim().replace(/\s+/g,' ');
window.api=async p=>(await fetch(p)).json();
window.openModel=async()=>{if(!$('composerControls').classList.contains('open')&&!window.VALWindows?.isOpen('model')){$('modelBtn').click();await w(900);}};
window.closeAll=async()=>{$('closeControls')?.click();document.querySelectorAll('.fw [data-fw-close]').forEach(b=>b.offsetParent&&b.click());await w(400);};
window.loadState=()=>$('modelLoadState')?.dataset.state||'';
window.busy=()=>!!document.querySelector('#chat [data-generating=true]');
window.approveAll=()=>document.querySelectorAll('dialog.tool-approval[open] .primary').forEach(b=>b.click());
window.send=async(text,limit=300)=>{const i=$('input');i.value=text;i.dispatchEvent(new Event('input',{bubbles:true}));$('send').click();
  for(let k=0;k<limit;k++){await w(400);approveAll();if(k>3&&!busy())break;}await w(800);};
window.chats=()=>[...document.querySelectorAll('#convs .conv')].length;
if(!window.__hidden){window.__hidden={};
  const shown=e=>{for(let x=e;x&&x!==document.body;x=x.parentElement){if(x.hidden)return false;const s=getComputedStyle(x);if(s.display==='none'||s.visibility==='hidden')return false;}const b=e.getBoundingClientRect();return b.width>0&&b.height>0;};
  // A status, warning or error text written into a hidden element while its window is open on
  // screen: the user is looking at that window and never sees the message. Text updated inside a
  // closed window is fine (it shows when the window opens).
  const STATUS=/status|error|warn|notice|hint|toast|note|msg|message/i;
  const PANEL='.fw,dialog,#composerControls,#drawer,[role=dialog],.agent-small-menu';
  new MutationObserver(list=>{for(const m of list){const el=m.type==='characterData'?m.target.parentElement:m.target;
    if(!el||el.closest('#chat,svg,script,style,template,option,select,dialog:not([open])'))continue;
    const text=(el.textContent||'').trim();if(text.length<4||el.children.length>2)continue;
    if(!STATUS.test(el.id+' '+el.className))continue;
    const panel=el.parentElement?.closest(PANEL);
    // Hidden itself while what holds it is on screen (text in a closed tab or window is not counted).
    if(!shown(el)&&el.parentElement&&shown(el.parentElement)&&(panel?shown(panel):true)){const key=el.id?'#'+el.id:el.tagName.toLowerCase()+'.'+String(el.className).split(' ')[0];(window.__hidden[key]??=new Set()).add(text.slice(0,90));}}})
  .observe(document.body,{subtree:true,childList:true,characterData:true});}
"""

# Status areas that are meant to be filled while hidden and shown later by their own panel.
HIDDEN_BY_DESIGN = ('#st-', '#hf', '#settings-', 'div.fw-', '#tourStep', '#tour')


class Run:
    def __init__(self, core, browser, out):
        self.core, self.browser, self.out, self.rows, self.hidden_seen = core, browser, out, [], {}

    def check(self, name, ok, detail=''):
        self.rows.append({'engine': 'interface', 'check': name, 'status': 'pass' if ok else 'fail', 'detail': str(detail)[:300]})
        print(f"  {'OK  ' if ok else 'FAIL'} {name}" + (f' — {detail}' if detail else ''), flush=True)

    async def ui(self, script):
        return await self.browser.run(HELPERS + script)

    async def shot(self, name):
        data = await self.browser.call('Page.captureScreenshot', {'format': 'png'})
        (self.out / f'{len(self.rows):02d}-{name}.png').write_bytes(base64.b64decode(data['data']))

    async def hidden(self):
        found = await self.ui("return Object.fromEntries(Object.entries(window.__hidden||{}).map(([k,v])=>[k,[...v].slice(0,3)]));")
        for key, texts in found.items():
            self.hidden_seen.setdefault(key, set()).update(texts)

    async def reload(self):
        await self.hidden()  # the observer's record does not survive a reload
        await self.browser.call('Page.reload', {})
        await asyncio.sleep(4)
        await self.browser.run("document.querySelector('.update-card-close')?.click();")


async def scenario(core, model_id, out):
    async with Browser() as browser:
        run = Run(core, browser, out)
        await browser.open(core.base + '/')

        screen = await run.ui("return {state:loadState(), button:t('modelBtn')};")
        stats = core.get('/api/stats')
        run.check('start: neither the screen nor the core has a model loaded', not stats.get('loaded') and screen['state'] != 'loaded', screen)

        # Select and load through the model window.
        screen = await run.ui("""await openModel(); $('modelChooser').click(); await w(300);
            const option=[...document.querySelectorAll('#modelResults .model-option')].find(o=>o.innerText.includes(%s));
            if(!option) return {error:'model not listed'}; option.click(); await w(400);
            const c=$('ctxInput'); c.value=8192; c.dispatchEvent(new Event('input',{bubbles:true})); await w(300);
            $('modelSummaryAction').click(); for(let k=0;k<240&&loadState()!=='loaded';k++) await w(500);
            await w(1200); return {state:loadState(), name:t('modelSelectedName'), context:t('ctxValue')};""" % json.dumps(core.model_name))
        stats = core.get('/api/stats')
        await run.shot('loaded')
        run.check('load: the screen says loaded and the core has that model', screen.get('state') == 'loaded' and stats.get('loaded')
                  and stats.get('model') == model_id, f"screen {screen} · core {stats.get('model')}")
        limit = (stats.get('context_usage') or {}).get('limit')
        run.check('load: the context on screen is the engine\'s', limit == 8192 and '8' in screen.get('context', ''), f'core {limit}')

        # Change the context.
        screen = await run.ui("""const c=$('ctxInput'); c.value=10240; c.dispatchEvent(new Event('input',{bubbles:true})); await w(300);
            $('ctxApply').click(); for(let k=0;k<120;k++){await w(500); if(loadState()==='loaded'&&k>4)break;} await w(1500);
            return {state:loadState(), context:t('ctxValue')};""")
        for _ in range(40):  # the engine has just restarted: its numbers arrive with the next poll
            limit = (core.get('/api/stats').get('context_usage') or {}).get('limit')
            if limit:
                break
            await asyncio.sleep(.5)
        run.check('context change reaches the engine', limit == 10240 and screen['state'] == 'loaded', f'core {limit} · screen {screen}')

        # The context changed from outside the window (the API, another client): the window must follow the engine.
        core.post('/api/context', {'model': model_id, 'tokens': 12288}, timeout=600)
        screen = await run.ui("""await closeAll(); await w(3500); await openModel(); await w(600);
            return {context:t('ctxValue'), state:loadState()};""")
        limit = (core.get('/api/stats').get('context_usage') or {}).get('limit')
        digits = ''.join(ch for ch in screen['context'] if ch.isdigit())
        run.check('a context set outside the window is shown as the engine has it', limit == 12288 and digits == '12288',
                  f"core {limit} · screen {screen['context']}")

        # A request that writes a file, approved in the dialog.
        await run.ui("await closeAll(); $('newchat').click(); await w(400);")
        await run.ui("await send('Crea hola.txt con el texto: hola desde la interfaz');")
        await run.shot('file-written')
        written = [p for p in (core.data / 'workspaces').rglob('hola.txt')] if (core.data / 'workspaces').is_dir() else []
        content = written[0].read_text(encoding='utf-8', errors='replace').strip() if written else None
        run.check('a request from the composer writes the file on disk', content is not None and 'hola' in content.lower(),
                  repr(content))

        # Stop a reply half way.
        screen = await run.ui("""const i=$('input'); i.value='Escribe una lista numerada del 1 al 300 con una palabra cada una.';
            i.dispatchEvent(new Event('input',{bubbles:true})); $('send').click(); await w(3000); const during=busy();
            $('send').click(); for(let k=0;k<30&&busy();k++) await w(300); await w(800);
            return {during, after:busy(), label:$('send').getAttribute('aria-label')};""")
        live = (core.get('/api/stats').get('live') or {}).get('state')
        run.check('stop: the screen and the engine both stop', screen['during'] and not screen['after']
                  and live not in ('reading', 'generating', 'decoding'), f'screen {screen} · engine {live}')

        # Response settings survive a reload.
        await run.ui("""$('responseBtn').click(); await w(800); const m=$('p_max'); m.value=777;
            m.dispatchEvent(new Event('input',{bubbles:true})); m.dispatchEvent(new Event('change',{bubbles:true})); await w(900); await closeAll();""")
        await run.reload()
        screen = await run.ui("""await openModel(); const r={state:loadState(), name:t('modelSelectedName')}; await closeAll();
            $('responseBtn').click(); await w(800); r.max=$('p_max').value; await closeAll(); return r;""")
        run.check('reload: the loaded model is still shown as loaded', screen['state'] == 'loaded' and core.get('/api/stats').get('loaded'), screen)
        run.check('reload: the response limit is kept', screen['max'] == '777', screen['max'])

        # Unload.
        screen = await run.ui("""await openModel(); $('modelSummaryAction').click(); for(let k=0;k<60&&loadState()==='loaded';k++) await w(500);
            await w(1000); return {state:loadState()};""")
        run.check('unload: the screen and the core agree', screen['state'] != 'loaded' and not core.get('/api/stats').get('loaded'), screen)

        # Switch engine and back.
        engine = await run.ui("""$('modelEngineOptions').open=true; const k=$('engineKind'); k.value='rust'; k.dispatchEvent(new Event('change',{bubbles:true}));
            await w(300); $('applyEngine').click(); await w(2500); return k.value;""")
        active = core.get('/api/harness/state').get('active')
        run.check('engine switch reaches the core', active == 'rust' == engine, f'screen {engine} · core {active}')
        await run.ui("""const k=$('engineKind'); k.value='llama'; k.dispatchEvent(new Event('change',{bubbles:true})); await w(300);
            $('applyEngine').click(); await w(2500); $('modelEngineOptions').open=false; await closeAll();""")
        run.check('engine switch back reaches the core', core.get('/api/harness/state').get('active') == 'llama')

        # Language survives a reload.
        await run.ui("""$('gear').click(); await w(500); document.querySelector('[data-settings-category=general],[data-category=general]')?.click(); await w(300);
            const l=$('uiLanguage'); l.value='en'; l.dispatchEvent(new Event('change',{bubbles:true})); await w(900); $('gear').click(); await w(300);""")
        await run.reload()
        lang = await run.ui("return document.documentElement.lang;")
        await run.shot('english')
        run.check('language change survives a reload', lang == 'en', lang)
        await run.ui("""$('gear').click(); await w(500); document.querySelector('[data-settings-category=general],[data-category=general]')?.click(); await w(300);
            const l=$('uiLanguage'); l.value='es'; l.dispatchEvent(new Event('change',{bubbles:true})); await w(900); $('gear').click(); await w(300);""")

        # Delete a conversation.
        before = len([s for s in core.get('/api/v1/sessions').get('sessions') or [] if not s.get('deleted')])
        screen = await run.ui("""const n=chats(); const row=document.querySelector('#convs .conv'); row.querySelector('.conv-more').click(); await w(400);
            const item=document.querySelector('#convMenu [data-action=delete]');
            item?.click(); await w(500); const yes=document.querySelector('dialog.val-confirm[open] .danger'); yes?.click(); await w(1000);
            return {before:n, after:chats(), menu:!!item, confirmed:!!yes};""")
        after = len([s for s in core.get('/api/v1/sessions').get('sessions') or [] if not s.get('deleted')])
        run.check('deleting a chat removes it on screen and in the core', screen['after'] == screen['before'] - 1 and after == before - 1,
                  f'screen {screen} · core {before}→{after}')
        await run.reload()
        count = await run.ui("return chats();")
        run.check('reload: the chat list matches the core', count == after, f'screen {count} · core {after}')

        await run.hidden()
        real = {key: sorted(texts)[:3] for key, texts in run.hidden_seen.items() if not key.startswith(HIDDEN_BY_DESIGN)}
        run.check('no status message was written where nobody can see it', not real, real or 'none')
        run.check('no page errors during the run', not browser.errors, browser.errors[:3] or 'none')
        return run.rows


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--model', required=True, help='a small GGUF for llama.cpp')
    parser.add_argument('--engines-from', default=r'%LOCALAPPDATA%\V-Agent-Data')
    parser.add_argument('--out', default=str(ROOT / 'build' / 'ui-consistency'))
    parser.add_argument('--report', help='write the results as JSON here')
    args = parser.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    with IsolatedCore(engines_from=args.engines_from) as core:
        core.post('/api/harness/configure', {'engine': 'llama', 'variant': 'cuda'})
        model = core.post('/api/models/register', {'path': args.model}, timeout=600)['model']
        core.model_name = model.get('name') or Path(args.model).stem
        rows = asyncio.run(scenario(core, model['id'], out))
    failed = [row for row in rows if row['status'] == 'fail']
    print(f'\n{len(rows)} checks, {len(failed)} failed. Screenshots: {out}')
    if args.report:
        Path(args.report).write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding='utf-8')
    sys.exit(1 if failed else 0)


if __name__ == '__main__':
    main()
