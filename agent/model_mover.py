"""Safely move GGUF models (and companion vision/MTP/shard files) into V-Agent's models/ tree.

Layout:
    <models_root>/<creator_or_quantizer>/<model_name>/<files.gguf>
"""
import os
from pathlib import Path
import re
import threading

CHUNK_BYTES = 4 * 1024 * 1024
SHARD_RE = re.compile(r'^(.*)-(\d{5})-of-(\d{5})\.gguf$', re.IGNORECASE)
GENERIC_DIRS = {
    'models', 'model', 'hub', 'downloads', 'download', 'gguf', 'ggufs',
    'lmstudio', '.lmstudio', 'unsloth', '.unsloth', 'studio', 'snapshots',
    'blobs', 'cache', '.cache', 'huggingface', 'local', 'users', 'desktop',
}


def _clean_segment(name, fallback='local'):
    text = re.sub(r'[<>:"/\\|?*\x00-\x1f]+', '-', str(name or '').strip())
    text = re.sub(r'\s+', ' ', text).strip(' .-_')
    if not text or text in ('.', '..'):
        return fallback
    return text[:90].rstrip(' .') or fallback


def is_inside(path, root):
    try:
        Path(path).resolve().relative_to(Path(root).resolve())
        return True
    except (OSError, ValueError):
        return False


def infer_layout(path, group=None, name=None):
    """Return (creator_folder, model_folder) for a GGUF file."""
    gguf = Path(path)
    creator = ''
    model_dir = ''

    # 1. Explicit group from scanner (e.g. "bartowski/Qwen2.5-7B-GGUF" or "models--unsloth--Qwen3-8B-GGUF")
    parts = [p for p in str(group or '').replace('\\', '/').split('/') if p and p != '.']
    for part in parts:
        if part.startswith('models--') and part.count('--') >= 2:
            segs = [s for s in part.split('--')[1:] if s]
            if len(segs) >= 2:
                creator, model_dir = segs[0], '--'.join(segs[1:])
                break
    if not creator and len(parts) >= 2:
        creator, model_dir = parts[0], parts[-1]
    elif not model_dir and len(parts) == 1:
        model_dir = parts[0]

    # 2. Fallback to Hugging Face cache folder (models--Creator--ModelName) anywhere in ancestors
    if not creator:
        for anc in gguf.parents:
            if anc.name.startswith('models--') and anc.name.count('--') >= 2:
                segs = [s for s in anc.name.split('--')[1:] if s]
                if len(segs) >= 2:
                    creator, model_dir = segs[0], '--'.join(segs[1:])
                    break

    # 3. Fallback to parent / grandparent folder names on disk
    parent = gguf.parent.name if gguf.parent else ''
    grandparent = gguf.parent.parent.name if gguf.parent and gguf.parent.parent else ''
    if not model_dir and parent and parent.lower() not in GENERIC_DIRS:
        model_dir = parent
    if not creator and grandparent and grandparent.lower() not in GENERIC_DIRS:
        creator = grandparent

    if not model_dir:
        stem = name or gguf.stem
        m = SHARD_RE.match(gguf.name)
        if m:
            stem = m.group(1)
        model_dir = stem
    if not creator:
        creator = 'local'

    return _clean_segment(creator, 'local'), _clean_segment(model_dir, 'model')


def _is_companion(filename):
    low = filename.lower()
    return (
        low.startswith('mmproj')
        or '-mmproj' in low
        or '_mmproj' in low
        or '-mtp-' in low
        or low.startswith('mtp-')
        or low.endswith('-mtp.gguf')
        or low.endswith('_mtp.gguf')
        or 'draft' in low
    )


def _is_main_gguf(filename):
    low = filename.lower()
    if not low.endswith('.gguf') or _is_companion(low) or 'imatrix' in low:
        return False
    m = SHARD_RE.match(filename)
    if m and m.group(2) != '00001':
        return False
    return True


def collect_model_files(main_path):
    """Return [main_gguf, ...shards, ...vision/MTP companions] in the same folder."""
    main = Path(main_path)
    if not main.is_file():
        return []
    files = [main]
    seen = {os.path.normcase(str(main.resolve()))}
    parent = main.parent

    try:
        entries = sorted(p for p in parent.iterdir() if p.is_file() and p.suffix.lower() == '.gguf')
    except OSError:
        return files

    # 1. Split shards belonging to this main GGUF
    shard_match = SHARD_RE.match(main.name)
    if shard_match:
        prefix, total = shard_match.group(1).lower(), shard_match.group(3)
        for p in entries:
            m = SHARD_RE.match(p.name)
            if m and m.group(1).lower() == prefix and m.group(3) == total:
                key = os.path.normcase(str(p.resolve()))
                if key not in seen:
                    seen.add(key)
                    files.append(p)

    # 2. Companion vision (mmproj) / MTP / draft GGUFs when this folder holds only this model
    # (or when the companion clearly shares the model's base name prefix).
    other_mains = [
        p for p in entries
        if _is_main_gguf(p.name) and os.path.normcase(str(p.resolve())) not in seen
    ]
    base_token = re.split(r'[-_.]', main.stem.lower())[0]
    for p in entries:
        key = os.path.normcase(str(p.resolve()))
        if key in seen or not _is_companion(p.name):
            continue
        if not other_mains or (len(base_token) >= 3 and base_token in p.name.lower()):
            seen.add(key)
            files.append(p)

    return files


class ModelMover:
    """Background worker moving GGUF models into <models_root>/<creator>/<model>/ with live byte progress."""

    def __init__(self, folder_fn, register_fn):
        self._folder = folder_fn
        self._register = register_fn
        self._lock = threading.RLock()
        self._state = self._empty()

    def _empty(self):
        return {
            'active': False,
            'cancel_requested': False,
            'phase': 'idle',
            'current_model': '',
            'current_file': '',
            'files_done': 0,
            'files_total': 0,
            'bytes_done': 0,
            'bytes_total': 0,
            'percent': 0.0,
            'results': [],
            'error': '',
        }

    def snapshot(self):
        with self._lock:
            return {**self._state, 'results': list(self._state['results'])}

    def cancel(self):
        with self._lock:
            if self._state['active']:
                self._state['cancel_requested'] = True
            return self.snapshot()

    def start(self, items):
        if not isinstance(items, list) or not 0 < len(items) <= 100:
            raise ValueError('Elige al menos un modelo.')
        with self._lock:
            if self._state['active']:
                raise ValueError('Ya hay un movimiento de modelos en curso.')
            plans = []
            total_files = 0
            total_bytes = 0
            models_root = Path(self._folder())
            for item in items:
                if not isinstance(item, dict) or not item.get('path'):
                    continue
                files = collect_model_files(item['path'])
                if not files:
                    continue
                creator, model_dir = infer_layout(item['path'], item.get('group'), item.get('name'))
                dest_dir = models_root / creator / model_dir
                sizes = []
                for f in files:
                    try:
                        sz = f.stat().st_size
                    except OSError:
                        sz = 0
                    sizes.append((f, sz))
                    total_bytes += sz
                    total_files += 1
                plans.append({'item': item, 'dest_dir': dest_dir, 'files': sizes})
            if not plans:
                raise ValueError('No se encontraron archivos GGUF válidos para mover.')
            self._state = {
                **self._empty(),
                'active': True,
                'phase': 'moving',
                'files_total': total_files,
                'bytes_total': total_bytes,
            }
        threading.Thread(target=self._run, args=(plans,), daemon=True, name='v-agent-model-mover').start()
        return self.snapshot()

    def _move_one(self, src, dest, size):
        # A Hugging Face cache entry is a link to blobs/<hash>: the file it points at is moved and the link
        # removed (moving the link itself left a link that points nowhere).
        link = src if src.is_symlink() else None
        if link is not None:
            src = src.resolve()
        moved = self._move_file(src, dest, size)
        if link is not None and moved is not None:
            try:
                link.unlink(missing_ok=True)
            except OSError:
                pass
        return moved

    def _move_file(self, src, dest, size):
        dest.parent.mkdir(parents=True, exist_ok=True)
        try:
            if src.resolve() == dest.resolve():
                self._add_bytes(size)
                return dest
        except OSError:
            pass
        if dest.exists():
            # Only a byte-for-byte copy is a duplicate: two versions of a model often have the same size,
            # and deleting the source on size alone lost the newer one.
            import filecmp
            try:
                same = dest.is_file() and dest.stat().st_size == size and filecmp.cmp(src, dest, shallow=False)
            except OSError:
                same = False
            if not same:
                raise ValueError('Ya hay otro archivo llamado %s en %s; no se ha movido.' % (dest.name, dest.parent))
            src.unlink(missing_ok=True)
            self._add_bytes(size)
            return dest
        # Try instant same-volume rename first.
        try:
            os.replace(src, dest)
            self._add_bytes(size)
            return dest
        except OSError:
            pass
        # Cross-volume safe move: chunked copy to .tmp -> verify size -> atomic replace -> unlink source.
        tmp = dest.with_name(dest.name + '.v-agent-moving.tmp')
        copied = 0
        try:
            with open(src, 'rb') as fin, open(tmp, 'wb') as fout:
                while True:
                    with self._lock:
                        if self._state['cancel_requested']:
                            raise InterruptedError('Movimiento cancelado.')
                    chunk = fin.read(CHUNK_BYTES)
                    if not chunk:
                        break
                    fout.write(chunk)
                    copied += len(chunk)
                    self._add_bytes(len(chunk))
                fout.flush()
            if size > 0 and tmp.stat().st_size != size:
                raise OSError('El tamaño del archivo copiado no coincide con el original.')
            os.replace(tmp, dest)
            tmp = None
            for _ in range(3):
                try:
                    src.unlink(missing_ok=True)
                    break
                except PermissionError:
                    import time
                    time.sleep(0.2)
            return dest
        finally:
            if tmp is not None:
                tmp.unlink(missing_ok=True)

    def _add_bytes(self, delta):
        with self._lock:
            self._state['bytes_done'] += delta
            total = self._state['bytes_total']
            self._state['percent'] = round(min(100.0, (100.0 * self._state['bytes_done'] / total)), 1) if total > 0 else 100.0

    def _run(self, plans):
        results = []
        cancelled = False
        try:
            for plan in plans:
                with self._lock:
                    if self._state['cancel_requested']:
                        cancelled = True
                        break
                    self._state['current_model'] = plan['item'].get('name') or plan['dest_dir'].name
                    self._state['phase'] = 'moving'
                moved_main = None
                moved_count = 0
                try:
                    for idx, (src, sz) in enumerate(plan['files']):
                        with self._lock:
                            if self._state['cancel_requested']:
                                cancelled = True
                                break
                            self._state['current_file'] = src.name
                        dest = plan['dest_dir'] / src.name
                        final_path = self._move_one(src, dest, sz)
                        if idx == 0:
                            moved_main = final_path
                        moved_count += 1
                        with self._lock:
                            self._state['files_done'] += 1
                    if cancelled:
                        break
                    with self._lock:
                        self._state['phase'] = 'registering'
                    reg = self._register(str(moved_main), plan['item'].get('name'), plan['item'])
                    results.append({
                        'path': str(moved_main),
                        'folder': str(plan['dest_dir']),
                        'files_moved': moved_count,
                        **reg,
                    })
                except InterruptedError:
                    cancelled = True
                    break
                except (ValueError, OSError, KeyError, TypeError) as error:
                    results.append({'path': plan['item'].get('path', ''), 'error': str(error)[:220]})
        finally:
            with self._lock:
                self._state['results'] = results
                self._state['active'] = False
                self._state['current_file'] = ''
                if cancelled:
                    self._state['phase'] = 'cancelled'
                else:
                    self._state['phase'] = 'done'
                    if self._state['bytes_total'] > 0 and not any(r.get('error') for r in results):
                        self._state['percent'] = 100.0
