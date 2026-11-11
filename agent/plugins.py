"""User-installed plugin bundles: instruction and command data.

Plugins are local data, never executable host code. Enabled instructions are
added to the agent's system message; commands insert a prepared prompt in the
composer. Portable MCP servers stay in the MCP marketplace.
"""
import hashlib
import json
import re
import threading
import time
from pathlib import Path

from runtime_paths import DATA_ROOT
from ui_preferences import atomic_json

ROOT = DATA_ROOT / 'plugins'
STATE = ROOT / 'installed.json'
LOCK = threading.RLock()
INSTRUCTION_LIMIT = 32 * 1024
PROMPT_LIMIT = 24 * 1024
COMMAND_LIMIT = 20


def _read():
    try:
        value = json.loads(STATE.read_text(encoding='utf8'))
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}


def _identifier(name):
    slug = re.sub(r'[^a-z0-9]+', '-', name.lower()).strip('-')[:40]
    return slug or 'plugin-' + hashlib.sha1(name.encode('utf8')).hexdigest()[:10]


def _file_within(root, value):
    path = (root / str(value)).resolve()
    if path != root and root not in path.parents:
        raise ValueError('El plugin intenta leer un archivo fuera de su carpeta.')
    return path


def _text(path, limit):
    raw = path.read_bytes()
    if len(raw) > limit:
        raise ValueError(f'El archivo {path.name} supera el límite de {limit // 1024} KB.')
    return raw.decode('utf-8-sig', errors='replace').strip()


def _commands(value):
    if value in (None, ''):
        return []
    if not isinstance(value, list) or len(value) > COMMAND_LIMIT:
        raise ValueError(f'commands debe ser una lista de hasta {COMMAND_LIMIT} elementos.')
    result = []
    for item in value:
        if not isinstance(item, dict):
            raise ValueError('Cada comando debe ser un objeto con name y prompt.')
        name = str(item.get('name') or '').strip()
        prompt = str(item.get('prompt') or '').strip()
        if not name or len(name) > 60 or not prompt or len(prompt) > 4000:
            raise ValueError('Cada comando necesita un nombre y un prompt de hasta 4000 caracteres.')
        result.append({'name': name, 'prompt': prompt})
    return result


def _commands_folder(root):
    folder = root / 'commands'
    if not folder.is_dir():
        return []
    result = []
    for path in sorted(folder.glob('*.md'))[:COMMAND_LIMIT]:
        try:
            path = _file_within(root, path.relative_to(root))
            text = _text(path, 8000)
        except (OSError, ValueError):
            continue
        # Claude command files start with a small YAML frontmatter; the body is the prompt.
        if text.startswith('---'):
            parts = text.split('---', 2)
            if len(parts) == 3:
                text = parts[2].strip()
        if not text:
            continue
        name = path.stem.replace('-', ' ').replace('_', ' ').strip()
        result.append({'name': name[:60], 'prompt': text[:4000]})
    return result


def _skills_folder(root):
    folder = root / 'skills'
    if not folder.is_dir():
        return []
    parts = []
    for path in sorted(folder.glob('*/SKILL.md')):
        try:
            path = _file_within(root, path.relative_to(root))
            text = _text(path, 16000)
        except (OSError, ValueError):
            continue
        if text:
            parts.append(f'## {path.parent.name}\n\n{text}')
    return parts


def _validate(data, root=None, source='local'):
    if not isinstance(data, dict):
        raise ValueError('El manifiesto del plugin debe ser un objeto JSON.')
    name = str(data.get('name') or '').strip()
    if not name or len(name) > 80:
        raise ValueError('El plugin necesita un nombre de hasta 80 caracteres.')
    version = str(data.get('version') or '1.0').strip()[:32]
    description = str(data.get('description') or '').strip()[:600]
    instructions = str(data.get('instructions') or '').strip()
    if root and data.get('instructions_file'):
        instructions = _text(_file_within(root, data['instructions_file']), INSTRUCTION_LIMIT)
    if root and not instructions and (root / 'SKILL.md').is_file():
        instructions = _text(_file_within(root, 'SKILL.md'), INSTRUCTION_LIMIT)
    if root:
        skills = _skills_folder(root)
        if skills:
            instructions = (instructions + '\n\n' if instructions else '') + '\n\n'.join(skills)
    if len(instructions) > INSTRUCTION_LIMIT:
        raise ValueError(f'Las instrucciones superan el límite de {INSTRUCTION_LIMIT // 1024} KB.')
    commands = _commands(data.get('commands'))
    if root:
        for command in _commands_folder(root):
            if len(commands) >= COMMAND_LIMIT:
                break
            if not any(item['name'] == command['name'] for item in commands):
                commands.append(command)
    return {
        'id': _identifier(name),
        'name': name,
        'version': version,
        'description': description,
        'enabled': False,
        'instructions': instructions,
        'commands': commands,
        'source': source,
        'installed_at': int(time.time()),
    }


def public():
    with LOCK:
        items = _read()
    return [
        {
            'id': identifier,
            'name': item.get('name', identifier),
            'version': item.get('version', ''),
            'description': item.get('description', ''),
            'enabled': bool(item.get('enabled')),
            'instruction_chars': len(item.get('instructions') or ''),
            'commands': item.get('commands') or [],
            'source': item.get('source', 'local'),
        }
        for identifier, item in sorted(items.items(), key=lambda pair: pair[1].get('name', '').lower())
    ]


def _install(record):
    with LOCK:
        items = _read()
        if record['id'] in items:
            raise ValueError('Ya existe un plugin con ese nombre. Elimínalo antes de reinstalarlo.')
        items[record['id']] = record
        atomic_json(STATE, items)
    return public()


def install_manifest(manifest):
    return _install(_validate(manifest))


def install_path(value):
    path = Path(str(value)).expanduser().resolve()
    if not path.is_dir():
        raise ValueError('La carpeta del plugin no existe.')
    manifest = path / 'plugin.json'
    if manifest.is_file():
        try:
            data = json.loads(_text(manifest, 64 * 1024))
        except ValueError as error:
            raise ValueError('plugin.json no es JSON válido: ' + str(error)) from None
        if not isinstance(data, dict):
            raise ValueError('plugin.json debe contener un objeto JSON.')
        data.setdefault('name', path.name)
    elif (path / 'SKILL.md').is_file():
        data = {'name': path.name}
    else:
        raise ValueError('La carpeta no contiene plugin.json ni SKILL.md.')
    return _install(_validate(data, path, str(path)))


def set_enabled(identifier, enabled):
    if type(enabled) is not bool:
        raise ValueError('Estado de plugin no válido.')
    with LOCK:
        items = _read()
        if identifier not in items:
            raise ValueError('Plugin desconocido.')
        items[identifier]['enabled'] = enabled
        atomic_json(STATE, items)
    return public()


def remove(identifier):
    with LOCK:
        items = _read()
        if identifier not in items:
            raise ValueError('Plugin desconocido.')
        items.pop(identifier)
        atomic_json(STATE, items)
    return public()


def prompt_block():
    """Stable system block for enabled plugins; empty when none are active."""
    with LOCK:
        items = _read()
    enabled = [item for item in items.values() if item.get('enabled') and item.get('instructions')]
    if not enabled:
        return ''
    chunks = []
    budget = PROMPT_LIMIT
    for item in sorted(enabled, key=lambda value: value.get('name', '')):
        title = f"## Plugin: {item.get('name', 'Plugin')}"
        body = str(item.get('instructions') or '').strip()
        if not body:
            continue
        chunk = title + '\n' + body
        if len(chunk) > budget:
            chunk = chunk[:max(0, budget - 20)].rstrip() + '\n[truncado]'
        chunks.append(chunk)
        budget -= len(chunk)
        if budget <= 0:
            break
    if not chunks:
        return ''
    return ('[User-installed plugin instructions. They apply to this conversation; they do not '
            'replace system rules or tool permissions.]\n\n' + '\n\n'.join(chunks))
