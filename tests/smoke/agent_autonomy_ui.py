"""An autonomous turn in the real interface: the agent asks, retries and trims its context by itself.

    .venv\\Scripts\\python tests\\smoke\\agent_autonomy_ui.py

An isolated core is connected to a local fake provider (no account) whose replies are scripted per
request, and the interface is driven in the bundled headless browser like a user would:
- the model asks a question with options (agent__ask_user): the dialog shows it, the user picks an
  option, the answer reaches the model and the turn ends with the model's reply;
- "Let the agent decide" sends the model the instruction to continue on its own judgment;
- the provider answers 503 once in the middle of a turn: the round is repeated, the task finishes;
- the provider refuses a prompt as larger than its context: the history is shortened, the round
  is repeated and the task finishes;
- a request without `ask_user` (an API client) never gets the question tool.
"""
import asyncio
import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from headless import Browser  # noqa: E402
from isolated_core import IsolatedCore  # noqa: E402

REQUESTS = []
STATE = {'failed_503': False, 'overflowed': False}


def sse(packets):
    return ''.join('data: ' + json.dumps(p) + '\n\n' for p in packets) + 'data: [DONE]\n\n'


def call(name, args, ident='call_1'):
    return sse([{'choices': [{'delta': {'tool_calls': [{'index': 0, 'id': ident, 'type': 'function',
                                                         'function': {'name': name, 'arguments': json.dumps(args)}}]},
                              'finish_reason': 'tool_calls'}]}])


def say(text):
    return sse([{'choices': [{'delta': {'content': text}, 'finish_reason': 'stop'}]}])


def script(body):
    """(status, payload) for one request: decided by the user's words and the last tool result."""
    messages = body.get('messages') or []
    user = next((m.get('content') for m in reversed(messages) if m.get('role') == 'user'), '') or ''
    if isinstance(user, list):
        user = ' '.join(part.get('text', '') for part in user if isinstance(part, dict))
    last_user = max((i for i, m in enumerate(messages) if m.get('role') == 'user'), default=-1)
    last_tool = next((m.get('content') for m in reversed(messages[last_user + 1:]) if m.get('role') == 'tool'), None)
    tools = [t['function']['name'] for t in body.get('tools') or []]
    if 'color' in user:
        if last_tool is None:
            return 200, call('agent__ask_user', {'question': '¿Qué color prefieres para el botón?', 'options': ['Azul', 'Verde']})
        return 200, say('RESPUESTA-MODELO: ' + last_tool)
    if 'retry' in user:
        if last_tool is None:
            return 200, call('pc__fs_write', {'path': 'nota.txt', 'content': 'hola'})
        if not STATE['failed_503']:
            STATE['failed_503'] = True
            return 503, json.dumps({'error': {'message': 'The server is overloaded, try again later.'}})
        return 200, say('TAREA-COMPLETA tras reintento')
    if 'grande' in user:
        size = len(json.dumps(messages))
        if last_tool is None:
            return 200, call('pc__fs_write', {'path': 'grande.txt', 'content': 'x' * 30000})
        if not STATE['overflowed'] and size > 20000:
            STATE['overflowed'] = True
            return 400, json.dumps({'error': {'message': 'the request exceeds the available context size, try increasing it',
                                              'type': 'exceed_context_size_error'}})
        return 200, say('TAREA-COMPLETA con contexto de %d caracteres' % size)
    if 'api client' in user:
        return 200, say('TOOLS:' + ','.join(tools))
    return 200, say('ok')


class Provider(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def _send(self, status, text, kind):
        raw = text.encode()
        self.send_response(status)
        self.send_header('Content-Type', kind)
        self.send_header('Content-Length', str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):
        self._send(200, json.dumps({'object': 'list', 'data': [{'id': 'fake-agent', 'object': 'model', 'context_length': 1048576}]}),
                   'application/json')

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers.get('Content-Length') or 0)) or b'{}')
        REQUESTS.append(body)
        status, text = script(body)
        self._send(status, text, 'text/event-stream' if status == 200 else 'application/json')


SEND = """const w=ms=>new Promise(r=>setTimeout(r,ms));const $=id=>document.getElementById(id);
const input=$('input');input.value=%s;input.dispatchEvent(new Event('input',{bubbles:true}));await w(200);$('send').click();
for(let k=0;k<20&&!input.disabled;k++)await w(100);return true;"""

WAIT_DIALOG = """const w=ms=>new Promise(r=>setTimeout(r,ms));
for(let k=0;k<100;k++){const d=document.querySelector('dialog.agent-question[open]');if(d)return {question:d.querySelector('.agent-question-text')?.textContent,
  options:[...d.querySelectorAll('.agent-question-option')].map(b=>b.textContent),title:d.querySelector('h3')?.textContent};await w(150);}
return null;"""

WAIT_DONE = """const w=ms=>new Promise(r=>setTimeout(r,ms));const $=id=>document.getElementById(id);
for(let k=0;k<300&&$('input').disabled;k++)await w(150);await w(500);
const msgs=[...document.querySelectorAll('#chat .msg.assistant, #chat .assistant')];const last=msgs[msgs.length-1];
const cards=[...document.querySelectorAll('#chat .tool, #chat details.tool')].map(c=>c.textContent.replace(/\\s+/g,' ').slice(0,240));
return {text:last?last.textContent.replace(/\\s+/g,' ').slice(-700):'',cards};"""


async def run(core):
    ok = []

    def check(name, good, detail=''):
        ok.append(bool(good))
        print(f"  {'OK  ' if good else 'FAIL'} {name}" + (f' — {str(detail)[:300]}' if detail else ''), flush=True)

    async with Browser(1280, 900) as browser:
        await browser.open(core.base + '/')
        await asyncio.sleep(2)
        # Automatic permissions: the write in the scripts must not stop at an approval.
        await browser.run("const b=document.querySelector('#permissionMenu [data-mode=run]');b&&b.click();return 1")
        await browser.run("""const w=ms=>new Promise(r=>setTimeout(r,ms));const $=id=>document.getElementById(id);
            if(!window.VALWindows?.isOpen('model'))$('modelBtn').click();await w(1000);const a=$('modelSummaryAction');
            if(a&&/Usar modelo|Use model/.test(a.textContent))a.click();await w(1500);window.VALWindows?.close?.('model');return 1""")

        # 1. A question with options, answered by picking one.
        await browser.run(SEND % json.dumps('Haz el botón, elige el color conmigo'))
        dialog = await browser.run(WAIT_DIALOG)
        check('the agent\'s question opens a dialog with its options', dialog and dialog.get('options') == ['Azul', 'Verde']
              and 'color' in (dialog.get('question') or ''), dialog)
        await browser.run("[...document.querySelectorAll('dialog.agent-question .agent-question-option')].find(b=>b.textContent==='Verde').click();return 1")
        done = await browser.run(WAIT_DONE)
        check('the picked option reaches the model and the turn ends', 'The user answered: Verde' in done['text'], done['text'])
        check('the question card shows the answer in the interface language', any('Tu respuesta: Verde' in c for c in done['cards']), done['cards'])

        # 2. "Let the agent decide".
        await browser.run(SEND % json.dumps('Otro botón, elige el color'))
        dialog = await browser.run(WAIT_DIALOG)
        await browser.run("[...document.querySelectorAll('dialog.agent-question button')].find(b=>/Que decida|Let the agent/.test(b.textContent)).click();return 1")
        done = await browser.run(WAIT_DONE)
        check('"Let the agent decide" tells the model to continue on its own judgment',
              'chose not to answer' in done['text'] and 'best judgment' in done['text'], done['text'])

        # 3. A 503 in the middle of a turn.
        await browser.run(SEND % json.dumps('Prueba retry: guarda una nota y termina'))
        done = await browser.run(WAIT_DONE)
        check('a 503 mid-turn is retried and the task finishes', 'TAREA-COMPLETA tras reintento' in done['text'], done['text'])
        check('the retry is shown as a card', any('Reintento automático' in c for c in done['cards']), done['cards'][-3:])

        # 4. The provider refuses the prompt as too large.
        await browser.run(SEND % json.dumps('Archivo grande: escribe y termina'))
        done = await browser.run(WAIT_DONE)
        check('a context overflow shortens the history, repeats and finishes', 'TAREA-COMPLETA con contexto' in done['text'], done['text'])
        check('the shortened context is shown as a card', any('Contexto acotado' in c for c in done['cards']), done['cards'][-4:])
        errors = await browser.run("return (window.__errors||[]).slice(-5)")
        check('no page errors', not errors and not browser.errors, (errors, browser.errors))
    return ok


def main():
    server = ThreadingHTTPServer(('127.0.0.1', 0), Provider)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    with IsolatedCore(port=19392) as core:
        core.post('/api/harness/configure', {'engine': 'api', 'base_url': f'http://127.0.0.1:{server.server_port}/v1', 'api_key': 'fixture-only-key'})
        core.post('/api/harness/connect', {})
        ok = asyncio.run(run(core))
        # 5. API clients: same core, no ask_user flag.
        model = next(m['id'] for m in core.get('/api/models')['models'])
        core.post('/api/load', {'model': model})
        core.chat('qa-api-client', 'api client: list tools', model, functions={'files': True})
        sent = [b for b in REQUESTS if 'api client' in json.dumps(b.get('messages'))]
        names = [t['function']['name'] for t in (sent[-1].get('tools') or [])] if sent else []
        good = bool(names) and 'agent__ask_user' not in names
        ok.append(good)
        print(f"  {'OK  ' if good else 'FAIL'} an API client (no ask_user flag) never gets the question tool — {names[:6]}", flush=True)
    print('RESULT', 'OK' if all(ok) else 'FAIL', f'({sum(ok)}/{len(ok)})')
    sys.exit(0 if all(ok) else 1)


if __name__ == '__main__':
    main()
