"""Find options that are hard to see or reach: small targets, hover-only or faded controls, cut text,
settings buried in folds inside folds, and content outside its window with no way to scroll to it.

    .venv\\Scripts\\python tests\\smoke\\ui_layout_audit.py [--size 800x600]

Opens every window, tab, settings page and menu of the interface in the bundled headless browser
(an isolated core with llama.cpp and a registered model, so the model window is complete) and
measures what is on screen. Screenshots go to build/ui-layout-audit/. Exit code 1 when anything is found.
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

AUDIT = r"""
// A window that is closed (or closing) stays in the page nearly transparent: not "shown".
const shown=e=>{const r=e.getBoundingClientRect();if(r.width<1||r.height<1)return false;for(let x=e;x;x=x.parentElement){const s=getComputedStyle(x);if(s.display==='none'||s.visibility==='hidden'||parseFloat(s.opacity)<0.2)return false;}return true;};
const name=e=>(e.id?'#'+e.id:e.tagName.toLowerCase()+(typeof e.className==='string'&&e.className?'.'+e.className.trim().split(/\s+/)[0]:''))+' «'+(e.getAttribute('aria-label')||e.title||e.innerText||e.value||e.placeholder||'').trim().replace(/\s+/g,' ').slice(0,40)+'»';
const root=document.querySelector(ROOT_SELECTOR)||document.body;
const issues=[];
const opacity=e=>{let o=1;for(let x=e;x;x=x.parentElement)o*=parseFloat(getComputedStyle(x).opacity||1);return o;};
for(const e of root.querySelectorAll('button,a[href],select,input:not([type=hidden]),summary,[role=button],[role=menuitem],[role=menuitemradio],[role=tab],textarea')){
  if(!shown(e)||e.disabled)continue;const r=e.getBoundingClientRect();
  // A checkbox or radio is fine when its label is the target.
  // A checkbox or radio is fine when its label is the target; a slider is a long, thin control by nature.
  const labelled=(e.type==='checkbox'||e.type==='radio')&&e.closest('label')||e.type==='range';
  if(!labelled&&(r.width<24||r.height<20))issues.push(['small target',name(e),Math.round(r.width)+'×'+Math.round(r.height)]);
  const o=opacity(e);if(o<0.6&&!e.closest('[aria-hidden=true]'))issues.push(['faded until hover',name(e),'opacity '+o.toFixed(2)]);
  if(r.right>innerWidth+1||r.bottom>innerHeight+1){let scroll=false;for(let x=e.parentElement;x;x=x.parentElement){const s=getComputedStyle(x);if(/(auto|scroll)/.test(s.overflowY+s.overflowX)&&(x.scrollHeight>x.clientHeight||x.scrollWidth>x.clientWidth)){scroll=true;break;}}
    if(!scroll)issues.push(['outside the window, no scroll',name(e),Math.round(r.right)+','+Math.round(r.bottom)]);}
}
for(const e of root.querySelectorAll('label,span,button,summary,h3,h4,h5,p,strong,option,.setting-row>*')){
  if(!shown(e)||!e.innerText?.trim()||e.getBoundingClientRect().width<=2)continue;const s=getComputedStyle(e);  // 1px = screen-reader text
  if((s.textOverflow==='ellipsis'||s.overflow==='hidden')&&e.scrollWidth>e.clientWidth+2&&!e.title)issues.push(['cut text',name(e),e.scrollWidth+'>'+e.clientWidth]);
}
for(const d of root.querySelectorAll('details details')){if(!shown(d.querySelector(':scope>summary')||d))continue;
  const depth=(()=>{let n=0;for(let x=d;x;x=x.parentElement?.closest('details'))n++;return n;})();
  if(depth>=2)issues.push(['fold inside a fold',name(d.querySelector(':scope>summary')||d),'depth '+depth]);}
return issues;"""

STEPS = [
    ('home', 'body', ''),
    ('model-window', '#composerControls', "if(!window.VALWindows?.isOpen('model'))$('modelBtn').click();await w(1200);"),
    ('model-advanced-tab', '#composerControls', "$('tab-load')?.click();await w(600);document.querySelectorAll('#composerControls details').forEach(d=>d.open=true);await w(600);"),
    ('engine-advanced', '#composerControls', "$('mayaQuickAdvanced')?.click();await w(1500);"),
    ('response-menu', 'body', "$('closeControls')?.click();await w(400);$('responseBtn')?.click();await w(700);"),
    ('access-menu', '#permissionMenu', "document.dispatchEvent(new KeyboardEvent('keydown',{key:'Escape',bubbles:true}));await w(300);$('scopeBtn').click();await w(700);"),
    ('add-menu', '#composerAddMenu', "document.dispatchEvent(new KeyboardEvent('keydown',{key:'Escape',bubbles:true}));await w(300);document.querySelector('#composerAdd,#attach,[aria-controls=composerAddMenu]')?.click();await w(700);"),
    ('tools-window', '#toolsWindow', "document.dispatchEvent(new KeyboardEvent('keydown',{key:'Escape',bubbles:true}));await w(300);$('mcpBtn').click();await w(1000);document.querySelectorAll('#toolsWindow details').forEach(d=>d.open=true);await w(500);"),
    ('models-window', '#modelsWindow', "document.querySelectorAll('.fw [data-fw-close]').forEach(b=>b.offsetParent&&b.click());await w(400);$('sidebarModels').click();await w(2500);"),
    ('console', '#consoleWindow', "document.querySelectorAll('.fw [data-fw-close]').forEach(b=>b.offsetParent&&b.click());await w(400);$('openConsole')?.click();await w(1000);"),
    ('project', 'body', "document.querySelectorAll('.fw [data-fw-close]').forEach(b=>b.offsetParent&&b.click());await w(400);$('projectBtn')?.click();await w(900);"),
]
SETTINGS = ['general', 'appearance', 'chat', 'tools', 'market', 'plugins', 'system', 'history']


async def audit(core, size, out):
    width, height = (int(x) for x in size.split('x'))
    found = {}
    async with Browser(width, height) as browser:
        async def shot(label):
            data = await browser.call('Page.captureScreenshot', {'format': 'png'})
            (out / f'{size}-{label}.png').write_bytes(base64.b64decode(data['data']))

        await browser.open(core.base + '/')
        await browser.run("const w=ms=>new Promise(r=>setTimeout(r,ms));const $=id=>document.getElementById(id);"
                          "$('modelBtn').click();await w(900);$('modelChooser').click();await w(400);"
                          "document.querySelector('#modelResults .model-option')?.click();await w(500);$('closeControls')?.click();await w(400);")
        steps = list(STEPS) + [(f'settings-{c}', '#drawer', "document.querySelectorAll('.fw [data-fw-close]').forEach(b=>b.offsetParent&&b.click());"
                                 "if(!document.getElementById('drawer')||document.getElementById('drawer').hidden){$('gear').click();await w(700);}"
                                 f"document.querySelector('[data-settings-category={c}],[data-category={c}]')?.click();await w(900);"
                                 "document.querySelectorAll('#drawer details').forEach(d=>d.open=true);await w(400);") for c in SETTINGS]
        steps += [('conversation-menu', '#convMenu', "if(!$('drawer').hidden)$('gear').click();await w(400);"
                   "$('input').value='hola';$('input').dispatchEvent(new Event('input',{bubbles:true}));"
                   "document.querySelector('#convs .conv-more')?.click();await w(700);")]
        for label, selector, script in steps:
            try:
                issues = await browser.run("const w=ms=>new Promise(r=>setTimeout(r,ms));const $=id=>document.getElementById(id);"
                                           + script + AUDIT.replace('ROOT_SELECTOR', json.dumps(selector)))
            except RuntimeError as error:
                issues = [['step failed', label, str(error)[:120]]]
            await shot(label)
            for kind, element, detail in issues:
                found.setdefault((kind, element), (label, detail))
        # The MCP settings must show their saved values, and the Tools window's shortcut must work.
        values = await browser.run("const w=ms=>new Promise(r=>setTimeout(r,ms));const $=id=>document.getElementById(id);"
            "document.querySelectorAll('.fw [data-fw-close]').forEach(b=>b.offsetParent&&b.click());await w(400);"
            "$('mcpBtn').click();await w(900);$('configureMCPs')?.click();await w(2000);"
            "const n=$('mcpopt-duckduckgo-max_results')||document.querySelector('#mcpOptionsFields input[type=number]');"
            "return {value:n?.value,focus:document.activeElement?.id||document.activeElement?.tagName};")
        if not values.get('value'):
            found[('MCP settings show no saved values', '#mcpOptionsFields')] = ('settings-tools', values)
        for error in browser.errors:
            found[('page error', error[:120])] = ('run', '')
    return found, []


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--model', required=True)
    parser.add_argument('--size', default='1280x800')
    args = parser.parse_args()
    out = ROOT / 'build' / 'ui-layout-audit'
    out.mkdir(parents=True, exist_ok=True)
    with IsolatedCore(19374, r'%LOCALAPPDATA%\V-Agent-Data') as core:
        core.post('/api/harness/configure', {'engine': 'llama', 'variant': 'cuda'})
        core.post('/api/models/register', {'path': args.model})
        found, _ = asyncio.run(audit(core, args.size, out))
    by_kind = {}
    for (kind, element), (label, detail) in sorted(found.items()):
        by_kind.setdefault(kind, []).append(f'{element} [{label}] {detail}')
    for kind, items in by_kind.items():
        print(f'\n{kind} ({len(items)}):')
        for item in items:
            print('   ', item)
    print(f'\n{len(found)} findings at {args.size}. Screenshots: {out}')
    sys.exit(1 if found else 0)


if __name__ == '__main__':
    main()
