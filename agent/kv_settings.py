"""KV cache contracts of the installed engines; dynamically discovers formats from --help."""
from functools import lru_cache
import json
from pathlib import Path
import re
from draft_settings import argument
from model_import import _atomic_json

FORMATS = {
    'fp16': ('FP16', '16 bits; mayor precisión y consumo de memoria.'),
    'bf16': ('BF16', '16 bits en coma flotante (BF16).'),
    'f32': ('F32', '32 bits; máxima precisión y mayor consumo de memoria.'),
    'f8_e4m3': ('FP8 (E4M3)', '8 bits en coma flotante; reduce el consumo de memoria.'),
    'fp8': ('FP8', '8 bits en coma flotante; reduce el consumo de VRAM.'),
    'fp4': ('FP4', '4 bits en coma flotante; mínimo consumo de memoria.'),
    'q8_0': ('Q8_0', '8 bits para claves y valores; reduce el consumo de memoria.'),
    'q5_1': ('Q5_1', '5 bits (Q5_1); equilibrio intermedio de memoria y precisión.'),
    'q5_0': ('Q5_0', '5 bits (Q5_0); equilibrio intermedio de memoria y precisión.'),
    'q4_1': ('Q4_1', '4 bits (Q4_1); menor consumo de memoria.'),
    'q4_0': ('Q4_0', '4 bits con rotación Hadamard; menor memoria y precisión.'),
    'iq4_nl': ('IQ4_NL', '4 bits no lineal (IQ4_NL); menor memoria con mejor precisión que Q4_0.'),
    'int8': ('INT8', 'Claves y valores de 8 bits; implementación propia de esta arquitectura.'),
    'int8k': ('INT8K', 'Claves de 8 bits y valores FP16; consumo intermedio.'),
    'k8v4': ('K8V4', 'Claves INT8 y valores Q4_0; formato híbrido.'),
}

_RUST_TO_CANON = {'f16': 'fp16', 'q8': 'q8_0', 'q4': 'q4_0'}
_CANON_TO_RUST = {'fp16': 'f16', 'f16': 'f16', 'q8_0': 'q8', 'q4_0': 'q4'}
_LLAMA_TO_CANON = {'f16': 'fp16'}
_CANON_TO_LLAMA = {'fp16': 'f16'}


def format_meta(key):
    """Return (label, description) for any known or newly discovered KV format."""
    if key in FORMATS:
        return FORMATS[key]
    return key.upper(), 'Formato de caché KV admitido por el motor instalado.'


def discover_engine_kv(kind, exe_path=None):
    """Inspect the installed engine's --help output to discover supported KV formats dynamically."""
    help_txt = ''
    if exe_path and Path(exe_path).is_file():
        try:
            import engine_options
            help_txt = engine_options.help_text(kind, Path(exe_path))
        except Exception:
            help_txt = ''
    if kind == 'llama':
        m = re.search(r'--cache-type-k\b[\s\S]{0,260}?allowed values:\s*([^\n(]+(?:\n\s+[a-z0-9_,\s]+)*)', help_txt, re.I)
        if m:
            raw = re.findall(r'\b[a-z][a-z0-9_]{1,12}\b', m.group(1).lower())
            seen, out = set(), []
            for item in raw:
                if item in ('default', 'allowed', 'values'):
                    continue
                canon = _LLAMA_TO_CANON.get(item, item)
                if canon not in seen:
                    seen.add(canon)
                    out.append(canon)
            if out:
                # Put fp16 first as default if present
                if 'fp16' in out:
                    out.remove('fp16')
                    out.insert(0, 'fp16')
                return out
        return ['fp16', 'bf16', 'q8_0', 'q4_0']
    if kind == 'rust':
        m = re.search(r'--kv\s+<[^>]+>[\s\S]{0,400}?\[possible values:\s*([^\]]+)\]', help_txt, re.I)
        if m:
            raw = re.findall(r'\b[a-z][a-z0-9_]{1,12}\b', m.group(1).lower())
            seen, out = set(), []
            for item in raw:
                canon = _RUST_TO_CANON.get(item, item)
                if canon not in seen:
                    seen.add(canon)
                    out.append(canon)
            if out:
                return out
        return ['fp16', 'q8_0']
    return ['fp16']


def kv_options_for_engine(kind, exe_path=None):
    return [{'value': k, 'label': format_meta(k)[0], 'description': format_meta(k)[1]}
            for k in discover_engine_kv(kind, exe_path)]


def map_kv_for_engine(kind, value, exe_path=None):
    """Map a saved KV preference to a valid CLI flag value for `kind` without failing on cross-engine switches."""
    raw = str(value or 'fp16').strip().lower()
    allowed = discover_engine_kv(kind, exe_path)
    if kind == 'llama':
        canon = _LLAMA_TO_CANON.get(raw, raw)
        if canon not in allowed:
            canon = {'fp8': 'q8_0', 'int8': 'q8_0', 'int8k': 'q8_0', 'k8v4': 'q4_0', 'fp4': 'q4_0'}.get(canon, 'fp16')
        if canon not in allowed:
            canon = 'fp16' if 'fp16' in allowed else allowed[0]
        return _CANON_TO_LLAMA.get(canon, canon)
    if kind == 'rust':
        canon = _RUST_TO_CANON.get(raw, raw)
        if canon not in allowed:
            canon = {'fp8': 'q8_0', 'int8': 'q8_0', 'int8k': 'q8_0', 'q4_0': 'q8_0', 'k8v4': 'q8_0', 'fp4': 'q8_0', 'bf16': 'fp16'}.get(canon, 'fp16')
        if canon not in allowed:
            canon = 'fp16' if 'fp16' in allowed else allowed[0]
        return _CANON_TO_RUST.get(canon, canon)
    return raw


def _discover_strata_poly_kv(help_txt, arch, heads):
    """Parse PolyStrata's --kv help block so newly added KV formats appear automatically."""
    formats = ['fp16']
    has_help = bool(help_txt)
    kv_block = ''
    if has_help:
        m = re.search(r'--kv\s+\S+([\s\S]*?)(?:\n\s+--[a-z]|\Z)', help_txt)
        kv_block = m.group(1) if m else help_txt
    has_q4 = 'q4_0' in kv_block
    has_fp8 = (not has_help) or ('fp8' in kv_block)
    if arch == 'gemma4':
        if any(heads) and all(type(d) is int and d % 32 == 0 and (d == 64 or d >= 128) for d in heads if d is not None):
            formats += ['int8', 'int8k']
    elif arch in ('inkling2_loop', 'inkling2'):
        formats += ['q8_0']
        if has_fp8:
            formats += ['fp8']
        if has_q4:
            formats += ['q4_0']
    elif arch in ('qwen35moe', 'clover_moe', 'kolibri1', 'flint'):
        formats += ['q8_0']
        if has_q4:
            formats += ['q4_0']
    elif has_help:
        # Unknown/future architecture in a newer PolyStrata release: expose general quantized formats if advertised.
        if 'q8_0' in kv_block:
            formats += ['q8_0']
        if has_q4:
            formats += ['q4_0']
    # Also surface any brand-new KV tokens introduced by future PolyStrata builds (e.g. q5_0, iq4_nl, fp4)
    if kv_block:
        for extra in re.findall(r'\b(bf16|q5_0|q5_1|q4_1|iq4_nl|f8_e4m3|fp4|k8v4)\b', kv_block):
            if extra not in formats:
                formats.append(extra)
    return formats


@lru_cache(maxsize=128)
def _shape(path, size, modified):
    from gguf_catalog import inspect
    meta = inspect(path)['metadata']
    arch = meta.get('general.architecture')
    return arch, [meta.get(str(arch) + '.attention.' + key) for key in ('key_length', 'key_length_swa')]


def describe(config_path):
    try:
        path = Path(config_path)
        cfg = json.loads(path.read_text(encoding='utf-8-sig'))
        args = cfg.get('args') or []
        current = argument(args, '--kv', 'fp16')
        weight = Path(argument(args, '--model', ''))
        if not weight.is_absolute():
            weight = Path(cfg.get('cwd') or path.parent) / weight
        stat = weight.stat()
        arch, heads = _shape(str(weight.resolve()), stat.st_size, stat.st_mtime_ns)
        exe_path = Path(cfg.get('exe', ''))
        exe = exe_path.stem.lower()
        if exe == 'strata':
            formats = ['fp16', 'int8', 'q4_0', 'k8v4']
        elif 'strata-poly' in exe or 'polystrata' in exe or cfg.get('_val_managed_engine'):
            help_txt = ''
            if exe_path.is_file():
                try:
                    import engine_options
                    help_txt = engine_options.help_text('strata', exe_path)
                except Exception:
                    help_txt = ''
            formats = _discover_strata_poly_kv(help_txt, arch, heads)
        else:
            formats = []
        return {
            'current': current,
            'architecture': arch,
            'options': [{'value': key, 'label': format_meta(key)[0], 'description': format_meta(key)[1]} for key in formats],
        }
    except (OSError, ValueError, KeyError, EOFError):
        return {'current': None, 'options': [], 'error': 'No se pudo comprobar la compatibilidad KV.'}


def validate(config_path, value):
    if not isinstance(value, str) or value not in {option['value'] for option in describe(config_path)['options']}:
        raise ValueError('Formato de caché KV no admitido por este modelo y motor.')
    return value


def apply(config_path, value):
    validate(config_path, value)
    path = Path(config_path)
    cfg = json.loads(path.read_text(encoding='utf-8-sig'))
    if argument(cfg.get('args', []), '--kv', 'fp16') == value:
        return None
    before = list(cfg['args'])
    args = cfg['args']
    while '--kv' in args:
        i = args.index('--kv')
        del args[i:i + 2]
    args.extend(['--kv', value])
    _atomic_json(path, cfg)
    return {'config': str(path), 'before': before}
