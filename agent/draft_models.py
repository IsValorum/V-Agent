"""llama.cpp speculative draft settings. The draft is optional and per model."""
from pathlib import Path

TYPES = ('auto', 'draft-simple', 'draft-eagle3', 'draft-mtp', 'draft-dflash', 'draft-dspark')
DEFAULT = {'enabled': False, 'path': '', 'type': 'auto', 'max': 3, 'min': 0}


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
        path = Path(result['path'])
        if not path.is_file():
            raise ValueError('El archivo draft seleccionado no existe.')
    return result


def infer_type(path):
    """Read the draft GGUF architecture only; never load its weights."""
    feature = {}
    try:
        from gguf_catalog import inspect
        feature = inspect(Path(path))
        architecture = str(feature.get('metadata', {}).get('general.architecture') or '').lower()
    except (OSError, ValueError, KeyError, EOFError):
        architecture = ''
    if 'dflash' in architecture:
        return 'draft-dflash'
    if 'eagle' in architecture:
        return 'draft-eagle3'
    if 'dspark' in architecture:
        return 'draft-dspark'
    if 'mtp' in architecture or feature.get('head'):
        return 'draft-mtp'
    return 'draft-simple'


def arguments(value):
    settings = validate(value, require_file=True)
    if not settings['enabled']:
        return []
    path = str(Path(settings['path']).resolve())
    spec = settings['type'] if settings['type'] != 'auto' else infer_type(path)
    args = ['--spec-draft-model', path, '--spec-type', spec, '--spec-draft-n-max', str(settings['max'])]
    if settings['min']:
        args += ['--spec-draft-n-min', str(settings['min'])]
    return args


def weight_bytes(value):
    """Conservative draft weight size for the memory estimate."""
    settings = validate(value)
    if not settings['enabled'] or not settings['path']:
        return 0
    try:
        from gguf_catalog import inspect
        facts = inspect(Path(settings['path']))
        return int(facts.get('dense_bytes', 0)) + int(facts.get('expert_bytes', 0))
    except (OSError, ValueError, KeyError, EOFError):
        return 0
