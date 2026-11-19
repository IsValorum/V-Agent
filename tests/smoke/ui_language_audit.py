"""Spanish left on screen when the interface is in another language.

    .venv\\Scripts\\python tests\\smoke\\ui_language_audit.py [--language en]

An isolated core is connected to a local fake provider whose replies reason slowly and then call a
tool, so the screen goes through every live state of a reply (reasoning, a tool card, the answer).
The interface is switched to the chosen language and, at each state and with the main windows open,
every visible text is compared with the translation catalog: a text that is a Spanish catalog phrase
(with a different translation) is reported. Exit code 1 if any is found.
"""
import argparse
import asyncio
import json
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from headless import ROOT, Browser  # noqa: E402
from isolated_core import IsolatedCore  # noqa: E402


class Provider(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_GET(self):
        raw = json.dumps({'data': [{'id': 'fake-reasoner', 'context_length': 131072, 'max_tokens': 32768}]}).encode()
        self.send_response(200)
        self.send_header('Content-Length', str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers.get('Content-Length') or 0)) or b'{}')
        tool_done = any(m.get('role') == 'tool' for m in body.get('messages') or [])
        self.send_response(200)
        self.send_header('Content-Type', 'text/event-stream')
        self.end_headers()

        def send(packet):
            self.wfile.write(('data: ' + json.dumps(packet) + '\n\n').encode())
            self.wfile.flush()
        if not tool_done:
            for _ in range(10):  # slow reasoning: the "Reasoning…" state stays on screen
                send({'choices': [{'delta': {'reasoning_content': 'thinking about the island. '}}]})
                time.sleep(.4)
            send({'choices': [{'delta': {'tool_calls': [{'index': 0, 'id': 'c1', 'type': 'function', 'function': {
                'name': 'pc__fs_write', 'arguments': json.dumps({'path': 'isla.txt', 'content': 'x' * 20000})}}]},
                'finish_reason': 'tool_calls'}]})
        else:
            for word in ('Done ', 'with ', 'the ', 'island.'):
                send({'choices': [{'delta': {'content': word}}]})
                time.sleep(.3)
            send({'choices': [{'delta': {}, 'finish_reason': 'stop'}]})
        self.wfile.write(b'data: [DONE]\n\n')


SCAN = """const catalog=window.__catalog;const lang=%s;const found=new Set();
const walker=document.createTreeWalker(document.body,NodeFilter.SHOW_TEXT);
// Spanish that is not even in the catalog: only for en/de, where Spanish words cannot be the translation.
const SPANISH=/[ñ¿¡]|\b(?:el|los|las|del|una|está|aún|ningún|ninguna|selecciona|pulsa|descarga|conexión|también|después|todavía|cargando|guardar|actualizar)\b/i;
const translated=new Set(Object.values(catalog).map(e=>e[lang]).filter(Boolean));
const spanishLike=text=>['en','de'].includes(lang)&&text.length<300&&SPANISH.test(text)&&!translated.has(text);
const visible=el=>{for(let n=el;n&&n!==document.body;n=n.parentElement){const s=getComputedStyle(n);if(s.display==='none'||s.visibility==='hidden')return false;if(n.hidden)return false;}return true;};
for(let node=walker.nextNode();node;node=walker.nextNode()){const text=node.textContent.trim();if(text.length<3)continue;
  const el=node.parentElement;if(!el||!visible(el)||el.closest('pre,code,textarea,.msg-body .markdown,.markdown'))continue;
  const entry=catalog[text];if(entry&&entry[lang]&&entry[lang]!==text)found.add(text);
  else if(!entry&&spanishLike(text)&&!el.closest('.msg,.message,.conv-list,#convList,[data-user-content],#uiLanguage'))found.add('not in catalog: '+text);}
for(const el of document.querySelectorAll('[title],[placeholder],[aria-label]')){if(!visible(el))continue;for(const a of ['title','placeholder','aria-label']){const v=(el.getAttribute(a)||'').trim();const entry=catalog[v];if(entry&&entry[lang]&&entry[lang]!==v)found.add(a+': '+v);}}
return [...found];"""


async def run(core, language):
    catalog = json.loads((ROOT / 'agent' / 'ui' / 'locales.json').read_text(encoding='utf-8'))
    report = {}
    async with Browser(1280, 900) as browser:
        await browser.open(core.base + '/')
        await asyncio.sleep(2)
        await browser.run('window.__catalog=%s;await window.VALI18n.setLanguage(%s);await new Promise(r=>setTimeout(r,1500));return 1'
                          % (json.dumps(catalog), json.dumps(language)))
        await browser.run("const b=document.querySelector('#permissionMenu [data-mode=run]');b&&b.click();return 1")
        scan = SCAN % json.dumps(language)
        report['idle'] = await browser.run(scan)
        await browser.run("""const w=ms=>new Promise(r=>setTimeout(r,ms));const $=id=>document.getElementById(id);
            if(!window.VALWindows?.isOpen('model'))$('modelBtn').click();await w(1000);const a=$('modelSummaryAction');
            if(a&&/Usar modelo|Use model|Usar|Utiliser|verwenden/i.test(a.textContent))a.click();await w(1500);return 1""")
        report['model window'] = await browser.run(scan)
        await browser.run("window.VALWindows?.close?.('model');const i=document.getElementById('input');i.value='make a voxel island';"
                          "i.dispatchEvent(new Event('input',{bubbles:true}));document.getElementById('send').click();return 1")
        await asyncio.sleep(1.5)
        report['while reasoning'] = await browser.run(scan)
        expected = catalog['Razonando…'][language]
        shown = await browser.run('return document.getElementById("chat").innerText')
        if expected not in shown:
            report['while reasoning'].append('the reasoning note is not shown as "%s"' % expected)
        await asyncio.sleep(4.5)
        report['tool card / answer'] = await browser.run(
            "for(const d of document.querySelectorAll('#chat details'))d.open=true;await new Promise(r=>setTimeout(r,400));" + scan)
        await asyncio.sleep(3)
        report['finished'] = await browser.run(
            "for(const d of document.querySelectorAll('#chat details'))d.open=true;await new Promise(r=>setTimeout(r,400));" + scan)
        await browser.run("document.getElementById('gear')?.click();return 1")
        await asyncio.sleep(1.5)
        report['settings'] = await browser.run(scan)
    return report


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--language', default='en')
    language = parser.parse_args().language
    server = ThreadingHTTPServer(('127.0.0.1', 0), Provider)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    with IsolatedCore(port=19395) as core:
        core.post('/api/harness/configure', {'engine': 'api', 'base_url': f'http://127.0.0.1:{server.server_port}/v1', 'api_key': 'fixture-only-key'})
        core.post('/api/harness/connect', {})
        report = asyncio.run(run(core, language))
    bad = 0
    for state, texts in report.items():
        bad += len(texts)
        print(f"  {'OK  ' if not texts else 'FAIL'} {state}: " + ('no Spanish left' if not texts else '; '.join(texts)[:600]), flush=True)
    print('RESULT', 'OK' if not bad else 'FAIL')
    sys.exit(1 if bad else 0)


if __name__ == '__main__':
    main()
