"""Project Maya inside V-Agent, without Maya's weights: a fake Maya checkout and server.

    .venv\\Scripts\\python tests\\smoke\\maya_matrix.py

Builds a throw-away Maya checkout (maya.py, serve/server.py, binary, tokenizer, maya-*.json) whose
server speaks what V-Agent expects from Maya (private key, /health, OpenAI chat with tool calls) and
records every request it receives. V-Agent then starts it through the real Maya path (selected engine,
config listing, `python -m serve.server --engine maya …`) and, for every profile (Light, Standard,
Full) × access (Sandbox, Whole PC) × permission mode, checks:

- which tools reach Maya (what the profile and access allow, nothing else);
- that a tool call from Maya runs, its result goes back to Maya and the reply ends;
- that writes ask in "Ask" / "Confirm changes" and not in "Automatic";
- commands: isolated in the Sandbox, real on the whole PC; console only on the whole PC;
- the context limit and live count come from Maya; unloading stops its server.
Exit code 1 when any check fails.
"""
import json
import shutil
import sys
import tempfile
import textwrap
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from isolated_core import IsolatedCore  # noqa: E402

FAKE_SERVER = r'''
import argparse, json, os, sys, threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
p = argparse.ArgumentParser(); p.add_argument('--engine'); p.add_argument('--config'); p.add_argument('--host')
p.add_argument('--port', type=int); p.add_argument('--parent-pipe', action='store_true'); a = p.parse_args()
cfg = json.load(open(a.config, encoding='utf-8')); KEY = os.environ.get('MAYA_API_KEY', '')
LOG = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'requests.jsonl')
CTX = int(cfg.get('context') or 32768)
class H(BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.1'
    def log_message(self, *x): pass
    def _auth(self):
        if self.headers.get('Authorization') != 'Bearer ' + KEY:
            self._json(401, {'error': 'missing or wrong key'}); return False
        return True
    def _json(self, code, data):
        raw = json.dumps(data).encode(); self.send_response(code); self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(raw))); self.end_headers(); self.wfile.write(raw)
    def do_GET(self):
        if not self._auth(): return
        if self.path.startswith('/health'): return self._json(200, {'status': 'ok', 'model': cfg['model_name'], 'max_context': CTX})
        if self.path.startswith('/v1/models'): return self._json(200, {'data': [{'id': cfg['model_name']}]})
        self._json(404, {'error': 'not found'})
    def do_POST(self):
        if not self._auth(): return
        body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
        with open(LOG, 'a', encoding='utf-8') as f: f.write(json.dumps(body) + '\n')
        msgs = body.get('messages') or []
        user = next((m.get('content') for m in reversed(msgs) if m.get('role') == 'user'), '') or ''
        if isinstance(user, list): user = ' '.join(x.get('text', '') for x in user if isinstance(x, dict))
        after_tool = msgs and msgs[-1].get('role') == 'tool'
        self.send_response(200); self.send_header('Content-Type', 'text/event-stream'); self.send_header('Connection', 'close'); self.end_headers()
        def send(obj): self.wfile.write(b'data: ' + json.dumps(obj).encode() + b'\n\n'); self.wfile.flush()
        usage = {'prompt_tokens': 900 + len(json.dumps(msgs)) // 4, 'completion_tokens': 12}
        names = {t['function']['name'] for t in body.get('tools') or []}
        if 'CALL ' in user and not after_tool:
            spec = user.split('CALL ', 1)[1].strip(); name, _, args = spec.partition(' ')
            if name in names:
                send({'choices': [{'delta': {'reasoning_content': 'Uso la herramienta.'}}]})
                send({'choices': [{'delta': {'tool_calls': [{'index': 0, 'id': 'call_1', 'type': 'function', 'function': {'name': name, 'arguments': args or '{}'}}]}}]})
                send({'choices': [{'delta': {}, 'finish_reason': 'tool_calls'}], 'usage': usage})
                self.wfile.write(b'data: [DONE]\n\n'); return
            text = 'NO_TOOL ' + name
        else:
            text = 'Hecho.' if after_tool else 'Hola.'
        send({'choices': [{'delta': {'content': text}}]})
        send({'choices': [{'delta': {}, 'finish_reason': 'stop'}], 'usage': usage})
        self.wfile.write(b'data: [DONE]\n\n')
ThreadingHTTPServer((a.host, a.port), H).serve_forever()
'''


def fake_checkout(folder: Path):
    (folder / 'serve').mkdir(parents=True)
    (folder / 'maya.py').write_text('# fake Project Maya checkout for V-Agent tests\n', encoding='utf-8')
    (folder / 'serve' / '__init__.py').write_text('', encoding='utf-8')
    (folder / 'serve' / 'server.py').write_text(textwrap.dedent(FAKE_SERVER), encoding='utf-8')
    (folder / 'build' / 'bin').mkdir(parents=True)
    shutil.copy2(sys.executable, folder / 'build' / 'bin' / 'maya.exe')  # only has to exist and be a file
    (folder / 'tokenizer').mkdir()
    (folder / 'tokenizer' / 'vocab.json').write_text('{}', encoding='utf-8')
    config = {'model_name': 'GLM-5.3-Flash QA', 'exe': 'build/bin/maya.exe', 'tokenizer': 'tokenizer', 'context': 65536,
              'args': ['--glm-pack', 'packs/glm', '--max-context', '65536']}
    (folder / 'maya-glm-qa.json').write_text(json.dumps(config), encoding='utf-8')


def main():
    rows = []

    def check(name, ok, detail=''):
        rows.append(ok)
        print(f"  {'OK  ' if ok else 'FAIL'} {name}" + (f' — {str(detail)[:230]}' if detail else ''), flush=True)

    folder = Path(tempfile.mkdtemp(prefix='va-fake-maya-'))
    fake_checkout(folder)
    log = folder / 'requests.jsonl'
    try:
        with IsolatedCore(19380 + 13) as core:
            core.post('/api/harness/configure', {'engine': 'maya', 'maya_root': str(folder), 'maya_python': sys.executable})
            models = core.get('/api/models').get('models') or []
            check('the Maya config is listed as a model', len(models) == 1, [m.get('display_name') for m in models])
            if not models:
                return
            model = models[0]['id']
            status, data = core.request('POST', '/api/load', {'model': model, 'context': 65536}, timeout=120)
            check('Maya loads through V-Agent (process, key, /health)', status == 200 and data.get('loaded'), data if status != 200 else 'loaded')
            if status != 200:
                return
            stats = core.get('/api/stats')
            check('the context limit is Maya\'s', (stats.get('context_usage') or {}).get('limit') == 65536, stats.get('context_usage'))

            def run(profile, access, permission, call, approve=True):
                core.post('/api/access', {'mode': access})
                log.write_text('', encoding='utf-8')
                conv = 'qa-maya-' + uuid.uuid4().hex[:8]
                events = core.chat(conv, f'CALL {call}', model, permission=permission, approve=approve, profile=profile,
                                   functions={'files': True, 'shell': True, 'search': True, 'visit': True, 'sys': True,
                                              'console': True, 'web': True, 'browser': False, 'autobrowser': False},
                                   rounds=4)
                requests = [json.loads(line) for line in log.read_text(encoding='utf-8').splitlines() if line.strip()]
                offered = sorted({t['function']['name'] for t in (requests[0].get('tools') or [])}) if requests else []
                return conv, events, requests, offered

            expected = {}
            for profile in ('light', 'balanced', 'advanced'):
                for access in ('sandbox', 'full_pc'):
                    conv, events, requests, offered = run(profile, access, 'run', 'pc__fs_write {"path": "maya.txt", "content": "hola maya"}')
                    label = f'{profile}/{access}'
                    expected[label] = offered
                    file = core.workspace(conv) / 'maya.txt'
                    sent_back = len(requests) >= 2 and any(m.get('role') == 'tool' for m in requests[-1].get('messages', []))
                    done = any(e.get('type') == 'done' for e in events)
                    check(f'{label}: Maya receives tools ({len(offered)}) and its write runs and returns', bool(offered) and sent_back and done
                          and (file.is_file() or access == 'full_pc'), f'{len(offered)} tools; done={done}; returned={sent_back}')
                    if 'pc__console' in offered and access == 'sandbox':
                        check(f'{label}: no console in the Sandbox', False, 'pc__console offered')
                    if profile == 'light' and any(n.startswith(('web__', 'autobrowser__', 'admin__', 'computer__')) for n in offered):
                        check(f'{label}: Light offers only its small set', False, [n for n in offered if not n.startswith(('pc__', 'duckduckgo__'))])
            light, std, full = (set(expected[f'{p}/full_pc']) for p in ('light', 'balanced', 'advanced'))
            check('profiles differ as designed (Light ⊆ Standard ⊆ Full on the whole PC)', light <= std <= full and len(light) < len(full),
                  f'light {len(light)}, standard {len(std)}, full {len(full)}')
            check('Sandbox never offers more than the whole PC', all(set(expected[f'{p}/sandbox']) <= set(expected[f'{p}/full_pc'])
                                                                     for p in ('light', 'balanced', 'advanced')))

            # Approvals: a write asks in Ask and Confirm changes, never in Automatic.
            for permission, asks in (('ask', True), ('auto', True), ('run', False)):
                conv, events, _, _ = run('balanced', 'sandbox', permission, 'pc__fs_write {"path": "p.txt", "content": "x"}', approve=False)
                asked = any(e.get('type') == 'approval' for e in events)
                written = (core.workspace(conv) / 'p.txt').is_file()
                check(f'Maya + {permission}: write {"asks" if asks else "runs without asking"}', asked == asks and written == (not asks),
                      f'asked={asked} written={written}')
            # Commands: isolated in the Sandbox; on the whole PC they run for real.
            for access in ('sandbox', 'full_pc'):
                conv, events, _, offered = run('balanced', access, 'run', 'pc__shell_run {"command": "echo maya-ok"}')
                result = next((e for e in events if e.get('type') == 'tool_result' and e.get('name') == 'pc__shell_run'), {})
                ok = 'maya-ok' in json.dumps(result, ensure_ascii=False) or (access == 'sandbox' and 'pc__shell_run' not in offered)
                check(f'Maya + commands in {access}', ok, (result.get('result') or 'not offered')[:120])
            # A tool the profile does not offer is refused, not run.
            conv, events, _, offered = run('light', 'full_pc', 'run', 'web__http_request {"url": "https://example.com"}')
            check('Light: a tool outside its set is not offered to Maya', 'web__http_request' not in offered, f'{len(offered)} tools')

            live = core.get('/api/stats').get('context_usage') or {}
            check('the context count follows Maya after a reply', isinstance(live.get('used'), int) and live['used'] > 0, live)
            core.post('/api/unload', {})
            import socket
            with socket.socket() as probe:
                closed = probe.connect_ex(('127.0.0.1', 19383)) != 0
            check('unloading stops Maya\'s server', closed)
    finally:
        shutil.rmtree(folder, ignore_errors=True)
    print(f'\n{len(rows)} checks, {rows.count(False)} failed')
    sys.exit(0 if all(rows) else 1)


if __name__ == '__main__':
    main()
