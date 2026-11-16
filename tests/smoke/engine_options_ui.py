"""The engine's "Advanced settings" in the interface, for llama.cpp, Strata and Strata Rust.

    .venv\\Scripts\\python tests\\smoke\\engine_options_ui.py --model small.gguf

In the bundled headless browser: the engine card's "Advanced settings" button opens the engine options
under the card (as it does for Project Maya); every option of the installed engine is shown; a change
is saved in the core's model preferences and an invalid value is marked; the texts follow the
interface language; screenshots in the dark and light themes go to build/engine-options-ui/.
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

OUT = ROOT / 'build' / 'engine-options-ui'
OPEN = """const w=ms=>new Promise(r=>setTimeout(r,ms));const $=id=>document.getElementById(id);
if(!window.VALWindows?.isOpen('model'))$('modelBtn').click();await w(1200);
const button=$('mayaQuickAdvanced');if(!button||button.hidden)return {error:'no Advanced settings button'};
const box=$('engineOptions');if(box.hidden||!box.open)button.click();
for(let k=0;k<40&&!document.querySelector('#engineOptionsBody .engine-option');k++)await w(250);
const rect=box.getBoundingClientRect(),card=document.querySelector('.engine-quick').getBoundingClientRect();
return {visible:!!box.offsetParent&&rect.height>40,rows:document.querySelectorAll('#engineOptionsBody .engine-option').length,
  groups:[...document.querySelectorAll('#engineOptionsBody h5')].map(h=>h.textContent),title:$('engineOptionsTitle').textContent,
  first:document.querySelector('#engineOptionsBody .engine-option label')?.textContent,below_card:rect.top>=card.bottom-1,
  expanded:button.getAttribute('aria-expanded'),button:button.textContent.trim()};"""


async def run(core, model):
    rows = []

    def check(name, ok, detail=''):
        rows.append(ok)
        print(f"  {'OK  ' if ok else 'FAIL'} {name}" + (f' — {str(detail)[:220]}' if detail else ''), flush=True)

    OUT.mkdir(parents=True, exist_ok=True)
    async with Browser(1280, 900) as browser:
        async def shot(name):
            data = await browser.call('Page.captureScreenshot', {'format': 'png'})
            (OUT / f'{name}.png').write_bytes(base64.b64decode(data['data']))

        await browser.open(core.base + '/')
        await browser.run("""const w=ms=>new Promise(r=>setTimeout(r,ms));document.getElementById('modelBtn').click();await w(900);
            document.getElementById('modelChooser').click();await w(400);
            document.querySelector('#modelResults .model-option')?.click();await w(500);""")
        state = await browser.run(OPEN)
        check('the engine card has "Advanced settings" for llama.cpp and it opens the options under it',
              state.get('rows', 0) > 20 and state.get('visible') and state.get('below_card') and state.get('expanded') == 'true', state)
        await shot('es-dark')
        # A change is saved; an invalid value is marked and not saved.
        result = await browser.run("""const w=ms=>new Promise(r=>setTimeout(r,ms));const $=id=>document.getElementById(id);
            const fa=$('engopt_flash_attn');fa.value='on';fa.dispatchEvent(new Event('change',{bubbles:true}));
            const t=$('engopt_threads');t.value='6';t.dispatchEvent(new Event('change',{bubbles:true}));
            const bad=$('engopt_main_gpu');bad.value='abc';bad.dispatchEvent(new Event('change',{bubbles:true}));
            await w(1500);const still=$('engopt_main_gpu');
            return {invalid:still.getAttribute('aria-invalid'),same_element:still===bad,typed:still.value,status:$('engineOptionsStatus').textContent,count:$('engineOptionsCount').textContent};""")
        saved = (core.get('/api/models').get('models') or [{}])
        prefs = next((m.get('preferences') or {} for m in saved if m.get('id') == model), {})
        check('a change reaches the core and an invalid value is marked, not saved',
              (prefs.get('engine') or {}) == {'flash_attn': 'on', 'threads': 6} and result['invalid'] == 'true' and result['same_element']
              and result['typed'] == 'abc' and 'abc' not in json.dumps(prefs) and 'GPU' in result['status'], [prefs.get('engine'), result])
        # Reload: the saved values are shown again.
        await browser.call('Page.reload', {})
        await asyncio.sleep(4)
        state = await browser.run(OPEN + "")
        values = await browser.run("return {fa:document.getElementById('engopt_flash_attn').value,threads:document.getElementById('engopt_threads').value};")
        check('after reloading, the saved values are shown', values == {'fa': 'on', 'threads': '6'}, values)
        # Languages.
        for lang, expect in (('en', 'Engine options'), ('de', 'Engine-Optionen'), ('fr', 'Options du moteur')):
            await browser.run("""const w=ms=>new Promise(r=>setTimeout(r,ms));const l=document.getElementById('uiLanguage');
                l.value=%s;l.dispatchEvent(new Event('change',{bubbles:true}));await w(1200);""" % json.dumps(lang))
            state = await browser.run(OPEN)
            check(f'texts follow the language ({lang})', state.get('title') == expect and state.get('first') and
                  all(not g.startswith(('Rendimiento', 'Memoria')) for g in state.get('groups', [])), state)
            if lang == 'en':
                await shot('en-dark')
        # Light theme.
        await browser.run("""const w=ms=>new Promise(r=>setTimeout(r,ms));document.getElementById('themeBtn').click();await w(1200);""")
        await browser.run(OPEN)
        colors = await browser.run("""const row=document.querySelector('#engineOptionsBody .engine-option'),help=row.querySelector('.engine-option-help');
            return {bg:getComputedStyle(document.body).backgroundColor,text:getComputedStyle(row.querySelector('label')).color,help:getComputedStyle(help).color};""")
        await shot('fr-light')
        check('the light theme applies to the options', colors['text'] != colors['bg'], colors)
        check('no page errors', not browser.errors, browser.errors[:2] or 'none')
    return rows


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--model', required=True)
    args = parser.parse_args()
    with IsolatedCore(19372, r'%LOCALAPPDATA%\V-Agent-Data') as core:
        core.post('/api/harness/configure', {'engine': 'llama', 'variant': 'cuda'})
        model = core.post('/api/models/register', {'path': args.model})['model']['id']
        rows = asyncio.run(run(core, model))
    print(f'\n{len(rows)} checks, {rows.count(False)} failed. Screenshots: {OUT}')
    sys.exit(0 if all(rows) else 1)


if __name__ == '__main__':
    main()
