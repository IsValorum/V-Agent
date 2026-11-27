"""llama.cpp speculative draft settings. The draft is optional and per model."""
from functools import lru_cache
import os
from pathlib import Path

TYPES = ('auto', 'draft-simple', 'draft-eagle3', 'draft-mtp', 'draft-dflash', 'draft-dspark')
DEFAULT = {'enabled': False, 'path': '', 'type': 'auto', 'max': 3, 'min': 0}


@lru_cache(maxsize=128)
def _has_head_cached(path_str, size, modified):
    try:
        from gguf_catalog import inspect
        return bool(inspect(Path(path_str)).get('head'))
    except (OSError, ValueError, KeyError, EOFError):
        return False


def has_head(path):
    """True when the GGUF at `path` contains built-in MTP / NextN layers."""
    if not path:
        return False
    try:
        resolved = Path(path).resolve()
        stat = resolved.stat()
    except OSError:
        return False
    return _has_head_cached(str(resolved), stat.st_size, stat.st_mtime_ns)


def _same_file(first, second):
    if not first or not second:
        return False
    try:
        return os.path.normcase(str(Path(first).resolve())) == os.path.normcase(str(Path(second).resolve()))
    except OSError:
        return False


def validate(value, previous=None, require_file=False):
    if not isinstance(value, dict) or set(value) - DEFAULT.keys():
        raise ValueError('Ajustes de draft no válidos.')
    result = {**DEFAULT, **(previous or {}), **value}
    if type(result['enabled']) is not bool:
        raise ValueError('Estado de draft no válido.')
    if not isinstance(result['path'], str) or len(result['path']) > 1024:
        raise ValueError('Ruta de draft no válida.')
    if result['path'] and Path(result['path']).suffix.lower() != '.gguf':
        raise ValueError('El draft debe ser un archivo GGUF.')
    if result['type'] not in TYPES:
        raise ValueError('Tipo de draft no admitido.')
    if type(result['max']) is not int or not 1 <= result['max'] <= 32:
        raise ValueError('Tokens de draft fuera de rango (1–32).')
    if type(result['min']) is not int or not 0 <= result['min'] <= result['max']:
        raise ValueError('Mínimo de draft fuera de rango.')
    if result['enabled']:
        if result['path']:
            path = Path(result['path'])
            if not path.is_file():
                raise ValueError('El archivo draft seleccionado no existe.')
        elif result['type'] != 'draft-mtp':
            raise ValueError('El archivo draft seleccionado no existe.')
    return result


def effective(value, model_path=None):
    """Resolve effective draft settings for `model_path`.

    - Absent `value` (or no explicit `enabled` key): auto-enable built-in `draft-mtp`
      when the model's GGUF carries MTP/NextN layers.
    - Explicit `enabled: False`: stays disabled (user choice remembered).
    - `path` pointing at the main model itself: treated as the built-in MTP head
      rather than loading the target weights twice.
    """
    if value is None or (isinstance(value, dict) and 'enabled' not in value):
        if model_path and has_head(model_path):
            merged = {**DEFAULT, **(value or {}), 'enabled': True, 'path': '', 'type': 'draft-mtp'}
            return validate(merged)
        return validate(value or {})
    settings = validate(value)
    if settings['enabled'] and settings['path'] and model_path and _same_file(settings['path'], model_path):
        settings = {**settings, 'path': '', 'type': 'draft-mtp'}
    return settings


def infer_type(path):
    """Read the draft GGUF architecture only; never load its weights."""
    feature = {}
    meta = {}
    try:
        from gguf_catalog import inspect
        feature = inspect(Path(path))
        meta = feature.get('metadata') or {}
        architecture = str(meta.get('general.architecture') or '').lower()
    except (OSError, ValueError, KeyError, EOFError):
        architecture = ''
    if 'dspark' in architecture or any('dspark' in k.lower() for k in meta) or 'dspark' in Path(path).name.lower():
        return 'draft-dspark'
    if 'dflash' in architecture:
        return 'draft-dflash'
    if 'eagle' in architecture:
        return 'draft-eagle3'
    if 'mtp' in architecture or feature.get('head'):
        return 'draft-mtp'
    return 'draft-simple'


def arguments(value, model_path=None):
    settings = effective(value, model_path)
    if not settings['enabled']:
        return []
    if not settings['path']:
        if model_path and not has_head(model_path):
            return []
        args = ['--spec-type', 'draft-mtp', '--spec-draft-n-max', str(settings['max'])]
        if settings['min']:
            args += ['--spec-draft-n-min', str(settings['min'])]
        return args
    path = str(Path(settings['path']).resolve())
    spec = settings['type'] if settings['type'] != 'auto' else infer_type(path)
    args = ['--spec-draft-model', path, '--spec-type', spec, '--spec-draft-n-max', str(settings['max'])]
    if settings['min']:
        args += ['--spec-draft-n-min', str(settings['min'])]
    return args


def rust_arguments(value, model_path=None, help_text='', explicit_mtp=None):
    """Built-in MTP speculative decoding for Strata Rust (--mtp N)."""
    if explicit_mtp is not None or '--mtp' not in (help_text or ''):
        return []
    settings = effective(value, model_path)
    if not settings['enabled'] or settings['path']:
        return []
    if model_path and not has_head(model_path):
        return []
    return ['--mtp', str(min(16, max(1, settings['max'])))]


def weight_bytes(value, model_path=None):
    """Conservative draft weight size for the memory estimate."""
    settings = effective(value, model_path)
    if not settings['enabled'] or not settings['path']:
        return 0
    try:
        from gguf_catalog import inspect
        facts = inspect(Path(settings['path']))
        return int(facts.get('dense_bytes', 0)) + int(facts.get('expert_bytes', 0))
    except (OSError, ValueError, KeyError, EOFError):
        return 0
