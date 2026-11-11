"""Validated per-model load controls. Probes help only; never starts inference.

Two llama.cpp modes:
  * automatic — llama.cpp's own --fit: GPU layers stay 'auto' so it can place layers and size the
    context to the free memory, keeping fit_target MiB free on the GPU (0 = engine default);
  * manual — --fit off and the user decides per layer: gpu_layers (-ngl; -1 = the engine-wide
    setting) and cpu_moe (--n-cpu-moe: layers whose MoE experts stay in RAM).
"""
from functools import lru_cache
import re,subprocess
DEFAULT={'auto':True,'parallel':1,'batch':0,'ubatch':0,'checkpoints':1,'gpu_layers':-1,'cpu_moe':0,'fit_target':0}
LIMITS={'parallel':(0,32),'batch':(0,65536),'ubatch':(0,8192),'checkpoints':(0,64),'gpu_layers':(-1,999),'cpu_moe':(0,999),'fit_target':(0,65536)}
def validate(value,previous=None):
    if not isinstance(value,dict) or set(value)-DEFAULT.keys():raise ValueError('Ajustes de carga no válidos.')
    result={**DEFAULT,**(previous or {}),**value}
    if type(result['auto']) is not bool:raise ValueError('Modo automático no válido.')
    for key,(low,high) in LIMITS.items():
        if type(result[key]) is not int or not low<=result[key]<=high:raise ValueError('Valor de carga fuera de rango: '+key)
    if result['batch'] and result['ubatch']>result['batch']:raise ValueError('Microbatch no puede superar Batch.')
    return result
@lru_cache(maxsize=16)
def _probe(path,size,mtime):
    try:
        r=subprocess.run([path,'--help'],capture_output=True,text=True,encoding='utf-8',errors='replace',timeout=15,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        text=r.stdout+r.stderr
        def default(flag,fallback):
            m=re.search(re.escape(flag)+r'[^\n]*\(default: (\d+)',text)
            return int(m[1]) if m else fallback
        return {'checkpoints':'--ctx-checkpoints' in text,'fit':'--fit ' in text,'fit_target':'--fit-target' in text,
                'cpu_moe':'--n-cpu-moe' in text,'batch':default('--batch-size',2048),'ubatch':default('--ubatch-size',512)}
    except (OSError,subprocess.TimeoutExpired):return {'checkpoints':False,'fit':False,'fit_target':False,'cpu_moe':False,'batch':2048,'ubatch':512}
def capabilities(exe):
    stat=exe.stat();return _probe(str(exe),stat.st_size,stat.st_mtime_ns)
def effective(value,caps=None):
    v=validate(value or {});caps=caps or {}
    if v['auto']:v={**DEFAULT,'fit_target':v['fit_target']}
    v['parallel']=v['parallel'] or 1
    v['batch']=v['batch'] or caps.get('batch',2048)
    v['ubatch']=min(v['ubatch'] or caps.get('ubatch',512),v['batch'])
    return v
def gpu_layers(value,engine_layers):
    """The -ngl value llama.cpp gets: 'auto' in automatic mode so --fit can move layers."""
    saved=validate(value or {})
    if saved['auto']:return 'auto'
    return str(engine_layers) if saved['gpu_layers']<0 else str(saved['gpu_layers'])
def arguments(value,context,caps):
    saved=validate(value or {});v=effective(saved,caps)
    args=['--ctx-size',str(context*v['parallel']),'--parallel',str(v['parallel'])]
    if not saved['auto']:
        if saved['batch']:args+=['--batch-size',str(saved['batch'])]
        if saved['ubatch']:args+=['--ubatch-size',str(saved['ubatch'])]
        if saved['cpu_moe']:
            if not caps.get('cpu_moe'):raise ValueError('Esta compilación de llama.cpp no admite --n-cpu-moe.')
            args+=['--n-cpu-moe',str(saved['cpu_moe'])]
    if caps.get('checkpoints'):args+=['--ctx-checkpoints',str(v['checkpoints'])]
    elif v['checkpoints']!=1:raise ValueError('Esta compilación no admite Context checkpoints.')
    if caps.get('fit'):
        args+=['--fit','on' if saved['auto'] else 'off']
        if saved['auto'] and saved['fit_target'] and caps.get('fit_target'):args+=['--fit-target',str(saved['fit_target'])]
    return args
