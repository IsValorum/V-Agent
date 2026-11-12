"""Take screenshots of the real interface of this version, with a model loaded and a real agent run.

    .venv\\Scripts\\python scripts\\quality\\screenshots.py --model D:\\models\\some-model.gguf [--engine llama]

Starts an isolated core (nothing from a real installation is used except the installed engines),
loads the model, switches the interface to English and, in the bundled headless browser at
1440×900 and device scale 1, sends a real request in "Confirm changes" mode, photographs the approval dialog,
approves, and photographs the finished reply, the model window, the tools window, the Hugging Face
browser, the engines page and the light theme. Images go to docs/test-reports/<version>/.
The data folder is kept under build/ so no path in the images shows the local user name.
"""
import argparse
import asyncio
import base64
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path[:0] = [str(ROOT / 'tests' / 'smoke'), str(ROOT / 'agent')]
from headless import Browser  # noqa: E402
from isolated_core import IsolatedCore  # noqa: E402

W = "const w=ms=>new Promise(r=>setTimeout(r,ms));const $=id=>document.getElementById(id);"
CLOSE = W + ("$('closeControls')?.click();document.querySelectorAll('.fw [data-fw-close]').forEach(b=>b.offsetParent&&b.click());"
             "if($('drawer')&&!$('drawer').hidden)$('gear').click();await w(500);")
REQUEST = ('Create a small landing page for a coffee shop in cafe.html, with a button that switches between a light '
           'and a dark theme and remembers the choice. Then check it for errors.')


async def take(core, out, request):
    async with Browser(1440, 900) as browser:
        async def shot(name):
            data = await browser.call('Page.captureScreenshot', {'format': 'png'})
            (out / f'{name}.png').write_bytes(base64.b64decode(data['data']))
            print('  ', name, flush=True)

        await browser.open(core.base + '/')
        await browser.run(W + """$('gear').click(); await w(500);
            document.querySelector('[data-settings-category=general],[data-category=general]')?.click(); await w(300);
            const l=$('uiLanguage'); l.value='en'; l.dispatchEvent(new Event('change',{bubbles:true})); await w(900);""")
        await browser.call('Page.reload', {})
        await asyncio.sleep(4)
        await browser.run(CLOSE + "document.querySelector('.update-card-close')?.click();")

        # A real agent run in "Confirm changes" mode: the approval dialog, then the finished reply.
        await browser.run(W + """$('scopeBtn').click(); await w(600);
            [...document.querySelectorAll('#permissionMenu [data-mode]')].find(b=>b.dataset.mode==='auto')?.click(); await w(400);
            document.dispatchEvent(new KeyboardEvent('keydown',{key:'Escape',bubbles:true})); await w(300);""")
        await browser.run(W + "const i=$('input'); i.value=%r; i.dispatchEvent(new Event('input',{bubbles:true})); $('send').click();" % request)
        photographed = False
        for _ in range(1500):
            state = await browser.run("""const d=document.querySelector('dialog.tool-approval[open]');
                return {dialog:!!d, busy:!!document.querySelector('#chat [data-generating=true]')};""")
            if state['dialog']:
                if not photographed:
                    await asyncio.sleep(.8)
                    await shot('02-approval')
                    photographed = True
                await browser.run("document.querySelector('dialog.tool-approval[open] .primary')?.click();")
            elif not state['busy']:
                break
            await asyncio.sleep(.4)
        await asyncio.sleep(1.5)
        await browser.run("const c=document.getElementById('chat'); c.scrollTop=c.scrollHeight;")
        await shot('01-agent-run')

        await browser.run(CLOSE + "$('modelBtn').click(); await w(1200);")
        await shot('03-model-window')
        await browser.run(CLOSE + "$('mcpBtn').click(); await w(1000);")
        await shot('04-tools-window')
        await browser.run(CLOSE + "$('sidebarModels').click(); await w(3500);"
                                  "document.querySelector('#hubResults .hub-item')?.click(); await w(3500);")
        await shot('05-hugging-face')
        await browser.run(CLOSE + """$('gear').click(); await w(600);
            document.querySelector('[data-settings-category=system],[data-category=system]')?.click(); await w(900);""")
        await shot('06-settings-engines')
        await browser.run(CLOSE + "$('themeBtn').click(); await w(1500);")
        await shot('07-light-theme')
        return browser.errors


def main():
    import app_updates
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--model', required=True)
    parser.add_argument('--engine', default='llama', choices=('llama', 'strata', 'rust'))
    parser.add_argument('--context', type=int, default=16384)
    parser.add_argument('--request', default=REQUEST)
    parser.add_argument('--out', default=str(ROOT / 'docs' / 'test-reports' / app_updates.VERSION))
    args = parser.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    # The data folder lives under build/, so no screenshot shows the local user name.
    with IsolatedCore(19393, r'%LOCALAPPDATA%\V-Agent-Data', ROOT / 'build' / 'screens-data') as core:
        core.post('/api/harness/configure', {'engine': args.engine, 'variant': 'cuda'} if args.engine == 'llama' else {'engine': args.engine})
        model = core.post('/api/models/register', {'path': args.model}, timeout=900)['model']['id']
        core.post('/api/load', {'model': model, 'context': args.context}, timeout=1800)
        errors = asyncio.run(take(core, out, args.request))
    print('Page errors:', errors or 'none', '· images in', out)


if __name__ == '__main__':
    main()
