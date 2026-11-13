"""Hugging Face model browser: search GGUF repositories, show their card and download a quant.

Everything goes through huggingface.co (API, README, files); downloads are verified against the
SHA-256 that the Hub publishes for each LFS file before the model is added to V-Agent. A token
from the user's own `hf auth login` is used only for gated repositories and is never sent to any
other host (the CDN redirect is followed without it).
"""
import hashlib
import json
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from runtime_paths import DATA_ROOT

HUB = 'https://huggingface.co'
USER_AGENT = 'V-Agent'
SETTINGS = DATA_ROOT / 'hub.json'
REPO = re.compile(r'^[A-Za-z0-9][\w.-]{0,95}/[\w.-]{1,96}$')
SPLIT = re.compile(r'^(?P<base>.+)-(?P<part>\d{5})-of-(?P<total>\d{5})\.gguf$', re.I)
QUANT = re.compile(r'(IQ\d_[A-Z]+|Q\d_K_[SML]|Q\d_K|Q\d_\d|Q\d_[A-Z0-9]+|BF16|F16|F32|MXFP4|TQ\d_\d|UD-[A-Z0-9_]+)', re.I)
SORTS = {'downloads': 'downloads', 'likes': 'likes', 'trending': 'trendingScore', 'updated': 'lastModified'}


def _token():
    try:
        from huggingface_hub import get_token
        return get_token()
    except Exception:
        return None


class _NoAuthRedirect(urllib.request.HTTPRedirectHandler):
    """Follow redirects but never carry the Hub token to another host (e.g. the file CDN)."""
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        new = super().redirect_request(req, fp, code, msg, headers, newurl)
        if new is not None and urllib.parse.urlsplit(newurl).hostname != urllib.parse.urlsplit(req.full_url).hostname:
            new.headers.pop('Authorization', None)
            new.unredirected_hdrs.pop('Authorization', None)
        return new


_OPENER = urllib.request.build_opener(_NoAuthRedirect)


def _request(url, limit=None, auth=False, timeout=20):
    headers = {'User-Agent': USER_AGENT, 'Accept': 'application/json'}
    token = _token() if auth else None
    if token:
        headers['Authorization'] = 'Bearer ' + token
    with _OPENER.open(urllib.request.Request(url, headers=headers), timeout=timeout) as response:
        data = response.read(limit + 1 if limit else -1)
    if limit and len(data) > limit:
        raise ValueError('Respuesta demasiado grande.')
    return data


def _repo(value):
    value = str(value or '').strip()
    if not REPO.fullmatch(value) or '..' in value:
        raise ValueError('Repositorio no válido.')
    return value


def _file(value):
    value = str(value or '').strip().replace('\\', '/')
    parts = value.split('/')
    if not value.lower().endswith('.gguf') or any(p in ('', '.', '..') for p in parts) or len(value) > 300:
        raise ValueError('Archivo no válido.')
    return value


KINDS = {'text': 'text-generation', 'vision': 'image-text-to-text'}


def search(query='', sort='downloads', kind='text', limit=40):
    params = {'filter': 'gguf', 'sort': SORTS.get(sort, 'downloads'), 'direction': '-1', 'limit': str(max(1, min(int(limit), 100)))}
    if kind in KINDS:
        params['pipeline_tag'] = KINDS[kind]
    if query.strip():
        params['search'] = query.strip()[:120]
    data = json.loads(_request(HUB + '/api/models?' + urllib.parse.urlencode(params), 4 * 2**20))
    return [{'id': item.get('id') or item.get('modelId'), 'downloads': item.get('downloads', 0), 'likes': item.get('likes', 0),
             'updated': item.get('lastModified') or item.get('createdAt'), 'pipeline': item.get('pipeline_tag'),
             'tags': [t for t in item.get('tags', []) if ':' not in t][:8]} for item in data if item.get('id') or item.get('modelId')]


def _quant(name):
    match = QUANT.search(Path(name).stem)
    return match.group(1).upper() if match else ''


def details(repo):
    repo = _repo(repo)
    info = json.loads(_request(HUB + '/api/models/' + repo + '?blobs=true', 8 * 2**20, auth=True))
    files, groups = [], {}
    for sibling in info.get('siblings', []):
        name = sibling.get('rfilename', '')
        if not name.lower().endswith('.gguf'):
            continue
        lfs = sibling.get('lfs') or {}
        size = sibling.get('size') or lfs.get('size') or 0
        split = SPLIT.match(Path(name).name)
        key = str(Path(name).parent / split['base']) if split else name
        group = groups.get(key)
        if group is None:
            group = groups[key] = {'name': name, 'size': 0, 'parts': [], 'quant': _quant(split['base'] if split else name),
                                   'mmproj': 'mmproj' in Path(name).name.lower()}
            files.append(group)
        group['parts'].append({'name': name, 'size': size, 'sha256': lfs.get('sha256')})
        group['size'] += size
        if split and int(split['part']) == 1:
            group['name'] = name
    for group in files:
        group['parts'].sort(key=lambda p: p['name'])
    files.sort(key=lambda f: (f['mmproj'], f['size']))
    readme = ''
    if any(s.get('rfilename') == 'README.md' for s in info.get('siblings', [])):
        try:
            readme = _request(HUB + '/' + repo + '/resolve/main/README.md', 512 * 1024, auth=True).decode('utf-8', 'replace')
        except (OSError, ValueError):
            readme = ''
    card = info.get('cardData') or {}
    gguf = info.get('gguf') or {}
    return {'id': info.get('id', repo), 'author': info.get('author') or repo.split('/')[0], 'downloads': info.get('downloads', 0),
            'downloads_all_time': info.get('downloadsAllTime'), 'likes': info.get('likes', 0), 'updated': info.get('lastModified'),
            'created': info.get('createdAt'), 'gated': bool(info.get('gated')), 'license': card.get('license'),
            'base_model': card.get('base_model'), 'pipeline': info.get('pipeline_tag'),
            'architecture': gguf.get('architecture'), 'context': gguf.get('context_length'), 'parameters': gguf.get('total'),
            'tags': [t for t in info.get('tags', []) if ':' not in t][:12], 'files': files, 'readme': readme,
            'url': HUB + '/' + repo}


class Downloads:
    """One download at a time, resumable, verified by SHA-256, then added to V-Agent."""

    def __init__(self, register=None):
        self.lock = threading.RLock()
        self.jobs = {}
        self.queue = []
        self.worker = None
        self.register = register

    def folder(self):
        try:
            saved = json.loads(SETTINGS.read_text(encoding='utf-8')).get('folder')
        except (OSError, ValueError):
            saved = None
        return Path(saved) if saved else DATA_ROOT / 'models'

    def set_folder(self, path):
        folder = Path(str(path or '')).expanduser()
        if not folder.is_absolute():
            raise ValueError('Elige una carpeta completa.')
        folder.mkdir(parents=True, exist_ok=True)
        SETTINGS.parent.mkdir(parents=True, exist_ok=True)
        SETTINGS.write_text(json.dumps({'folder': str(folder)}, ensure_ascii=False), encoding='utf-8')
        return self.snapshot()

    def snapshot(self):
        with self.lock:
            return {'folder': str(self.folder()), 'jobs': [dict(job) for job in self.jobs.values()]}

    def start(self, repo, name):
        repo, name = _repo(repo), _file(name)
        info = details(repo)
        group = next((f for f in info['files'] if f['name'] == name or any(p['name'] == name for p in f['parts'])), None)
        if group is None:
            raise ValueError('Ese archivo no está en el repositorio.')
        ident = hashlib.sha256((repo + '/' + group['name']).encode()).hexdigest()[:16]
        with self.lock:
            current = self.jobs.get(ident)
            if current and current['state'] in ('queued', 'downloading', 'verifying'):
                return self.snapshot()
            self.jobs[ident] = {'id': ident, 'repo': repo, 'name': group['name'], 'parts': group['parts'], 'total': group['size'],
                                'received': 0, 'state': 'queued', 'error': '', 'path': '', 'model': None, 'started': time.time(),
                                'mmproj': group['mmproj']}
            self.queue.append(ident)
            if not self.worker or not self.worker.is_alive():
                self.worker = threading.Thread(target=self._run, daemon=True)
                self.worker.start()
        return self.snapshot()

    def cancel(self, ident):
        with self.lock:
            job = self.jobs.get(ident)
            if not job:
                raise ValueError('Descarga desconocida.')
            if job['state'] in ('queued', 'downloading', 'verifying'):
                job['state'] = 'cancelled'
            elif job['state'] in ('done', 'error', 'cancelled'):
                self.jobs.pop(ident)
        return self.snapshot()

    def _run(self):
        while True:
            with self.lock:
                if not self.queue:
                    return
                ident = self.queue.pop(0)
                job = self.jobs.get(ident)
                if not job or job['state'] == 'cancelled':
                    continue
                job['state'] = 'downloading'
            try:
                path = self._download(job)
                with self.lock:
                    if job['state'] == 'cancelled':
                        continue
                    job['path'] = str(path)
                if self.register and not job['mmproj']:
                    model_id = self.register(path, job)
                    with self.lock:
                        if job['state'] != 'cancelled':
                            job['model'] = model_id
                with self.lock:
                    if job['state'] != 'cancelled':
                        job['state'] = 'done'
            except Exception as error:
                with self.lock:
                    if job['state'] != 'cancelled':
                        job['state'] = 'error'
                        job['error'] = str(error)[:300]

    def _download(self, job):
        target_dir = self.folder() / job['repo'].replace('/', '__')
        target_dir.mkdir(parents=True, exist_ok=True)
        token = _token()
        done = 0
        first = None
        for part in job['parts']:
            final = target_dir / Path(part['name']).name
            first = first or final
            if final.is_file() and final.stat().st_size == part['size']:
                done += part['size']
                with self.lock:
                    job['received'] = done
                continue
            partial = final.with_name(final.name + '.part')
            have = partial.stat().st_size if partial.exists() else 0
            digest = hashlib.sha256()
            if have:
                with partial.open('rb') as stream:
                    while chunk := stream.read(2**22):
                        digest.update(chunk)
            url = HUB + '/' + job['repo'] + '/resolve/main/' + urllib.parse.quote(part['name'])
            headers = {'User-Agent': USER_AGENT}
            if token:
                headers['Authorization'] = 'Bearer ' + token
            if have:
                headers['Range'] = 'bytes=%d-' % have
            try:
                response = _OPENER.open(urllib.request.Request(url, headers=headers), timeout=60)
            except urllib.error.HTTPError as error:
                if error.code in (401, 403):
                    raise ValueError('Este modelo requiere aceptar sus condiciones en Hugging Face e iniciar sesión (hf auth login).') from None
                raise
            with response:
                if have and response.status != 206:
                    have, digest = 0, hashlib.sha256()
                with partial.open('ab' if have else 'wb') as output:
                    size = have
                    while chunk := response.read(2**20):
                        with self.lock:
                            if job['state'] == 'cancelled':
                                raise ValueError('Descarga cancelada.')
                            job['received'] = done + size + len(chunk)
                        output.write(chunk)
                        digest.update(chunk)
                        size += len(chunk)
            if part['size'] and size != part['size']:
                raise ValueError('La descarga quedó incompleta; vuelve a intentarlo para continuarla.')
            with self.lock:
                job['state'] = 'verifying'
            if part.get('sha256') and digest.hexdigest() != part['sha256']:
                partial.unlink(missing_ok=True)
                raise ValueError('El archivo descargado no coincide con el publicado (SHA-256).')
            with self.lock:
                if job['state'] == 'cancelled':
                    raise ValueError('Descarga cancelada.')
            partial.replace(final)
            done += part['size'] or size
            with self.lock:
                if job['state'] == 'cancelled':
                    raise ValueError('Descarga cancelada.')
                job['state'] = 'downloading'
        return first
