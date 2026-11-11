"""Reasoning controls derived from the template actually selected by the engine."""
import json
from pathlib import Path
import re
from functools import lru_cache

@lru_cache(maxsize=128)
def inspect_template(text):
    from jinja2 import Environment,meta
    try:external=meta.find_undeclared_variables(Environment(extensions=['jinja2.ext.loopcontrols']).parse(text))
    except Exception:external=set()
    levels=[]
    for match in re.finditer(r"reasoning_effort\s*(?:==\s*(['\"])(.*?)\1|in\s*\[([^\]]+)\])",text):
        levels += [match[2]] if match[2] else re.findall(r"['\"]([^'\"]+)['\"]",match[3] or '')
    levels=[x for x in ('minimal','low','medium','high','xhigh') if x in levels and 'reasoning_effort' in external]
    toggle='thinking_option' in external or 'enable_thinking' in external or 'reasoning_effort' in external and bool(re.search(r"reasoning_effort.*?['\"](?:none|off)['\"]",text))
    choices=(['none'] if toggle else [])+levels
    if toggle and not levels:choices+=['think']
    return {'mode':'levels' if levels else 'toggle' if toggle else 'fixed','choices':choices,
            'switch':'thinking_option' if 'thinking_option' in external and 'enable_thinking' not in external else 'enable_thinking',
            'default':('high' if 'high' in choices else 'think' if toggle and not levels else choices[-1] if choices else 'default')}

def capability(model,kind='strata'):
    if kind=='rust':return {'mode':'toggle','choices':['none','think'],'default':'think','source':'Strata Rust · enable_thinking'}
    if kind=='api':return {'mode':'fixed','choices':[],'default':'default','source':'Provider API'}
    try:
        cfg=json.loads(Path(model['config']).read_text(encoding='utf-8-sig'))
        if kind=='strata':
            path=Path(cfg.get('tokenizer',''))/'chat_template.jinja'
            if not path.is_file():
                from runtime_paths import SOURCE_ROOT
                path=SOURCE_ROOT/'serve/chat_template.jinja'
            return {**inspect_template(path.read_text(encoding='utf8')),'source':str(path)}
        template=cfg.get('template') or cfg.get('chat_template')
        if template and Path(template).is_file():
            path=Path(template);return {**inspect_template(path.read_text(encoding='utf8')),'source':str(path)}
        from gguf_reader import GGUFFile
        args=cfg.get('args',[]);path=model.get('path') or args[args.index('--model')+1]
        stat=Path(path).stat();text=_embedded(str(path),stat.st_mtime_ns,stat.st_size)
        return {**inspect_template(text),'source':'GGUF'}
    except (OSError,ValueError,KeyError,IndexError):return {'mode':'fixed','choices':[],'default':'default','source':'Unavailable'}

@lru_cache(maxsize=32)
def _embedded(path,mtime,size):
    from gguf_reader import GGUFFile
    return GGUFFile(Path(path),skip_tokenizer=True).metadata.get('tokenizer.chat_template','')

def normalize(value,info):return value if value in info['choices'] else info['default']

def apply(payload,value,info):
    value=normalize(value,info)
    payload.pop('reasoning_effort',None)
    kwargs=payload.setdefault('chat_template_kwargs',{})
    kwargs.pop('enable_thinking',None);kwargs.pop('reasoning_effort',None)
    if info['mode']=='fixed':return
    if info.get('switch')=='thinking_option':kwargs['thinking_option']='off' if value=='none' else 'on'
    else:kwargs['enable_thinking']=value!='none'
    if info['mode']=='levels':
        payload['reasoning_effort']=value;kwargs['reasoning_effort']=value
