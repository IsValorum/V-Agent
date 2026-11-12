"""Shared helpers for the interface smoke tools: start the bundled headless Chrome and talk CDP.

The browser is the one V-Agent bundles for page checks (browser/chrome-headless-shell-win64), or the
path in V_AGENT_HEADLESS. Screenshots use device scale 1 and the exact window size, so they show the
whole page as a user at that size would see it.
"""
import asyncio
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for _stream in (sys.stdout, sys.stderr):  # screen texts (⌄, ×, accents) on any console code page
    _stream.reconfigure(encoding='utf-8', errors='replace')
SKIP_TOUR = "try{localStorage.setItem('val-tour-done','1')}catch(e){}"
CLOSE_TOUR = ("[...document.querySelectorAll('.tour-card button')].find(b=>/Saltar|Skip/.test(b.textContent))?.click();"
              "document.querySelector('.update-card-close')?.click()")


def browser_path():
    candidates = [os.environ.get('V_AGENT_HEADLESS', ''),
                  str(ROOT / 'browser' / 'chrome-headless-shell-win64' / 'chrome-headless-shell.exe')]
    for path in candidates:
        if path and Path(path).is_file():
            return path
    raise SystemExit('Headless browser not found: put it in browser/ or set V_AGENT_HEADLESS.')


def free_port():
    with socket.socket() as probe:
        probe.bind(('127.0.0.1', 0))
        return probe.getsockname()[1]


class Browser:
    """One headless Chrome page driven over the DevTools protocol (async context manager)."""

    def __init__(self, width=1280, height=800, scheme='dark'):
        self.width, self.height, self.scheme = width, height, scheme
        self.errors, self.frames = [], []
        self._pending, self._next = {}, 0
        # method → async callback(params) for other DevTools events (they must not await call()).
        self.handlers = {}

    async def __aenter__(self):
        import websockets
        port = free_port()
        self.profile = tempfile.mkdtemp(prefix='va-smoke-')
        self.process = subprocess.Popen(
            [browser_path(), '--headless', f'--remote-debugging-port={port}', f'--user-data-dir={self.profile}',
             f'--window-size={self.width},{self.height}', '--force-device-scale-factor=1', '--hide-scrollbars',
             'about:blank'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        tabs = []
        for _ in range(100):
            try:
                tabs = json.load(urllib.request.urlopen(f'http://127.0.0.1:{port}/json/list', timeout=1))
                break
            except OSError:
                time.sleep(.1)
        url = next(t['webSocketDebuggerUrl'] for t in tabs if t['type'] == 'page')
        self.socket = await websockets.connect(url, max_size=None)
        self.reader = asyncio.create_task(self._read())
        for method in ('Runtime.enable', 'Page.enable'):
            await self.call(method)
        await self.call('Emulation.setDeviceMetricsOverride',
                        {'width': self.width, 'height': self.height, 'deviceScaleFactor': 1, 'mobile': False})
        await self.call('Emulation.setEmulatedMedia', {'features': [{'name': 'prefers-color-scheme', 'value': self.scheme}]})
        await self.call('Page.addScriptToEvaluateOnNewDocument', {'source': SKIP_TOUR})
        return self

    async def __aexit__(self, *error):
        self.reader.cancel()
        await self.socket.close()
        self.process.kill()
        self.process.wait()
        shutil.rmtree(self.profile, ignore_errors=True)

    async def _read(self):
        async for raw in self.socket:
            message = json.loads(raw)
            method = message.get('method')
            if method == 'Runtime.exceptionThrown':
                details = message['params']['exceptionDetails']
                self.errors.append((details.get('exception') or {}).get('description', details.get('text', ''))[:300])
            elif method == 'Runtime.consoleAPICalled' and message['params']['type'] == 'error':
                self.errors.append('console: ' + ' '.join(str(a.get('value', a.get('description', '')))
                                                          for a in message['params']['args'])[:300])
            elif method == 'Page.screencastFrame':
                self.frames.append((time.monotonic(), message['params']['data']))
                await self.socket.send(json.dumps({'id': 0, 'method': 'Page.screencastFrameAck',
                                                   'params': {'sessionId': message['params']['sessionId']}}))
            elif method in self.handlers:
                await self.handlers[method](message['params'])
            elif message.get('id') in self._pending:
                self._pending.pop(message['id']).set_result(message)

    async def send(self, method, params):
        """Fire a command without waiting for its answer (for use inside event handlers)."""
        await self.socket.send(json.dumps({'id': 0, 'method': method, 'params': params}))

    async def call(self, method, params=None):
        self._next += 1
        future = asyncio.get_running_loop().create_future()
        self._pending[self._next] = future
        await self.socket.send(json.dumps({'id': self._next, 'method': method, 'params': params or {}}))
        message = await asyncio.wait_for(future, 120)
        return message.get('result', {})

    async def open(self, url):
        await self.call('Page.navigate', {'url': url})
        await asyncio.sleep(4)
        await self.run(CLOSE_TOUR)
        await asyncio.sleep(.5)

    async def run(self, script):
        """Run a step (async function body). Returns its value, or raises with the page's error."""
        result = await self.call('Runtime.evaluate', {'expression': '(async()=>{' + script + '})()',
                                                      'awaitPromise': True, 'returnByValue': True})
        if result.get('exceptionDetails'):
            details = result['exceptionDetails']
            raise RuntimeError((details.get('exception') or {}).get('description', details.get('text', 'step failed'))[:300])
        return (result.get('result') or {}).get('value')
