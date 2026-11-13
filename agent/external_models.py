"""Bring GGUF models (and how they were tuned) in from LM Studio and Unsloth Studio, and send
V-Agent's settings back to them.

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

HOME = Path(os.path.expanduser('~'))
LMSTUDIO = HOME / '.lmstudio'
UNSLOTH = HOME / '.unsloth' / 'studio'
HF_CACHE = Path(os.environ.get('HF_HUB_CACHE') or os.environ.get('HUGGINGFACE_HUB_CACHE') or HOME / '.cache' / 'huggingface' / 'hub')
KV_FROM = {'f16': 'fp16', 'fp16': 'fp16', 'bf16': 'bf16', 'q8_0': 'q8_0', 'q4_0': 'q4_0'}
KV_TO = {'fp16': 'f16', 'bf16': 'bf16', 'q8_0': 'q8_0', 'q4_0': 'q4_0'}
LIMIT = 2000


def _json(path):
    try:
        return json.loads(Path(path).read_text(encoding='utf-8-sig'))
    except (OSError, ValueError):
        return None


def _skip(path):
    name = path.name.lower()
    return name.startswith('mmproj') or '-mtp-' in name or name.startswith('mtp-') or 'imatrix' in name or (
        '-of-' in name and not name.split('-of-')[0].endswith('-00001'))


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
    if HF_CACHE.is_dir():
        candidates += list(HF_CACHE.glob('models--*/snapshots/*/*.gguf'))
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


def sources():
    return {'lmstudio': {'available': LMSTUDIO.is_dir(), 'folder': str(lmstudio_root())},
            'unsloth': {'available': UNSLOTH.is_dir(), 'folder': str(UNSLOTH)}}


def scan():
    items, by_path = [], {}
    errors = {}
    for key, function in (('lmstudio', scan_lmstudio), ('unsloth', scan_unsloth)):
        try:
            found = function()
        except OSError as error:
            errors[key] = str(error)
            continue
        for item in found:
            # Unsloth Studio can point at LM Studio's folder: one row per file, settings merged.
            same = by_path.get(os.path.normcase(item['path']))
            if same:
                for field in ('sampling', 'system_prompt', 'context', 'kv', 'template'):
                    if field in item and field not in same:
                        same[field] = item[field]
                same.setdefault('also', []).append(item['source'])
                continue
            by_path[os.path.normcase(item['path'])] = item
            items.append(item)
    return {'sources': sources(), 'models': items, 'errors': errors}
