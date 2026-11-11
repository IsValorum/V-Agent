"""Signed minor updates ("components") for V-Agent: MCP servers, web search, tool descriptions.

Smaller and faster than a full installer. Same trust model as app_updates.py:
  * a GitHub release tagged  components-<app version>-r<revision>  with the component files plus
    v-agent-components.json and v-agent-components.json.sig (Ed25519, maintainer's key);
  * only files on the ALLOWED list can be replaced, only for the exact app version they were built
    for, and only with a higher revision than the one installed;
  * every start re-verifies the signature and every file hash before the overlay is used; anything
    unexpected and V-Agent silently runs its original, bundled code.
The overlay lives in %LOCALAPPDATA%/V-Agent-Data/components and can be removed from Settings.
"""
import hashlib
import json
import re
import shutil
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from runtime_paths import DATA_ROOT
import app_updates

MANIFEST = 'v-agent-components.json'
ROOT = DATA_ROOT / 'components'
# Files that can be updated without a new installer: leaf modules (MCP servers and their helpers,
# tool descriptions) that the core and every MCP process import by name, plus two interface patches
# (ui-patch.css / ui-patch.js) that the window loads on top of the bundled interface at startup.
ALLOWED = {
    'pc_mcp.py', 'browser_mcp.py', 'computer_mcp.py', 'admin_mcp.py', 'hf_mcp.py', 'buscador_mcp.py',
    'busqueda_local.py', 'http_tools_mcp.py', 'mcp_prompt.py', 'tool_budget.py', 'verify.py',
    'render_check.py', 'scene_probe.js', 'ui-patch.css', 'ui-patch.js',
}
MAX_FILE = 2 * 2**20


def validate(manifest_bytes, signature, version=None, public_key=None):
    """Return the manifest when authentic and meant for this app version; raise ValueError otherwise."""
    version = version or app_updates.VERSION
    if not app_updates.verify_signature(manifest_bytes, signature, public_key or app_updates.PUBLIC_KEY):
        raise ValueError('The component signature is not valid; it was not published by the V-Agent maintainer.')
    data = json.loads(manifest_bytes.decode('utf-8'))
    if data.get('product') != 'V-Agent' or data.get('channel') != 'components':
        raise ValueError('This is not a V-Agent component manifest.')
    if data.get('app_version') != version:
        raise ValueError('These components were built for V-Agent %s.' % data.get('app_version'))
    if type(data.get('revision')) is not int or data['revision'] < 1:
        raise ValueError('Invalid component revision.')
    files = data.get('files')
    if not isinstance(files, list) or not files:
        raise ValueError('The component manifest lists no files.')
    for item in files:
        if item.get('name') not in ALLOWED:
            raise ValueError('Component %r cannot be updated through this channel.' % item.get('name'))
        if not re.fullmatch(r'[0-9a-f]{64}', str(item.get('sha256', ''))) or type(item.get('size')) is not int \
                or not 0 < item['size'] <= MAX_FILE:
            raise ValueError('Invalid entry for %s.' % item['name'])
    return data


def _active_file():
    return ROOT / 'active.json'


def active_overlay():
    """Folder with verified component files for this app version, or None. Called at every start."""
    try:
        record = json.loads(_active_file().read_text(encoding='utf-8'))
        manifest = record['manifest'].encode('utf-8')
        data = validate(manifest, record['signature'])
        folder = ROOT / ('r%d' % data['revision'])
        for item in data['files']:
            path = folder / item['name']
            if hashlib.sha256(path.read_bytes()).hexdigest() != item['sha256']:
                return None
        return folder
    except Exception:
        return None


def enable_overlay():
    """Serve verified component modules before the bundled ones (core and every MCP process).

    A meta-path finder is needed: in the packaged app PyInstaller's importer runs before sys.path,
    so adding a folder to sys.path would never win. Only names on ALLOWED are redirected.
    """
    import importlib.abc
    import importlib.util
    folder = active_overlay()
    if not folder or any(getattr(f, 'v_agent_components', None) for f in sys.meta_path):
        return folder

    class ComponentFinder(importlib.abc.MetaPathFinder):
        v_agent_components = str(folder)

        def find_spec(self, name, path=None, target=None):
            file = folder / (name + '.py')
            if '.' not in name and file.name in ALLOWED and file.is_file():
                return importlib.util.spec_from_file_location(name, file)
            return None

    sys.meta_path.insert(0, ComponentFinder())
    return folder


def resource(name, bundled):
    """Path of a non-Python component (e.g. scene_probe.js): the verified update, else the bundled file."""
    folder = active_overlay() if name in ALLOWED else None
    candidate = folder / name if folder else None
    return candidate if candidate and candidate.is_file() else Path(bundled)


class Components:
    def __init__(self, repository=None):
        self.repository = app_updates.REPOSITORY if repository is None else repository
        self.lock = threading.RLock()
        self.state = {'revision': self.installed_revision(), 'available': None, 'error': '', 'busy': False,
                      'checked_at': 0, 'configured': bool(self.repository), 'restart_needed': False}

    @staticmethod
    def installed_revision():
        try:
            record = json.loads(_active_file().read_text(encoding='utf-8'))
            return validate(record['manifest'].encode('utf-8'), record['signature'])['revision']
        except Exception:
            return 0

    def snapshot(self):
        with self.lock:
            return json.loads(json.dumps(self.state))

    def _get(self, url, limit):
        return app_updates.AppUpdates(self.repository)._get(url, limit)

    def check(self):
        if not self.repository:
            return self.snapshot()
        with self.lock:
            if self.state['busy']:
                return self.snapshot()
            self.state.update(busy=True, error='')
        try:
            releases = json.loads(self._get('https://api.github.com/repos/%s/releases?per_page=30' % self.repository, 2**21))
            prefix = 'components-%s-r' % app_updates.VERSION
            best = None
            for release in releases:
                tag = str(release.get('tag_name', ''))
                if release.get('draft') or not tag.startswith(prefix) or not tag[len(prefix):].isdigit():
                    continue
                if best is None or int(tag[len(prefix):]) > int(best['tag_name'][len(prefix):]):
                    best = release
            available = None
            if best:
                assets = {a.get('name'): a for a in best.get('assets') or []}
                manifest = self._get(assets[MANIFEST]['browser_download_url'], 256 * 1024)
                signature = self._get(assets[MANIFEST + '.sig']['browser_download_url'], 4096).decode('ascii', 'replace')
                data = validate(manifest, signature)
                if data['revision'] > self.installed_revision():
                    for item in data['files']:
                        asset = assets.get(item['name'])
                        if not asset or asset.get('size') != item['size']:
                            raise ValueError('Component %s does not match the signed manifest.' % item['name'])
                        item['url'] = asset['browser_download_url']
                    available = {'revision': data['revision'], 'notes': data.get('notes', ''), 'files': data['files'],
                                 'manifest': manifest.decode('utf-8'), 'signature': signature}
            with self.lock:
                self.state.update(available=available, checked_at=time.time())
        except urllib.error.HTTPError as error:
            # 404: the repository is still private or not created; there is simply nothing published.
            with self.lock:
                self.state.update(available=None, error='' if error.code == 404 else str(error)[:300], checked_at=time.time())
        except Exception as error:
            with self.lock:
                self.state.update(error=str(error)[:300], checked_at=time.time())
        finally:
            with self.lock:
                self.state['busy'] = False
        return self.snapshot()

    def apply(self):
        with self.lock:
            update = self.state.get('available')
            if not update or self.state['busy']:
                raise ValueError('There are no verified components to apply.')
            self.state['busy'] = True
        try:
            data = validate(update['manifest'].encode('utf-8'), update['signature'])
            staging = ROOT / ('r%d.part' % data['revision'])
            shutil.rmtree(staging, ignore_errors=True); staging.mkdir(parents=True)
            for item in update['files']:
                body = self._get(item['url'], item['size'])
                if len(body) != item['size'] or hashlib.sha256(body).hexdigest() != item['sha256']:
                    raise ValueError('Component %s does not match its signed checksum; nothing was changed.' % item['name'])
                (staging / item['name']).write_bytes(body)
            final = ROOT / ('r%d' % data['revision'])
            shutil.rmtree(final, ignore_errors=True); staging.replace(final)
            record = {'manifest': update['manifest'], 'signature': update['signature'], 'applied_at': time.time()}
            tmp = _active_file().with_suffix('.tmp'); tmp.write_text(json.dumps(record), encoding='utf-8'); tmp.replace(_active_file())
            for old in ROOT.glob('r*'):
                if old.is_dir() and old != final:
                    shutil.rmtree(old, ignore_errors=True)
            with self.lock:
                # Interface patches load in the open window; only modules (MCP servers, tools) need a restart.
                restart = any(not item['name'].startswith('ui-patch.') for item in data['files'])
                self.state.update(revision=data['revision'], available=None, restart_needed=restart, error='')
        except Exception as error:
            with self.lock:
                self.state['error'] = str(error)[:300]
            raise
        finally:
            with self.lock:
                self.state['busy'] = False
        return self.snapshot()

    def reset(self):
        """Go back to the components bundled with this V-Agent version."""
        with self.lock:
            _active_file().unlink(missing_ok=True)
            for old in ROOT.glob('r*'):
                shutil.rmtree(old, ignore_errors=True)
            self.state.update(revision=0, restart_needed=True)
        return self.snapshot()


COMPONENTS = Components()
