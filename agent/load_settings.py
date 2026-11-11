"""Validated per-model load controls. Probes help only; never starts inference."""
from functools import lru_cache
import re,subprocess
DEFAULT={'auto':True,'parallel':1,'batch':0,'ubatch':0,'checkpoints':1}
LIMITS={'parallel':(0,32),'batch':(0,65536),'ubatch':(0,8192),'checkpoints':(0,64)}
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
        return {'checkpoints':'--ctx-checkpoints' in text,'fit':'--fit ' in text,'batch':default('--batch-size',2048),'ubatch':default('--ubatch-size',512)}
    except (OSError,subprocess.TimeoutExpired):return {'checkpoints':False,'fit':False,'batch':2048,'ubatch':512}
def capabilities(exe):
    stat=exe.stat();return _probe(str(exe),stat.st_size,stat.st_mtime_ns)
def effective(value,caps=None):
    v=validate(value or {});caps=caps or {}
    if v['auto']:v={**DEFAULT}
    v['parallel']=v['parallel'] or 1
    v['batch']=v['batch'] or caps.get('batch',2048)
    v['ubatch']=min(v['ubatch'] or caps.get('ubatch',512),v['batch'])
    return v
def arguments(value,context,caps):
    saved=validate(value or {});v=effective(saved,caps)
    args=['--ctx-size',str(context*v['parallel']),'--parallel',str(v['parallel'])]
    if not saved['auto']:
        if saved['batch']:args+=['--batch-size',str(saved['batch'])]
        if saved['ubatch']:args+=['--ubatch-size',str(saved['ubatch'])]
    if caps.get('checkpoints'):args+=['--ctx-checkpoints',str(v['checkpoints'])]
    elif v['checkpoints']!=1:raise ValueError('Esta compilación no admite Context checkpoints.')
    if saved['auto'] and caps.get('fit'):args+=['--fit','on']
    return args
