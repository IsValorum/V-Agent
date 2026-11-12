"""Attack the Hugging Face model-card renderer with known XSS vectors, through the real interface.

    .venv\\Scripts\\python tests\\smoke\\xss_model_card.py

Model cards (README.md) are written by strangers and shown inside V-Agent. This starts an isolated
core (no model needed), opens the Models window in the bundled headless browser and answers the
card request itself with a README full of attacks: mutation XSS through noscript/svg/math/style,
`javascript:` and entity-encoded URLs, srcset, srcdoc, event handlers, data: SVG, broken markup...
The interface's own Markdown renderer and sanitiser handle it exactly as they would a real card.

Each vector tries to push its number into `window.__xss`. Passes when none ran, no dangerous element
or attribute survives in the rendered card, and links that do survive only point to https.
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

HIT = 'window.__xss.push'
VECTORS = [
    f'<img src=x onerror="{HIT}(1)">',
    f'<noscript><p title="</noscript><img src=x onerror={HIT}(2)>"></noscript>',
    f'<noscript><a title="</noscript><img src=x onerror={HIT}(3)>">x</a></noscript>',
    f'<svg><style><img src=x onerror={HIT}(4)></style></svg>',
    f'<math><mtext><table><mglyph><style><img src=x onerror={HIT}(5)></style></mglyph></table></mtext></math>',
    f'<a href="javascript:{HIT}(6)">x</a>',
    f'<a href=" javascript:{HIT}(7)">x</a>',
    f'<xmp><img src=x onerror={HIT}(9)></xmp>',
    f'<noembed><img src=x onerror={HIT}(10)></noembed>',
    f'<template><img src=x onerror={HIT}(11)></template>',
    f'<img src="https://x.invalid/a.png" srcset="x" onerror={HIT}(13)>',
    f'<iframe srcdoc="<script>parent.__xss.push(14)</script>"></iframe>',
    f'<object data="javascript:{HIT}(15)"></object>',
    f'<picture><source srcset="javascript:{HIT}(16)"><img src="https://x.invalid/b.png"></picture>',
    f'<div style="background:url(javascript:{HIT}(17))">x</div>',
    f'<textarea><img src=x onerror={HIT}(18)></textarea>',
    f'<title><img src=x onerror={HIT}(19)></title>',
    f'<noframes><img src=x onerror={HIT}(20)></noframes>',
    f'[link](javascript:{HIT}(22))',
    f'<a href="https://ok.invalid" onclick="{HIT}(23)">ok</a>',
    f'<img/src/onerror={HIT}(24)>',
    f'<scr<script>ipt>{HIT}(25)</script>',
    f'<a href="&#106;avascript:{HIT}(26)">x</a>',
    f'<img src="data:image/svg+xml,<svg onload={HIT}(27)>">',
    f'![x](javascript:{HIT}(28))',
]
# Broken on purpose: they leave an element or a tag open and swallow what follows, so they go last.
UNCLOSED = [
    f'<details open ontoggle={HIT}(12)>',
    f'<img src=x onerror={HIT}(21)//',
    f'<form><math><mtext></form><form><mglyph><style></math><img src=x onerror={HIT}(8)>',
]
REPO = 'qa-attacker/xss-card'


async def attack(core, out):
    # A marker after each vector shows it was parsed in place and did not swallow the next one.
    readme = ('# Model card\n\nA **normal** card with [a link](https://huggingface.co).\n\n'
              + ''.join(f'{vector}\n\nmarker-{n}\n\n' for n, vector in enumerate(VECTORS))
              + '\n\n'.join(UNCLOSED))
    answers = {
        '/api/harness/hub/search': {'models': [{'id': REPO, 'downloads': 1, 'likes': 1, 'updated': '2026-11-01T00:00:00Z'}]},
        '/api/harness/hub/model': {'id': REPO, 'author': 'qa-attacker', 'url': 'https://huggingface.co/' + REPO,
                                   'downloads': 1, 'likes': 1, 'updated': '2026-11-01T00:00:00Z', 'files': [],
                                   'readme': readme},
    }
    async with Browser() as browser:
        async def paused(params):
            path = params['request']['url'].split('://', 1)[1].split('/', 1)[1].split('?')[0]
            body = answers.get('/' + path)
            if body is None:
                await browser.send('Fetch.continueRequest', {'requestId': params['requestId']})
            else:
                await browser.send('Fetch.fulfillRequest', {
                    'requestId': params['requestId'], 'responseCode': 200,
                    'responseHeaders': [{'name': 'Content-Type', 'value': 'application/json'}],
                    'body': base64.b64encode(json.dumps(body).encode()).decode()})
        browser.handlers['Fetch.requestPaused'] = paused
        await browser.call('Page.addScriptToEvaluateOnNewDocument', {'source': 'window.__xss=[];'})
        await browser.call('Fetch.enable', {'patterns': [{'urlPattern': '*/api/harness/hub/*'}]})
        await browser.open(core.base + '/')
        result = await browser.run("""
            const w=ms=>new Promise(r=>setTimeout(r,ms));
            document.getElementById('gear').click(); await w(400); document.getElementById('sidebarModels').click(); await w(1500);
            document.querySelector('#hubResults .hub-item')?.click();
            for(let k=0;k<40&&!document.querySelector('.hub-readme');k++) await w(250);
            await w(2500);
            const card=document.querySelector('.hub-readme');
            if(!card) return {error:'card not rendered'};
            card.querySelectorAll('details').forEach(d=>d.open=true);
            card.querySelectorAll('a').forEach(a=>{a.addEventListener('click',e=>e.preventDefault());a.click();});
            await w(1500);
            const dangerous=[...card.querySelectorAll('script,iframe,object,embed,style,svg,math,form,textarea,noscript,template,link,meta')].map(e=>e.tagName);
            const handlers=[...card.querySelectorAll('*')].flatMap(e=>[...e.attributes].filter(a=>/^on|^style$|^srcdoc$/i.test(a.name)).map(a=>e.tagName+'['+a.name+']'));
            const urls=[...card.querySelectorAll('[href],[src],[srcset]')].flatMap(e=>['href','src','srcset'].map(n=>e.getAttribute(n)).filter(v=>v!==null)).filter(v=>!/^https:\\/\\//i.test(v.trim()));
            const markers=(card.innerText.match(/marker-[0-9]+/g)||[]).length;
            const normal=!!card.querySelector('strong')&&!!card.querySelector('a[href="https://huggingface.co"]');
            return {ran:window.__xss, dangerous, handlers, urls, markers, normal, html:card.innerHTML.slice(0,1500)};""")
        data = await browser.call('Page.captureScreenshot', {'format': 'png'})
        out.mkdir(parents=True, exist_ok=True)
        (out / 'xss-model-card.png').write_bytes(base64.b64decode(data['data']))
        return result, browser.errors


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--port', type=int, default=19391)
    parser.add_argument('--out', default=str(ROOT / 'build' / 'xss'))
    parser.add_argument('--report', help='write the results as JSON here')
    args = parser.parse_args()
    with IsolatedCore(args.port) as core:
        result, errors = asyncio.run(attack(core, Path(args.out)))
    rows = []

    def check(name, ok, detail):
        rows.append({'engine': 'interface', 'check': name, 'status': 'pass' if ok else 'fail', 'detail': str(detail)[:300]})
        print(f"  {'OK  ' if ok else 'FAIL'} {name} — {detail}")

    if result.get('error'):
        check('the attacked model card is rendered', False, result['error'])
    else:
        check(f'{len(VECTORS) + len(UNCLOSED)} XSS vectors in a model card: none ran', not result['ran'], result['ran'] or 'none ran')
        check('no dangerous element survives in the card', not result['dangerous'], result['dangerous'] or 'none')
        check('no event handler, style or srcdoc attribute survives', not result['handlers'], result['handlers'] or 'none')
        check('every surviving link or image points to https', not result['urls'], result['urls'] or 'all https')
        check('each closed vector is parsed in place (none swallows the next)', result['markers'] == len(VECTORS),
              f"{result['markers']} of {len(VECTORS)} markers rendered")
        check('the normal content of the card still renders', result['normal'], 'bold text and https link present' if result['normal'] else result['html'][:600])
    if args.report:
        Path(args.report).write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding='utf-8')
    sys.exit(1 if any(r['status'] == 'fail' for r in rows) else 0)


if __name__ == '__main__':
    main()
