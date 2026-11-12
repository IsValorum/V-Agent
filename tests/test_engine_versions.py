"""Engine updates keep the active and previous version only, reuse unchanged parts, leave no archives."""
import hashlib
import io
import os
import sys
import tempfile
import time
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

TMP = tempfile.mkdtemp(prefix='va-engines-')
os.environ['STRATA_AGENT_DATA'] = TMP
sys.path[:0] = ['agent', '.']
import engine_updates  # noqa: E402


def zipped(files):
    data = io.BytesIO()
    with zipfile.ZipFile(data, 'w') as z:
        for name, body in files.items():
            z.writestr(name, body)
    return data.getvalue()


class Response(io.BytesIO):
    def __enter__(self): return self
    def __exit__(self, *a): self.close()


class _Inline:
    """threading.Thread that runs its work at start(): no timing, no flaky waits on a busy PC."""
    def __init__(self, target=None, args=(), kwargs=None, **_):
        self.target, self.args, self.kwargs = target, args, kwargs or {}
    def start(self):
        self.target(*self.args, **self.kwargs)


class EngineVersionTests(unittest.TestCase):
    def setUp(self):
        # Another test module may have imported runtime_paths first with its own data folder.
        for patcher in (patch.object(engine_updates, 'DATA_ROOT', Path(TMP)), patch.object(engine_updates.threading, 'Thread', _Inline)):
            patcher.start(); self.addCleanup(patcher.stop)
        self.root = Path(TMP) / 'engine-updates'
        self.downloads = []
        self.updates = engine_updates.Updates(lambda: {})
        self.wait()

    def asset(self, name, body):
        return {'name': name, 'size': len(body), 'digest': 'sha256:' + hashlib.sha256(body).hexdigest(),
                'browser_download_url': 'https://github.com/ggml-org/llama.cpp/releases/download/x/' + name}

    def release(self, tag, server=b'server', cudart=b'cudart-12.4'):
        main_body = zipped({'llama-server.exe': server + tag.encode()})
        dep_body = zipped({'cudart64_12.dll': cudart})
        main = self.asset('llama-%s-bin-win-cuda-12.4-x64.zip' % tag, main_body)
        dep = self.asset('cudart-llama-bin-win-cuda-12.4-x64.zip', dep_body)
        self.updates.state.setdefault('releases', {})['llama-cuda'] = {'tag': tag, 'asset': main, 'dependencies': [dep]}
        bodies = {main['browser_download_url']: main_body, dep['browser_download_url']: dep_body}

        def urlopen(request, timeout=0):
            self.downloads.append(request.full_url.rsplit('/', 1)[1])
            return Response(bodies[request.full_url])
        return urlopen

    def wait(self):
        pass  # work runs inline (see _Inline)

    def install(self, tag, **kw):
        ok = type('R', (), {'returncode': 0, 'stdout': 'version', 'stderr': ''})()
        with patch.object(engine_updates.urllib.request, 'urlopen', self.release(tag, **kw)), \
             patch.object(engine_updates.subprocess, 'run', return_value=ok):
            self.updates.install('llama-cuda')

    def folders(self):
        return sorted(p.name.split('-')[0] for p in (self.root / 'llama-cuda').iterdir())

    def test_three_updates_keep_two_versions_without_archives(self):
        for tag in ('b1', 'b2', 'b3'):
            self.install(tag)
        self.assertEqual(self.folders(), ['b2', 'b3'])
        leftovers = [p for p in (self.root / 'llama-cuda').rglob('*.zip')]
        self.assertEqual(leftovers, [])
        # cudart did not change: downloaded once, then linked into each new version.
        self.assertEqual(sum('cudart' in name for name in self.downloads), 1)
        active = Path(engine_updates.active_installations()['llama-cuda']['executable'])
        self.assertEqual((active.parent / 'cudart64_12.dll').read_bytes(), b'cudart-12.4')

        self.updates.rollback('llama-cuda')
        self.assertIn('b2', engine_updates.active_installations()['llama-cuda']['tag'])
        self.updates.prune('llama-cuda')
        self.assertEqual(self.folders(), ['b2', 'b3'])  # the version rolled back from is kept

    def test_changed_dependency_is_downloaded_again_and_failures_leave_nothing(self):
        self.install('c1')
        self.install('c2', cudart=b'cudart-12.8')
        self.assertEqual(sum('cudart' in name for name in self.downloads), 2)
        before = self.folders()
        bad = type('R', (), {'returncode': 1, 'stdout': '', 'stderr': 'crash'})()
        with patch.object(engine_updates.urllib.request, 'urlopen', self.release('c3')), \
             patch.object(engine_updates.subprocess, 'run', return_value=bad):
            self.updates.install('llama-cuda')
        self.assertEqual(self.folders(), before)
        self.assertIn('c2', engine_updates.active_installations()['llama-cuda']['tag'])


def tearDownModule():
    import shutil
    shutil.rmtree(TMP, ignore_errors=True)


if __name__ == '__main__':
    unittest.main()
