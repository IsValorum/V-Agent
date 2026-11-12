"""Drive real models through V-Agent's own API, the way the interface does, on each local engine.

    .venv\\Scripts\\python tests\\smoke\\real_models.py --llama D:\\models\\small.gguf
    .venv\\Scripts\\python tests\\smoke\\real_models.py --strata D:\\models\\lfm2.gguf --unsupported D:\\models\\small.gguf
    .venv\\Scripts\\python tests\\smoke\\real_models.py --rust D:\\models\\qwen3-moe.gguf --report build\\rust.json

A core is started from source with a throw-away data folder (see isolated_core.py). The engines
already installed by V-Agent are reused (`--engines-from`, default %LOCALAPPDATA%\\V-Agent-Data);
nothing else from the real installation is read or written.

Requests are written like a user would, in Spanish and without naming tools. For each engine given:

- the model loads, and the engine's private server refuses requests without its key (llama.cpp,
  Strata Rust); the core refuses a foreign Host header (DNS rebinding);
- a Python file and a web page that remembers its theme are created and really work;
- an edit changes the file, and a denied approval in "Ask" mode leaves it untouched;
- leaving a reply half way stops the engine, and the next request still works;
- two chats at once each write only in their own folder;
- malformed requests get a 4xx and the core keeps answering;
- `--unsupported`: a model the engine cannot run is refused with a clear message, quickly;
- unloading closes the engine's server.

A check the model did not give the chance to make (for example it answered without trying to write)
is reported as "skipped", never as passed. Exit code 1 when any check fails.
"""
import argparse
import json
import socket
import sys
import threading
import time
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from isolated_core import ROOT, IsolatedCore  # noqa: E402

ENGINE_PORT = 19383  # llama.cpp and Strata Rust listen here, behind a per-session key
GENERATING = ('reading', 'generating', 'decoding')


class Results:
    def __init__(self):
        self.rows = []

    def add(self, engine, name, status, detail='', seconds=None):
        self.rows.append({'engine': engine, 'check': name, 'status': status, 'detail': str(detail)[:300],
                          'seconds': round(seconds, 1) if seconds is not None else None})
        mark = {'pass': 'OK     ', 'fail': 'FAIL   ', 'skip': 'SKIPPED'}[status]
        print(f'  {mark} {name}' + (f' — {detail}' if detail else ''), flush=True)

    def check(self, engine, name, ok, detail='', seconds=None):
        self.add(engine, name, 'pass' if ok else 'fail', detail, seconds)
        return ok


def tools_used(events):
    return [(e.get('name'), e.get('ok')) for e in events if e.get('type') == 'tool_result']


def errors_in(events):
    return [e for e in events if e.get('type') in ('error', 'http_error')]


def read(path):
    return path.read_text(encoding='utf-8', errors='replace') if path.is_file() else None


def engine_port_open():
    with socket.socket() as probe:
        return probe.connect_ex(('127.0.0.1', ENGINE_PORT)) == 0


def run_engine(core, results, engine, model_path, unsupported=None, context=8192):
    print(f'\n== {engine}: {Path(model_path).name}', flush=True)
    core.post('/api/harness/configure', {'engine': engine, 'variant': 'cuda'} if engine == 'llama' else {'engine': engine})
    started = time.time()
    try:
        model = core.post('/api/models/register', {'path': str(model_path)}, timeout=900)['model']['id']
        loaded = core.post('/api/load', {'model': model, 'context': context}, timeout=1800).get('loaded')
    except RuntimeError as error:
        results.check(engine, 'model loads', False, error, time.time() - started)
        return
    if not results.check(engine, 'model loads', loaded, f'context {context}', time.time() - started):
        return

    # The engine's own server and the core's Host check.
    if engine in ('llama', 'rust'):
        import http.client
        for method, path in (('GET', '/v1/models'), ('POST', '/v1/chat/completions')):
            connection = http.client.HTTPConnection('127.0.0.1', ENGINE_PORT, timeout=10)
            body = json.dumps({'messages': [{'role': 'user', 'content': 'hola'}], 'max_tokens': 4}) if method == 'POST' else None
            connection.request(method, path, body, {'Content-Type': 'application/json'})
            status = connection.getresponse().status
            connection.close()
            results.check(engine, f'engine server refuses {method} {path} without its key', status == 401, f'HTTP {status}')
    usage = (core.get('/api/stats').get('context_usage') or {}).get('limit')
    results.check(engine, 'the core reads the engine (with its key)', usage == context, f'context limit {usage}')
    status, _ = core.request('GET', '/api/v1/sessions', host='attacker.example:19381')
    results.check(engine, 'the core refuses a foreign Host header', status == 421, f'HTTP {status}')

    # A Python file that compiles.
    conversation = f'qa-{engine}-py-{uuid.uuid4().hex[:8]}'
    started = time.time()
    events = core.chat(conversation, 'Crea utilidades.py con una función que calcule el promedio de una lista de '
                                     'números, y asegúrate de que no tenga errores.', model)
    folder = core.workspace(conversation)
    # Small models sometimes translate the name (utilities.py): any new Python file counts, and its name is reported.
    created = sorted(p for p in folder.glob('*.py')) if folder.is_dir() else []
    detail = tools_used(events)
    if not created:
        results.check(engine, 'creates the Python file it was asked for', False, detail, time.time() - started)
    else:
        name = 'utilidades.py' if (folder / 'utilidades.py') in created else created[0].name
        try:
            compile(read(folder / name), name, 'exec')
            results.check(engine, 'creates the Python file it was asked for and it compiles', True, f'{name}; {detail}', time.time() - started)
        except SyntaxError as error:
            results.check(engine, 'creates the Python file it was asked for and it compiles', False, f'{name}: {error}', time.time() - started)

    # A web page that stores its theme: it must work where the preview runs it (a sandbox).
    conversation = f'qa-{engine}-web-{uuid.uuid4().hex[:8]}'
    started = time.time()
    events = core.chat(conversation, 'Hazme una página web sencilla de una cafetería en cafeteria.html con un botón '
                                     'para cambiar entre tema claro y oscuro, y que recuerde el tema elegido la '
                                     'próxima vez.', model)
    page = core.workspace(conversation) / 'cafeteria.html'
    if results.check(engine, 'creates cafeteria.html', page.is_file(), tools_used(events), time.time() - started):
        sys.path[:0] = [str(ROOT / 'agent'), str(ROOT)]
        import render_check
        rendered = render_check.render_de_archivo(str(page), espera_ms=1500)
        errors = rendered.get('errores') or []
        # V-Agent's job: the model is told what the sandboxed preview would show. Fixing it is the model's.
        told = ' '.join(json.dumps(e.get('result', ''), ensure_ascii=False) for e in events if e.get('type') == 'tool_result')
        reported = 'SecurityError' in told or 'sandboxed' in told
        results.check(engine, 'the sandboxed-preview error is caught (page clean, or the checker told the model)',
                      not errors or reported,
                      'page opens without errors' if not errors else
                      ('reported to the model, which left it unfixed: ' if reported else 'NOT reported: ') + str(errors[:1])[:140])

    # Edit, then a denied edit.
    conversation = f'qa-{engine}-edit-{uuid.uuid4().hex[:8]}'
    note = core.workspace(conversation) / 'nota.txt'
    core.chat(conversation, 'Crea nota.txt con el texto: version 1', model, permission='auto')
    folder = core.workspace(conversation)
    if not note.is_file() and folder.is_dir():  # small models sometimes translate the name (note.txt)
        note = next(iter(sorted(folder.glob('*.txt'))), note)
    events = core.chat(conversation, 'Cambia nota.txt para que diga: version 2', model, permission='auto')
    results.check(engine, 'edits a file on request', 'version 2' in (read(note) or ''), f'{note.name}: {read(note)!r}')
    before = read(note)
    if before is None:
        results.add(engine, 'a denied approval leaves the file untouched', 'skip', 'nota.txt was never created, so there was nothing to protect')
    events = [] if before is None else core.chat(conversation, 'Ahora cambia nota.txt para que diga: version 3', model, permission='ask', approve=False)
    asked = [e for e in events if e.get('type') == 'approval']
    if before is None:
        pass
    elif not asked:
        results.add(engine, 'a denied approval leaves the file untouched', 'skip',
                    'the model did not try to write this time; covered by test_security_audit.py')
    else:
        results.check(engine, 'a denied approval leaves the file untouched', read(note) == before,
                      f'{len(asked)} approval(s) asked, denied; file {read(note)!r}')

    # Leaving a reply half way.
    import urllib.request
    body = {'model': model, 'conversation_id': f'qa-{engine}-cut-{uuid.uuid4().hex[:8]}', 'effort': 'none',
            'messages': [{'role': 'user', 'content': 'Cuéntame en el chat, sin crear archivos, una historia larga '
                                                     'de unas mil palabras sobre un faro.'}],
            'functions': {}, 'sampling': {'temperature': 0, 'max_tokens': 3000}, 'rounds': 1,
            'agent_profile': 'balanced', 'permission_mode': 'auto'}
    request = urllib.request.Request(core.base + '/api/chat', json.dumps(body).encode(),
                                     {'Content-Type': 'application/json', 'Origin': core.base})
    response = urllib.request.urlopen(request, timeout=300)
    lines = 0
    for line in response:
        lines += line.startswith(b'data: ')
        if lines >= 40:
            break
    response.close()
    cut = time.time()
    state = 'generating'
    while time.time() - cut < 15:
        state = (core.get('/api/stats').get('live') or {}).get('state')
        if state not in GENERATING:
            break
        time.sleep(.25)
    results.check(engine, 'leaving a reply half way stops the engine', state not in GENERATING,
                  f'stopped {time.time() - cut:.1f} s after the client left (state {state})')
    events = core.chat(f'qa-{engine}-after-{uuid.uuid4().hex[:8]}', 'Responde solo con la palabra: listo', model,
                       functions={}, rounds=1, max_tokens=200)
    results.check(engine, 'the next request works', any(e.get('type') == 'done' for e in events) and not errors_in(events),
                  errors_in(events)[:1] or 'finished normally')

    # Two chats at once.
    replies = {}

    def one(name, text):
        conversation = f'qa-{engine}-{name}-{uuid.uuid4().hex[:8]}'
        replies[name] = (conversation, core.chat(conversation, f'Crea {name}.txt con exactamente este texto: {text}', model))

    started = time.time()
    threads = [threading.Thread(target=one, args=args) for args in (('alfa', 'ALFA'), ('bravo', 'BRAVO'))]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(900)
    # One engine answers one reply at a time: the other chat must either finish on its own or be told
    # clearly that a reply is running (409). Files must never land in the other chat's folder.
    for name, text, other in (('alfa', 'ALFA', 'bravo'), ('bravo', 'BRAVO', 'alfa')):
        conversation, events = replies.get(name, (None, []))
        folder = core.workspace(conversation) if conversation else None
        busy = [e for e in events if e.get('type') == 'http_error' and e.get('status') == 409 and 'en curso' in e.get('text', '')]
        mixed = bool(folder) and (folder / f'{other}.txt').exists()
        written = bool(folder) and text in (read(folder / f'{name}.txt') or '') and not errors_in(events)
        outcome = 'written in its own folder' if written else 'told clearly that another reply is running' if busy else 'neither'
        results.check(engine, f'two chats at once: {name} writes only in its own folder or waits its turn',
                      (written or bool(busy)) and not mixed, outcome, time.time() - started)
    results.check(engine, 'two chats at once: at least one of them finishes',
                  any(text in (read(core.workspace(c) / f'{n}.txt') or '') for n, text in (('alfa', 'ALFA'), ('bravo', 'BRAVO'))
                      for c in [replies.get(n, (None,))[0]] if c))

    # Malformed requests.
    for payload, label in ((b'{', 'broken JSON'), (b'[]', 'a list instead of an object'),
                           (json.dumps({'messages': 'x'}).encode(), 'messages that are not a list')):
        status, _ = core.request('POST', '/api/chat', payload, timeout=30)
        results.check(engine, f'/api/chat with {label} gets a 4xx', 400 <= status < 500, f'HTTP {status}')
    results.check(engine, 'the core still answers afterwards', bool(core.get('/api/harness/state')))

    core.post('/api/unload', {}, timeout=120)
    time.sleep(2)
    if engine in ('llama', 'rust'):
        results.check(engine, 'unloading closes the engine server', not engine_port_open())

    if unsupported:
        started = time.time()
        # Refused when it is added or when it is loaded: either way, at once and in words.
        status, data = core.request('POST', '/api/models/register', {'path': str(unsupported)}, timeout=300)
        if status < 400 and isinstance(data, dict):
            status, data = core.request('POST', '/api/load', {'model': data['model']['id'], 'context': 4096}, timeout=300)
        message = data.get('error', '') if isinstance(data, dict) else str(data)
        clear = 'arquitectura' in message or 'architecture' in message
        results.check(engine, 'a model it cannot run is refused with a clear message', status >= 400 and clear,
                      f'{time.time() - started:.1f} s: {message[:160]}', time.time() - started)
        core.request('POST', '/api/unload', {}, timeout=120)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--llama', help='GGUF to run with llama.cpp (a small one is enough)')
    parser.add_argument('--strata', help='GGUF to run with Strata (an architecture it supports)')
    parser.add_argument('--rust', help='GGUF to run with Strata Rust (an architecture it supports)')
    parser.add_argument('--unsupported', help='GGUF that Strata and Strata Rust cannot run, to check the message')
    parser.add_argument('--context', type=int, default=8192)
    parser.add_argument('--engines-from', default=r'%LOCALAPPDATA%\V-Agent-Data')
    parser.add_argument('--port', type=int, default=19381)
    parser.add_argument('--report', help='write the results as JSON here')
    args = parser.parse_args()
    if not (args.llama or args.strata or args.rust):
        parser.error('give at least one of --llama, --strata, --rust')
    results = Results()
    with IsolatedCore(args.port, args.engines_from) as core:
        core.events_dir = ROOT / 'build' / 'quality' / 'events'
        for engine in ('llama', 'strata', 'rust'):
            if getattr(args, engine):
                run_engine(core, results, engine, getattr(args, engine),
                           args.unsupported if engine != 'llama' else None, args.context)
    failed = [row for row in results.rows if row['status'] == 'fail']
    print(f'\n{len(results.rows)} checks: {len(results.rows) - len(failed)} not failed, {len(failed)} failed')
    if args.report:
        Path(args.report).parent.mkdir(parents=True, exist_ok=True)
        Path(args.report).write_text(json.dumps(results.rows, ensure_ascii=False, indent=1), encoding='utf-8')
    sys.exit(1 if failed else 0)


if __name__ == '__main__':
    main()
