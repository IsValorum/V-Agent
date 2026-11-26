"""Find GGUF models already on this PC (LM Studio, Unsloth Studio, the Hugging Face cache and folders the
user adds), bring them in with how they were tuned, and send V-Agent's settings back to LM Studio and Unsloth.

Every model is shown where its file really is: LM Studio's folder often holds links to other drives, and a
file reached through such a link is labelled by its real folder, not as LM Studio's.

Read side: LM Studio keeps its models in `downloadsFolder` (settings.json) and one JSON per model in
.internal/user-concrete-model-default-config (context, KV cache, sampling, prompt template).
Unsloth Studio keeps folders to scan and per-model sampling in studio.db, which is only ever opened
read-only. Write side: LM Studio's per-model JSON (only for models inside its own folder) and a
preset file for Unsloth Studio. Nothing else in those apps is touched.
"""
import json
import os
import sqlite3
from pathlib import Path

from runtime_paths import DATA_ROOT

HOME = Path(os.path.expanduser('~'))
LMSTUDIO = HOME / '.lmstudio'
UNSLOTH = HOME / '.unsloth' / 'studio'
HF_CACHE = Path(os.environ.get('HF_HUB_CACHE') or os.environ.get('HUGGINGFACE_HUB_CACHE') or HOME / '.cache' / 'huggingface' / 'hub')
KV_FROM = {'f16': 'fp16', 'fp16': 'fp16', 'bf16': 'bf16', 'q8_0': 'q8_0', 'q4_0': 'q4_0'}
KV_TO = {'fp16': 'f16', 'bf16': 'bf16', 'q8_0': 'q8_0', 'q4_0': 'q4_0'}
LIMIT = 2000
FOLDERS_FILE = DATA_ROOT / 'model-folders.json'   # the user's own folders to look in


def _json(path):
    try:
        return json.loads(Path(path).read_text(encoding='utf-8-sig'))
    except (OSError, ValueError):
        return None


def _skip(path):
    name = path.name.lower()
    return (
        name.startswith('mmproj') or '-mmproj' in name or '_mmproj' in name
        or '-mtp-' in name or name.startswith('mtp-') or name.endswith('-mtp.gguf') or name.endswith('_mtp.gguf')
        or 'dspark' in name or 'dflash' in name or 'eagle' in name or 'draft' in name or 'assistant' in name
        or 'imatrix' in name
        or ('-of-' in name and not name.split('-of-')[0].endswith('-00001'))
    )


def _value(field):
    value = field.get('value')
    if isinstance(value, dict) and 'checked' in value:
        return value.get('value') if value.get('checked') else None
    return value


# ---------------------------------------------------------------- LM Studio
def lmstudio_root():
    settings = _json(LMSTUDIO / 'settings.json') or {}
    folder = settings.get('downloadsFolder')
    return Path(folder) if folder else LMSTUDIO / 'models'


def _lm_config_path(root, gguf):
    relative = gguf.relative_to(root)
    return LMSTUDIO / '.internal' / 'user-concrete-model-default-config' / relative.parent / (relative.name + '.json')


def _lm_settings(config):
    out, sampling = {}, {}
    fields = [*(config.get('operation') or {}).get('fields', []), *(config.get('load') or {}).get('fields', [])]
    names = {'llm.prediction.temperature': 'temperature', 'llm.prediction.topPSampling': 'top_p',
             'llm.prediction.topKSampling': 'top_k', 'llm.prediction.minPSampling': 'min_p',
             'llm.prediction.repeatPenalty': 'repetition_penalty', 'llm.prediction.presencePenalty': 'presence_penalty',
             'llm.prediction.frequencyPenalty': 'frequency_penalty', 'llm.prediction.maxPredictedTokens': 'max_tokens'}
    for field in fields:
        key, value = field.get('key'), _value(field)
        if value is None:
            continue
        if key in names and isinstance(value, (int, float)) and not isinstance(value, bool):
            sampling[names[key]] = value
        elif key == 'llm.load.contextLength' and isinstance(value, int):
            out['context'] = value
        elif key == 'llm.load.llama.kCacheQuantizationType' and isinstance(value, str):
            out['kv'] = KV_FROM.get(value.lower())
        elif key == 'llm.prediction.promptTemplate' and isinstance(value, dict):
            template = ((value.get('jinjaPromptTemplate') or {}).get('template') or '') if value.get('type') == 'jinja' else ''
            if template.strip():
                out['template'] = template
        elif key == 'llm.prediction.systemPrompt' and isinstance(value, str) and value.strip():
            out['system_prompt'] = value
    if sampling:
        out['sampling'] = sampling
    return {k: v for k, v in out.items() if v is not None}


def scan_lmstudio():
    root = lmstudio_root()
    if not root.is_dir():
        return []
    found = []
    for gguf in sorted(root.rglob('*.gguf')):
        if len(found) >= LIMIT:
            break
        if _skip(gguf):
            continue
        try:
            size = gguf.stat().st_size
        except OSError:
            continue
        settings = _lm_settings(_json(_lm_config_path(root, gguf)) or {})
        found.append({'source': 'lmstudio', 'path': str(gguf), 'name': gguf.stem, 'size': size,
                      'group': str(gguf.parent.relative_to(root)).replace('\\', '/'), **settings})
    return found


def export_lmstudio(path, settings):
    root, gguf = lmstudio_root(), Path(path)
    try:
        gguf.resolve().relative_to(root.resolve())
    except ValueError:
        raise ValueError('LM Studio solo ve los modelos que están dentro de su carpeta (%s).' % root) from None
    target = _lm_config_path(root, gguf)
    config = _json(target) or {'preset': '', 'operation': {'fields': []}, 'load': {'fields': []}}
    def put(section, key, value):
        fields = config.setdefault(section, {}).setdefault('fields', [])
        fields[:] = [f for f in fields if f.get('key') != key]
        fields.append({'key': key, 'value': value})
    sampling = settings.get('sampling') or {}
    simple = {'temperature': 'llm.prediction.temperature', 'top_k': 'llm.prediction.topKSampling'}
    checked = {'top_p': 'llm.prediction.topPSampling', 'min_p': 'llm.prediction.minPSampling',
               'repetition_penalty': 'llm.prediction.repeatPenalty', 'presence_penalty': 'llm.prediction.presencePenalty',
               'frequency_penalty': 'llm.prediction.frequencyPenalty'}
    for name, key in simple.items():
        if name in sampling:
            put('operation', key, sampling[name])
    for name, key in checked.items():
        if name in sampling:
            put('operation', key, {'checked': True, 'value': sampling[name]})
    if settings.get('context'):
        put('load', 'llm.load.contextLength', int(settings['context']))
    if settings.get('kv') in KV_TO:
        put('load', 'llm.load.llama.kCacheQuantizationType', {'checked': True, 'value': KV_TO[settings['kv']]})
        put('load', 'llm.load.llama.vCacheQuantizationType', {'checked': True, 'value': KV_TO[settings['kv']]})
    if settings.get('template'):
        put('operation', 'llm.prediction.promptTemplate', {'type': 'jinja', 'jinjaPromptTemplate': {'template': settings['template']}, 'stopStrings': []})
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(target.name + '.v-agent.tmp')
    temporary.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding='utf-8')
    os.replace(temporary, target)
    return str(target)


# ---------------------------------------------------------------- Unsloth Studio
def _unsloth_db():
    db = UNSLOTH / 'studio.db'
    if not db.is_file():
        return None
    return sqlite3.connect('file:' + db.as_posix() + '?mode=ro', uri=True, timeout=2)


def _unsloth_sampling(params):
    names = {'temperature': 'temperature', 'topP': 'top_p', 'topK': 'top_k', 'minP': 'min_p',
             'repetitionPenalty': 'repetition_penalty', 'presencePenalty': 'presence_penalty', 'maxTokens': 'max_tokens'}
    sampling = {}
    for source, target in names.items():
        value = params.get(source)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            if target in ('top_k', 'max_tokens'):
                value = max(0, int(value))
            sampling[target] = value
    return sampling


def scan_unsloth():
    if not UNSLOTH.is_dir():
        return []
    folders, by_model, loaded = [], {}, []
    db = None
    try:
        db = _unsloth_db()
        if db:
            with db:
                folders = [(Path(p), bool(r)) for p, r in db.execute('select path, recursive from scan_folders')]
                for key, value in db.execute("select key, value_json from chat_settings where key='inferenceParamsByModel'"):
                    by_model = json.loads(value) or {}
                for key, value in db.execute("select key, value_json from app_settings where key like 'last_local_model_load:%'"):
                    item = json.loads(value) or {}
                    if item.get('kind') == 'gguf' and item.get('id'):
                        loaded.append(Path(item['id']))
    except (sqlite3.Error, ValueError, OSError):
        pass
    finally:
        if db is not None:
            db.close()
    candidates = []
    for folder, recursive in folders:
        if folder.is_dir():
            candidates += list(folder.rglob('*.gguf') if recursive else folder.glob('*.gguf'))
    for folder in [*map(Path, by_model), *loaded]:
        if folder.is_file() and folder.suffix.lower() == '.gguf':
            candidates.append(folder)
        elif folder.is_dir():
            candidates += list(folder.glob('*.gguf'))
    found, seen = [], set()
    for gguf in candidates:
        key = os.path.normcase(str(gguf))
        if key in seen or _skip(gguf) or len(found) >= LIMIT:
            continue
        seen.add(key)
        params = by_model.get(str(gguf.parent)) or by_model.get(str(gguf)) or {}
        if not isinstance(params, dict):
            params = {}
        try:
            size = gguf.stat().st_size
        except OSError:
            continue
        item = {'source': 'unsloth', 'path': str(gguf), 'name': gguf.stem, 'size': size, 'group': gguf.parent.name}
        sampling = _unsloth_sampling(params)
        if sampling:
            item['sampling'] = sampling
        if isinstance(params.get('systemPrompt'), str) and params['systemPrompt'].strip():
            item['system_prompt'] = params['systemPrompt']
        found.append(item)
    return found


def export_unsloth(name, settings):
    folder = UNSLOTH / 'presets'
    if not UNSLOTH.is_dir():
        raise ValueError('No se encontró Unsloth Studio en este equipo.')
    sampling = settings.get('sampling') or {}
    params = {'temperature': sampling.get('temperature', 0.7), 'topP': sampling.get('top_p', 0.95),
              'topK': float(sampling.get('top_k', 20)), 'minP': sampling.get('min_p', 0.0),
              'repetitionPenalty': sampling.get('repetition_penalty', 1.0), 'presencePenalty': sampling.get('presence_penalty', 0.0),
              'maxTokens': sampling.get('max_tokens') or 4096, 'systemPrompt': '', 'systemVariables': '', 'fastMode': False, 'seed': None}
    safe = ''.join(c if c.isalnum() or c in '-_' else '_' for c in name)[:60].strip('_') or 'modelo'
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / ('V-Agent_' + safe + '.json')
    target.write_text(json.dumps({'name': 'V-Agent · ' + name, 'params': params}, ensure_ascii=False, indent=2), encoding='utf-8')
    return str(target)


def _real(path):
    try:
        return Path(path).resolve()
    except OSError:
        return Path(path)


def _inside(path, folder):
    try:
        return path.is_relative_to(_real(folder))
    except (OSError, ValueError):
        return False


# ---------------------------------------------------------------- the user's folders and the HF cache
def folders():
    data = _json(FOLDERS_FILE)
    return [str(Path(p)) for p in data if isinstance(p, str)] if isinstance(data, list) else []


def _save_folders(items):
    FOLDERS_FILE.parent.mkdir(parents=True, exist_ok=True)
    temporary = FOLDERS_FILE.with_name(FOLDERS_FILE.name + '.tmp')
    temporary.write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding='utf-8')
    os.replace(temporary, FOLDERS_FILE)


def add_folder(path):
    folder = Path(str(path or '').strip().strip('"'))
    if not str(folder) or not folder.is_absolute() or not folder.is_dir():
        raise ValueError('Elige una carpeta que exista.')
    items = folders()
    if not any(os.path.normcase(str(_real(p))) == os.path.normcase(str(_real(folder))) for p in items):
        items.append(str(folder))
        _save_folders(items)
    return items


def remove_folder(path):
    items = [p for p in folders() if os.path.normcase(p) != os.path.normcase(str(Path(str(path or ''))))]
    _save_folders(items)
    return items


def _scan_tree(folder, source):
    found = []
    for gguf in sorted(Path(folder).rglob('*.gguf')):
        if len(found) >= LIMIT:
            break
        if _skip(gguf):
            continue
        try:
            size = gguf.stat().st_size
        except OSError:
            continue
        found.append({'source': source, 'path': str(gguf), 'name': gguf.stem, 'size': size, 'group': gguf.parent.name})
    return found


def scan_hf_cache():
    if not HF_CACHE.is_dir():
        return []
    found = []
    for gguf in sorted(HF_CACHE.glob('models--*/snapshots/*/*.gguf')):
        if _skip(gguf) or len(found) >= LIMIT:
            continue
        try:
            size = gguf.stat().st_size
        except OSError:
            continue
        repo = gguf.parents[2].name[len('models--'):].replace('--', '/')
        found.append({'source': 'hf_cache', 'path': str(gguf), 'name': gguf.stem, 'size': size, 'group': repo})
    return found


def scan_folders():
    found = []
    for folder in folders():
        if Path(folder).is_dir():
            found += _scan_tree(folder, 'folder')
    return found


def sources():
    return {'lmstudio': {'available': LMSTUDIO.is_dir(), 'folder': str(lmstudio_root())},
            'unsloth': {'available': UNSLOTH.is_dir(), 'folder': str(UNSLOTH)},
            'hf_cache': {'available': HF_CACHE.is_dir(), 'folder': str(HF_CACHE)},
            'folders': folders()}


def _where(real, origin, lm_root):
    """The source a file is shown under: where it really is, whatever path found it."""
    if origin == 'hf_cache' or _inside(real, HF_CACHE):
        return 'hf_cache'
    if _inside(real, lm_root):
        return 'lmstudio'
    if origin == 'unsloth' and not any(_inside(real, folder) for folder in folders()):
        return 'unsloth'
    return 'folder'


def scan():
    """One row per real file. `seen_in` names the other apps that also list it (a link in LM Studio's
    folder, a folder Unsloth Studio scans); its settings from those apps are merged into the row."""
    items, by_path, errors = [], {}, {}
    lm_root = lmstudio_root()
    for key, function in (('lmstudio', scan_lmstudio), ('unsloth', scan_unsloth), ('hf_cache', scan_hf_cache),
                          ('folder', scan_folders)):
        try:
            found = function()
        except OSError as error:
            errors[key] = str(error)
            continue
        for item in found:
            real = _real(item['path'])
            if real.suffix.lower() != '.gguf':
                # A Hugging Face cache link points at blobs/<hash>, a name with no .gguf and no part numbers:
                # importing that path is refused and a model in parts loses its siblings. The link is kept.
                real = Path(os.path.abspath(item['path']))
            item['path'] = str(real)
            item['folder'] = str(real.parent)
            source = _where(real, item['source'], lm_root)
            origin = item['source']
            item['source'] = source
            same = by_path.get(os.path.normcase(str(real)))
            if same:
                for field in ('sampling', 'system_prompt', 'context', 'kv', 'template'):
                    if field in item and field not in same:
                        same[field] = item[field]
                if origin != same['source'] and origin not in same.setdefault('seen_in', []):
                    same['seen_in'].append(origin)
                continue
            if origin != source:
                item['seen_in'] = [origin]
            by_path[os.path.normcase(str(real))] = item
            items.append(item)
    order = {'folder': 0, 'lmstudio': 1, 'unsloth': 2, 'hf_cache': 3}
    items.sort(key=lambda item: (order.get(item['source'], 9), item['folder'].lower(), item['name'].lower()))
    return {'sources': sources(), 'models': items, 'errors': errors}
