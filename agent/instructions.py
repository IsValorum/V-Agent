"""Persistent user and project instructions loaded from AGENTS.md files."""
import os
from pathlib import Path
import tempfile
from runtime_paths import DATA_ROOT

FILENAME = 'AGENTS.md'
MAX_CHARS = 16000


def global_path(data_dir=None):
    return Path(data_dir or DATA_ROOT) / FILENAME


def _read_bounded(path):
    try:
        target = Path(path)
        if not target.is_file():
            return ''
        text = target.read_text(encoding='utf-8-sig', errors='replace').strip()
    except OSError:
        return ''
    if not text:
        return ''
    if len(text) > MAX_CHARS:
        return text[:MAX_CHARS].rstrip() + f'\n\n[Truncated to {MAX_CHARS} characters.]'
    return text


def project_file(project_root):
    if not project_root:
        return None
    try:
        candidate = Path(project_root) / FILENAME
        return candidate if candidate.is_file() else None
    except OSError:
        return None


def prompt_section(project_root=None, data_dir=None):
    """Build the English-headed system instruction block from global and project AGENTS.md."""
    gpath = global_path(data_dir)
    parts = []
    global_text = _read_bounded(gpath)
    if global_text:
        parts.append('Global instructions (AGENTS.md):\n' + global_text)
    pfile = project_file(project_root)
    if pfile is not None:
        try:
            same = os.path.normcase(str(pfile.resolve())) == os.path.normcase(str(gpath.resolve()))
        except OSError:
            same = False
        if not same:
            project_text = _read_bounded(pfile)
            if project_text:
                parts.append('Project instructions (AGENTS.md):\n' + project_text)
    return '\n\n'.join(parts)


def snapshot(project_root=None, data_dir=None):
    gpath = global_path(data_dir)
    try:
        content = gpath.read_text(encoding='utf-8-sig', errors='replace') if gpath.is_file() else ''
    except OSError:
        content = ''
    pfile = project_file(project_root)
    return {
        'content': content,
        'path': str(gpath),
        'max_chars': MAX_CHARS,
        'project_path': str(pfile) if pfile else '',
        'project_active': bool(pfile),
    }


def save_global(content, data_dir=None):
    if not isinstance(content, str):
        raise ValueError('Las instrucciones deben ser texto.')
    text = content.replace('\r\n', '\n')
    if len(text) > MAX_CHARS:
        raise ValueError(f'Las instrucciones admiten hasta {MAX_CHARS} caracteres.')
    gpath = global_path(data_dir)
    if not text.strip():
        try:
            gpath.unlink(missing_ok=True)
        except OSError:
            pass
        return snapshot(data_dir=data_dir)
    gpath.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=gpath.parent, delete=False, newline='\n') as stream:
            temporary = Path(stream.name)
            stream.write(text)
            stream.flush()
        os.replace(temporary, gpath)
        temporary = None
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return snapshot(data_dir=data_dir)
