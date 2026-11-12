"""Read the context meter on screen every 0.3 s while a real model thinks and uses tools.

    .venv\\Scripts\\python tests\\smoke\\live_context_screen.py --engine llama --model D:\\models\\small.gguf

The same check as live_context_probe.py, but through the interface: what the user sees in the
composer's context meter. Exit code 1 when the meter stood still for more than 2.5 s while the reply
was running, never moved during it, or went down within the reply.
"""
import argparse
import asyncio
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from headless import Browser  # noqa: E402
from isolated_core import IsolatedCore  # noqa: E402

REQUEST = ('Crea tres archivos: uno.txt con el texto 1, dos.txt con el texto 2 y tres.txt con el texto 3. '
           'Después lee los tres y dime cuánto suman los números.')


async def watch(core):
    async with Browser() as browser:
        await browser.open(core.base + '/')
        await browser.run("""const w=ms=>new Promise(r=>setTimeout(r,ms));
            document.getElementById('scopeBtn').click(); await w(500);
            document.querySelector('#permissionMenu [data-mode=run]')?.click(); await w(300);
            document.dispatchEvent(new KeyboardEvent('keydown',{key:'Escape',bubbles:true})); await w(300);
            const i=document.getElementById('input'); i.value=%r; i.dispatchEvent(new Event('input',{bubbles:true}));
            document.getElementById('send').click();""" % REQUEST)
        samples, start = [], time.time()
        await asyncio.sleep(.5)
        while time.time() - start < 600:
            state = await browser.run("""return {label:document.getElementById('ctxLabel').textContent,
                busy:!!document.querySelector('#chat [data-generating=true]'), note:(document.querySelector('#chat [data-generating=true] .stream-note, #chat .stream-note')||{}).textContent||''};""")
            samples.append((round(time.time() - start, 2), state))
            if not state['busy'] and len(samples) > 3:
                break
            await asyncio.sleep(.3)
        return samples, browser.errors


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--engine', choices=('llama', 'strata', 'rust'), required=True)
    parser.add_argument('--model', required=True)
    parser.add_argument('--engines-from', default=r'%LOCALAPPDATA%\V-Agent-Data')
    args = parser.parse_args()
    with IsolatedCore(19389, args.engines_from) as core:
        core.post('/api/harness/configure', {'engine': args.engine, 'variant': 'cuda'} if args.engine == 'llama' else {'engine': args.engine})
        model = core.post('/api/models/register', {'path': args.model}, timeout=900)['model']['id']
        core.post('/api/load', {'model': model, 'context': 8192}, timeout=1800)
        samples, errors = asyncio.run(watch(core))
    used = [(t, int(re.sub(r'\D', '', s['label'].split('/')[0]) or -1), s) for t, s in samples if s['busy']]
    changes = [(t, u) for i, (t, u, _) in enumerate(used) if i == 0 or u != used[i - 1][1]]
    print('meter while replying:', ', '.join(f'{t}s={u}' for t, u in changes))
    longest, mark = 0.0, (used[0][0], used[0][1]) if used else (0, None)
    for t, u, _ in used:
        if u != mark[1]:
            mark = (t, u)
        longest = max(longest, t - mark[0])
    went_down = any(b[1] < a[1] for a, b in zip(changes, changes[1:]) if a[1] >= 0 and b[1] >= 0)
    print(f'changes: {len(changes)}; longest stretch without a change: {longest:.1f} s; went down: {went_down}; page errors: {errors or "none"}')
    sys.exit(0 if len(changes) > 2 and longest <= 2.5 and not went_down and not errors else 1)


if __name__ == '__main__':
    main()
