"""Start a V-Agent core from source with a throw-away data folder, so nothing touches a real install.

    with IsolatedCore(engines_from=r'%LOCALAPPDATA%\\V-Agent-Data') as core:
        core.post('/api/harness/configure', {'engine': 'llama', 'variant': 'cuda'})

`engines_from` copies only the list of installed engines (engine-updates/active.json, which points at
their executables), never conversations, models or settings. The core is stopped and its folder
deleted on exit, together with any engine it started.
"""
import http.client
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
# Screen texts (⌄, ×, accents) must print on any Windows console code page.
for stream in (sys.stdout, sys.stderr):
    stream.reconfigure(encoding='utf-8', errors='replace')
PYTHON = ROOT / '.venv' / 'Scripts' / 'python.exe'


class IsolatedCore:
    def __init__(self, port=19381, engines_from=None, data_parent=None):
        self.port, self.engines_from, self.data_parent = port, engines_from, data_parent
        self.base = f'http://127.0.0.1:{port}'

    def __enter__(self):
        if self._alive():
            raise SystemExit(f'Port {self.port} is already in use: stop that core first.')
        if self.data_parent:
            Path(self.data_parent).mkdir(parents=True, exist_ok=True)
        self.data = Path(tempfile.mkdtemp(prefix='va-quality-', dir=self.data_parent))
        if self.engines_from:
            source = Path(os.path.expandvars(self.engines_from)) / 'engine-updates' / 'active.json'
            if source.is_file():
                (self.data / 'engine-updates').mkdir(parents=True)
                shutil.copy2(source, self.data / 'engine-updates' / 'active.json')
        env = {**os.environ, 'V_AGENT_NO_AUTO_UPDATE': '1'}
        self.log = open(self.data / 'core-console.log', 'w', encoding='utf-8')
        self.process = subprocess.Popen([str(PYTHON if PYTHON.exists() else sys.executable), 'backend.py', '--port',
                                         str(self.port), '--data-dir', str(self.data), '--', '--background'],
                                        cwd=ROOT, env=env, stdout=self.log, stderr=subprocess.STDOUT,
                                        creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        for _ in range(120):
            if self._alive():
                return self
            if self.process.poll() is not None:
                break
            time.sleep(.5)
        self.__exit__()
        raise SystemExit('The isolated core did not start; see its console log.')

    def __exit__(self, *error):
        try:
            self.post('/api/unload', {}, timeout=60)
        except Exception:
            pass
        if getattr(self, 'process', None) and self.process.poll() is None:
            # The whole tree: the core and the engine or tool servers it started.
            subprocess.run(['taskkill', '/F', '/T', '/PID', str(self.process.pid)], capture_output=True)
            self.process.wait(timeout=30)
        if getattr(self, 'log', None):
            self.log.close()
        time.sleep(1)
        shutil.rmtree(getattr(self, 'data', ''), ignore_errors=True)

    def _alive(self):
        try:
            with urllib.request.urlopen(self.base + '/api/harness/state', timeout=2):
                return True
        except (OSError, urllib.error.URLError):
            return False

    def request(self, method, path, body=None, timeout=300, origin=True, host=None):
        """(status, parsed JSON or text). Never raises for HTTP errors."""
        connection = http.client.HTTPConnection('127.0.0.1', self.port, timeout=timeout)
        headers = {'Content-Type': 'application/json'}
        if origin:
            headers['Origin'] = self.base
        payload = body if isinstance(body, (bytes, type(None))) else json.dumps(body).encode()
        connection.putrequest(method, path, skip_host=host is not None)
        if host is not None:
            connection.putheader('Host', host)
        for key, value in headers.items():
            connection.putheader(key, value)
        connection.putheader('Content-Length', str(len(payload or b'')))
        connection.endheaders(payload)
        response = connection.getresponse()
        raw = response.read().decode('utf-8', 'replace')
        connection.close()
        try:
            return response.status, json.loads(raw)
        except ValueError:
            return response.status, raw

    def get(self, path, timeout=60):
        return self.request('GET', path, timeout=timeout)[1]

    def post(self, path, body, timeout=300):
        status, data = self.request('POST', path, body, timeout=timeout)
        if status >= 400:
            raise RuntimeError(f'{path} → {status}: {data}')
        return data

    def chat(self, conversation, message, model, permission='run', functions=None, rounds=8, approve=True,
             stop_after=None, max_tokens=3000):
        """Send one message and collect the reply's events; answers approvals with `approve`."""
        body = {'model': model, 'conversation_id': conversation, 'messages': [{'role': 'user', 'content': message}],
                'functions': functions if functions is not None else {'files': True}, 'effort': 'none',
                'sampling': {'temperature': 0, 'max_tokens': max_tokens}, 'rounds': rounds,
                'agent_profile': 'balanced', 'permission_mode': permission}
        request = urllib.request.Request(self.base + '/api/chat', json.dumps(body).encode(),
                                         {'Content-Type': 'application/json', 'Origin': self.base})
        events = []
        try:
            with urllib.request.urlopen(request, timeout=900) as response:
                for line in response:
                    if not line.startswith(b'data: '):
                        continue
                    try:
                        event = json.loads(line[6:])
                    except ValueError:
                        continue
                    events.append(event)
                    if event.get('type') == 'approval':
                        self.post('/api/harness/approval', {'id': event['id'], 'allowed': approve})
                    if stop_after and len(events) >= stop_after:
                        break
        except urllib.error.HTTPError as error:
            events.append({'type': 'http_error', 'status': error.code, 'text': error.read().decode('utf-8', 'replace')})
        if getattr(self, 'events_dir', None):  # every reply's events, to see afterwards what the model did
            Path(self.events_dir).mkdir(parents=True, exist_ok=True)
            with open(Path(self.events_dir) / f'{conversation}.jsonl', 'a', encoding='utf-8') as log:
                log.write(json.dumps({'message': message, 'events': events}, ensure_ascii=False) + '\n')
        return events

    def workspace(self, conversation):
        return self.data / 'workspaces' / 'conversations' / conversation
