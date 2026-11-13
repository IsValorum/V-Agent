"""Remote APIs at their edges, against a local fake provider (no account, no key, loopback only).

    .venv\\Scripts\\python tests\\smoke\\api_edge_cases.py [--report build\\quality\\api.json]

The fake provider speaks the OpenAI and Anthropic wire formats and behaves according to the model:
reasoning plus tool calls (DeepSeek style), no usage block, errors (401 echoing the key, 429, 500),
a stream cut half way, a slow stream that the client leaves, a model without declared context, a
1,048,576-token model, and Anthropic thinking blocks with tool use. For each case it checks what a
user needs: the reply arrives, tools run, errors are clear, the key never shows, the core keeps
working and leaving a reply closes the provider connection.
"""
import argparse
import json
import sys
import threading
import time
import urllib.request
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from isolated_core import IsolatedCore  # noqa: E402

KEY = 'sk-fixture-SECRET-1234567890'
MODELS = [{'id': 'reasoner-tools', 'context_length': 131072}, {'id': 'no-usage', 'context_length': 65536},
          {'id': 'err-401'}, {'id': 'err-429', 'context_length': 32768}, {'id': 'err-500', 'context_length': 32768},
          {'id': 'cut-stream', 'context_length': 32768}, {'id': 'slow-stream', 'context_length': 32768},
          {'id': 'huge-context', 'context_length': 1048576}]
STATE = {'slow_closed': None, 'requests': []}


class Provider(BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.1'

    def log_message(self, *args):
        pass

    def _send(self, status, payload, kind='application/json'):
        raw = payload if isinstance(payload, bytes) else json.dumps(payload).encode()
        self.send_response(status)
        self.send_header('Content-Type', kind)
        self.send_header('Content-Length', str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):
        if '/broken/' in self.path:
            return self._send(404, {'error': {'message': f'No route. Key used: {KEY}'}})
        if self.path.split('?')[0].endswith('/models'):
            return self._send(200, {'data': MODELS})
        self._send(404, {'error': 'not found'})

    def _stream(self, chunks, sse_event=False):
        self.send_response(200)
        self.send_header('Content-Type', 'text/event-stream')
        self.send_header('Connection', 'close')
        self.end_headers()
        for chunk in chunks:
            if sse_event:
                self.wfile.write(f"event: {chunk['type']}\ndata: {json.dumps(chunk)}\n\n".encode())
            else:
                self.wfile.write(b'data: ' + (chunk if isinstance(chunk, bytes) else json.dumps(chunk).encode()) + b'\n\n')
            self.wfile.flush()

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers['Content-Length'])) or b'{}')
        STATE['requests'].append(body)
        model = body.get('model')
        if self.path.endswith('/messages'):
            return self._anthropic(body)
        tool_done = any(m.get('role') == 'tool' for m in body.get('messages', []))
        if model == 'err-401':
            return self._send(401, {'error': {'message': f'Incorrect API key provided: {KEY}'}})
        if model == 'err-429':
            return self._send(429, {'error': {'message': 'Rate limit reached. Try again in 20s.'}})
        if model == 'err-500':
            return self._send(500, b'<html>Internal Server Error</html>', 'text/html')
        if model == 'cut-stream':
            self.send_response(200)
            self.send_header('Content-Type', 'text/event-stream')
            self.send_header('Connection', 'close')
            self.end_headers()
            self.wfile.write(b'data: ' + json.dumps({'choices': [{'delta': {'content': 'Empiezo a respon'}}]}).encode() + b'\n\n')
            self.wfile.flush()
            self.close_connection = True
            return
        if model == 'slow-stream':
            self.send_response(200)
            self.send_header('Content-Type', 'text/event-stream')
            self.send_header('Connection', 'close')
            self.end_headers()
            try:
                for _ in range(600):
                    self.wfile.write(b'data: ' + json.dumps({'choices': [{'delta': {'content': 'palabra '}}]}).encode() + b'\n\n')
                    self.wfile.flush()
                    time.sleep(.05)
                STATE['slow_closed'] = False
            except OSError:
                STATE['slow_closed'] = time.time()
            return
        usage = {'prompt_tokens': 321, 'completion_tokens': 9}
        if model == 'reasoner-tools' and not tool_done:
            chunks = [{'choices': [{'delta': {'reasoning_content': 'Necesito listar los archivos.'}}]},
                      {'choices': [{'delta': {'tool_calls': [{'index': 0, 'id': 'call_1', 'type': 'function',
                                                               'function': {'name': 'pc__fs_list', 'arguments': ''}}]}}]},
                      {'choices': [{'delta': {'tool_calls': [{'index': 0, 'function': {'arguments': '{"path": "."}'}}]}}]},
                      {'choices': [{'delta': {}, 'finish_reason': 'tool_calls'}], 'usage': usage}, b'[DONE]']
        else:
            final = {'choices': [{'delta': {}, 'finish_reason': 'stop'}]}
            if model != 'no-usage':
                final['usage'] = usage
            chunks = ([{'choices': [{'delta': {'reasoning_content': 'Ya tengo la lista.'}}]}] if model == 'reasoner-tools' else []) + \
                     [{'choices': [{'delta': {'content': 'Respuesta lista.'}}]}, final, b'[DONE]']
        self._stream(chunks)

    def _anthropic(self, body):
        tool_done = any(isinstance(p, dict) and p.get('type') == 'tool_result'
                        for m in body.get('messages', []) for p in (m.get('content') if isinstance(m.get('content'), list) else []))
        events = [{'type': 'message_start', 'message': {'usage': {'input_tokens': 222, 'output_tokens': 0}}},
                  {'type': 'content_block_start', 'index': 0, 'content_block': {'type': 'thinking', 'thinking': ''}},
                  {'type': 'content_block_delta', 'index': 0, 'delta': {'type': 'thinking_delta', 'thinking': 'Pienso un momento.'}},
                  {'type': 'content_block_stop', 'index': 0}]
        if tool_done:
            events += [{'type': 'content_block_start', 'index': 1, 'content_block': {'type': 'text', 'text': ''}},
                       {'type': 'content_block_delta', 'index': 1, 'delta': {'type': 'text_delta', 'text': 'Respuesta lista.'}},
                       {'type': 'content_block_stop', 'index': 1},
                       {'type': 'message_delta', 'delta': {'stop_reason': 'end_turn'}, 'usage': {'output_tokens': 8}}]
        else:
            events += [{'type': 'content_block_start', 'index': 1, 'content_block': {'type': 'tool_use', 'id': 'tu_1', 'name': 'pc__fs_list', 'input': {}}},
                       {'type': 'content_block_delta', 'index': 1, 'delta': {'type': 'input_json_delta', 'partial_json': '{"path": "."}'}},
                       {'type': 'content_block_stop', 'index': 1},
                       {'type': 'message_delta', 'delta': {'stop_reason': 'tool_use'}, 'usage': {'output_tokens': 12}}]
        events.append({'type': 'message_stop'})
        self._stream(events, sse_event=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--report')
    args = parser.parse_args()
    provider = ThreadingHTTPServer(('127.0.0.1', 0), Provider)
    threading.Thread(target=provider.serve_forever, daemon=True).start()
    base = f'http://127.0.0.1:{provider.server_address[1]}'
    rows = []

    def check(name, ok, detail=''):
        rows.append({'engine': 'api', 'check': name, 'status': 'pass' if ok else 'fail', 'detail': str(detail)[:300]})
        print(f"  {'OK  ' if ok else 'FAIL'} {name}" + (f' — {detail}' if detail else ''), flush=True)

    def texts(events):
        return ' '.join(json.dumps(e, ensure_ascii=False) for e in events)

    with IsolatedCore(19386) as core:
        # A provider whose model list fails: a clear error, and the key never shown.
        core.post('/api/harness/configure', {'engine': 'api', 'protocol': 'openai', 'base_url': base + '/broken/v1',
                                             'api_key': KEY, 'new_connection': True, 'name': 'Broken'})
        status, data = core.request('POST', '/api/harness/connect', {})
        shown = json.dumps(data, ensure_ascii=False)
        check('a failing model list gives an error without the key', status >= 400 and KEY not in shown and 'SECRET' not in shown,
              f'HTTP {status}: {shown[:160]}')

        core.post('/api/harness/configure', {'engine': 'api', 'protocol': 'openai', 'base_url': base + '/v1',
                                             'api_key': KEY, 'new_connection': True, 'name': 'Fake OpenAI'})
        core.post('/api/harness/connect', {})
        ids = {m['id'].split('--')[-1]: m for m in core.get('/api/models')['models']}
        check('all provider models are listed with their context', len(ids) == len(MODELS) and ids['huge-context'].get('context') == 1048576
              and ids['err-401'].get('context') in (None, 0), {k: v.get('context') for k, v in ids.items()})
        check('the stored connection never exposes the key', KEY not in json.dumps(core.get('/api/harness/state')), 'state checked')

        def use(name, context=None):
            model = ids[name]['id']
            core.request('POST', '/api/unload', {})
            status, data = core.request('POST', '/api/load', {'model': model, **({'context': context} if context else {})})
            return model, status, data

        def chat(model, message='Lista los archivos y dime cuántos hay.', **kw):
            return core.chat('qa-api-' + uuid.uuid4().hex[:8], message, model, permission='run', **kw)

        model, status, _ = use('reasoner-tools', 131072)
        events = chat(model)
        types = [e.get('type') for e in events]
        check('reasoning + tool call + answer (OpenAI, DeepSeek style)', 'reasoning' in types and 'tool_result' in types
              and any(e.get('type') == 'done' for e in events), [t for t in types if t not in ('content',)][:12])
        usage = [e for e in events if e.get('type') == 'usage']
        check('the provider usage reaches the context meter', bool(usage) and usage[-1]['usage'].get('prompt_tokens') == 321, usage[-1:] if usage else 'none')
        sent = STATE['requests'][-1]
        check('the tool result is sent back in OpenAI format', any(m.get('role') == 'tool' for m in sent.get('messages', [])), 'role=tool present')

        model, status, _ = use('no-usage')
        events = chat(model, 'Di hola.', functions={})
        limit = (core.get('/api/stats').get('context_usage') or {})
        check('a provider without usage still answers', any(e.get('type') == 'done' for e in events), [e.get('type') for e in events][-3:])

        for name, words in (('err-401', ('401', 'clave', 'key')), ('err-429', ('429', 'límite', 'Rate', 'limit')), ('err-500', ('500',))):
            model, status, data = use(name)
            if status >= 400:
                check(f'{name}: the model can be selected', False, data)
                continue
            events = chat(model, 'Di hola.', functions={})
            joined = texts(events)
            errors = [e for e in events if e.get('type') in ('error', 'http_error')]
            check(f'{name}: a clear error, without the key', bool(errors) and any(w in joined for w in words) and KEY not in joined
                  and 'SECRET' not in joined and '<html>' not in joined, (errors[:1] or events[-1:]))
        check('the core keeps answering after provider errors', bool(core.get('/api/harness/state')))

        model, status, _ = use('cut-stream')
        events = chat(model, 'Di hola.', functions={})
        joined = texts(events)
        check('a stream cut half way is reported, not shown as a full answer',
              any(e.get('type') == 'error' for e in events) or 'interrump' in joined.lower() or 'incomplet' in joined.lower(),
              [e.get('type') for e in events][-4:])

        model, status, _ = use('slow-stream')
        left = time.time()
        chat(model, 'Escribe mucho.', functions={}, stop_after=5)
        for _ in range(40):
            if STATE['slow_closed']:
                break
            time.sleep(.1)
        closed = STATE['slow_closed']
        check('leaving a reply closes the provider connection', bool(closed) and closed - left < 3,
              f'closed {closed - left:.1f} s after leaving' if closed else 'still streaming')
        model, status, _ = use('no-usage')
        check('the next request works after leaving one', any(e.get('type') == 'done' for e in chat(model, 'Di hola.', functions={})))

        model, status, data = use('huge-context', 1048576)
        check('a 1,048,576-token provider model can be used', status == 200, data if status != 200 else 'loaded')
        events = chat(model, 'Di hola.', functions={})
        limit = (core.get('/api/stats').get('context_usage') or {}).get('limit')
        check('its context limit is the provider\'s', limit == 1048576, limit)
        speeds = [e['timings'].get(k) for e in events if isinstance(e.get('timings'), dict)
                  for k in ('predicted_per_second', 'prompt_per_second') if e['timings'].get(k)]
        check('a reply delivered in one burst shows no absurd speed', all(v < 20000 for v in speeds), speeds or 'no speed shown')
        status, data = core.request('POST', '/api/load', {'model': ids['no-usage']['id']})
        check('switching to another provider model needs no unload', status == 200 and
              core.get('/api/stats').get('model') == ids['no-usage']['id'], data if status != 200 else 'switched')

        # Anthropic protocol with thinking and tool use.
        core.post('/api/harness/configure', {'engine': 'api', 'protocol': 'anthropic', 'base_url': base + '/anthropic/v1',
                                             'api_key': KEY, 'new_connection': True, 'name': 'Fake Anthropic'})
        core.post('/api/harness/connect', {})
        model = next(m['id'] for m in core.get('/api/models')['models'] if m['id'].endswith('reasoner-tools'))
        core.request('POST', '/api/unload', {})
        core.post('/api/load', {'model': model})
        events = chat(model)
        types = [e.get('type') for e in events]
        check('thinking + tool use + answer (Anthropic)', 'reasoning' in types and 'tool_result' in types
              and any(e.get('type') == 'done' and 'Respuesta lista' in json.dumps(e, ensure_ascii=False) for e in events), types[-6:])
    provider.shutdown()
    failed = [r for r in rows if r['status'] == 'fail']
    print(f'\n{len(rows)} checks, {len(failed)} failed')
    if args.report:
        Path(args.report).write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding='utf-8')
    sys.exit(1 if failed else 0)


if __name__ == '__main__':
    main()
