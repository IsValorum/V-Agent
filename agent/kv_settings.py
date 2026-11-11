"""KV cache contracts of the installed Strata engines; no inference or lifecycle."""
from functools import lru_cache
import json
from pathlib import Path
from draft_settings import argument
from model_import import _atomic_json

FORMATS = {
    'fp16': ('FP16', '16 bits; mayor precisión y consumo de memoria.'),
    'q8_0': ('Q8_0', '8 bits para claves y valores; reduce el consumo de memoria.'),
    'int8': ('INT8', 'Claves y valores de 8 bits; implementación propia de esta arquitectura.'),
    'int8k': ('INT8K', 'Claves de 8 bits y valores FP16; consumo intermedio.'),
    'q4_0': ('Q4_0', '4 bits con rotación Hadamard; menor memoria y precisión.'),
    'k8v4': ('K8V4', 'Claves INT8 y valores Q4_0; formato híbrido.'),
}

@lru_cache(maxsize=128)
def _shape(path, size, modified):
    from gguf_catalog import inspect
    meta=inspect(path)['metadata']
    arch=meta.get('general.architecture')
    return arch, [meta.get(str(arch)+'.attention.'+key) for key in ('key_length','key_length_swa')]

def describe(config_path):
    try:
        path=Path(config_path)
        cfg=json.loads(path.read_text(encoding='utf-8-sig'))
        args=cfg.get('args') or []
        current=argument(args,'--kv','fp16')
        weight=Path(argument(args,'--model',''))
        if not weight.is_absolute():weight=Path(cfg.get('cwd') or path.parent)/weight
        stat=weight.stat();arch,heads=_shape(str(weight.resolve()),stat.st_size,stat.st_mtime_ns)
        exe=Path(cfg.get('exe','')).stem.lower()
        if exe=='strata-poly':
            formats=['fp16']
            if arch in ('qwen35moe','clover_moe','kolibri1'):formats+=['q8_0']
            elif arch=='gemma4' and all(type(d) is int and d%32==0 and (d==64 or d>=128) for d in heads):formats+=['int8','int8k']
        elif exe=='strata':formats=['fp16','int8','q4_0','k8v4']
        else:formats=[]
        return {'current':current,'architecture':arch,'options':[{'value':key,'label':FORMATS[key][0],'description':FORMATS[key][1]} for key in formats]}
    except (OSError,ValueError,KeyError,EOFError):
        return {'current':None,'options':[],'error':'No se pudo comprobar la compatibilidad KV.'}

def validate(config_path, value):
    if not isinstance(value,str) or value not in {option['value'] for option in describe(config_path)['options']}:
        raise ValueError('Formato de caché KV no admitido por este modelo y motor.')
    return value

def apply(config_path,value):
    validate(config_path,value)
    path=Path(config_path);cfg=json.loads(path.read_text(encoding='utf-8-sig'))
    if argument(cfg.get('args',[]),'--kv','fp16')==value:return None
    before=list(cfg['args']);args=cfg['args']
    while '--kv' in args:
        i=args.index('--kv');del args[i:i+2]
    args.extend(['--kv',value]);_atomic_json(path,cfg)
    return {'config':str(path),'before':before}
