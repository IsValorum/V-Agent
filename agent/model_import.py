"""Register local GGUF files without copying weights or loading a GPU model."""
import copy
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import unicodedata

from runtime_paths import CONFIG_ROOT,SOURCE_ROOT,RUNTIME_ROOT,LOG_ROOT,command
ROOT = CONFIG_ROOT
PROFILES = ROOT / 'agent' / 'model-profiles.json'
ASSETS = ROOT / 'agent' / 'model-assets'
IMPORT_LOCK = threading.Lock()
SUPPORTED = {'qwen35moe','clover_moe','glm5-next','glm5next','gemma4','deepseek4','lfm2moe','flint','kolibri1'}
FAMILY_NAMES = {'qwen35moe':'Qwen MoE','clover_moe':'Clover MoE','glm5-next':'GLM','glm5next':'GLM','gemma4':'Gemma 4','deepseek4':'DeepSeek 4','lfm2moe':'LFM2 MoE','flint':'Flint','kolibri1':'Kolibri'}


def _metadata(path):
    sys.path.insert(0, str(SOURCE_ROOT / 'tools'))
    from gguf_reader import GGUFFile
    try:
        gguf = GGUFFile(path)
    except (OSError, ValueError, KeyError, EOFError, OverflowError) as error:
        raise ValueError('No se pudo leer ese GGUF: ' + str(error)) from None
    if not gguf.tensors:
        raise ValueError('El GGUF no contiene los pesos de un modelo.')
    return gguf.metadata


def _existing(path):
    for config_path in ROOT.glob('strata-*.json'):
        try:
            config = json.loads(config_path.read_text(encoding='utf-8-sig'))
            args = config.get('args') or []
            for flag in ('--model','--native'):
                if flag not in args[:-1]:
                    continue
                candidate = Path(config.get('cwd') or ROOT) / args[args.index(flag)+1]
                if candidate.exists() and os.path.samefile(path, candidate):
                    return {'id':config.get('model_name') or config_path.stem.removeprefix('strata-'),
                            'display_name':config.get('display_name') or config.get('model_name') or path.stem,
                            'config':str(config_path),'tokenizer':config.get('tokenizer')}
        except (OSError, ValueError, TypeError):
            continue
    return None


def _path(value, extension):
    if not isinstance(value,str) or not value.strip():
        raise ValueError('Elige un archivo primero.')
    path = Path(os.path.expandvars(os.path.expanduser(value.strip().strip('"')))).resolve()
    if not path.is_file() or path.suffix.lower() not in extension:
        raise ValueError('No se encontró un archivo ' + ' / '.join(extension) + ' en esa ruta.')
    return path


def _template_source(path, metadata, template_path=None):
    sidecar = _path(template_path,('.jinja','.jinja2')) if template_path else path.parent/'chat_template.jinja'
    if sidecar.is_file():
        if sidecar.stat().st_size > 262144:
            raise ValueError('La plantilla es demasiado grande (máximo 256 KB).')
        try:
            return sidecar.read_text(encoding='utf-8-sig'), str(sidecar)
        except UnicodeError:
            raise ValueError('La plantilla debe estar guardada como UTF-8.') from None
    source = metadata.get('tokenizer.chat_template')
    if not isinstance(source,str) or not source.strip():
        raise ValueError('El modelo no trae plantilla. Elige su archivo Jinja en «Plantilla».')
    return source, 'gguf'


def _validate_source(source):
    import jinja2
    from jinja2.sandbox import ImmutableSandboxedEnvironment
    # Match the inference frontend's handling of Transformers generation blocks.
    code = re.sub(r'({%-?\s*)endgeneration(\s*-?%})',r'\1endif\2',source)
    code = re.sub(r'({%-?\s*)generation(\s*-?%})',r'\1if true\2',code)
    env = ImmutableSandboxedEnvironment(extensions=['jinja2.ext.loopcontrols'])
    env.filters['from_json'] = json.loads
    try:
        env.parse(code)
    except jinja2.TemplateError as error:
        raise ValueError('La plantilla Jinja contiene un error: ' + str(error)) from None


def inspect_local_model(value, template_path=None):
    path = _path(value,('.gguf',))
    existing = _existing(path)
    profiles = json.loads(PROFILES.read_text(encoding='utf-8'))
    if existing and existing['id'] in profiles.get('ignored_models',[]):
        raise ValueError('Ese modelo está oculto de tu lista.')
    if existing:
        return {'path':str(path),'name':existing['display_name'],'already_registered':True,
                'model':existing,'family':'Registrado','size_gib':round(path.stat().st_size/2**30,2)}
    metadata = _metadata(path)
    arch = metadata.get('general.architecture')
    count = int(metadata.get('split.count') or 1)
    if count > 1:
        match = re.fullmatch(r'(.+)-(\d{5})-of-(\d{5})\.gguf',path.name,re.I)
        if not match or int(match[2]) != 1:
            raise ValueError('Elige la primera parte del modelo: …-00001-of-….gguf.')
        for index in range(1,count+1):
            if not (path.parent/f'{match[1]}-{index:05d}-of-{count:05d}.gguf').is_file():
                raise ValueError(f'Falta la parte {index} de {count}. Coloca todas las partes en la misma carpeta.')
    source, origin = _template_source(path,metadata,template_path)
    _validate_source(source)
    context = metadata.get(str(arch)+'.context_length')
    return {'path':str(path),'name':str(metadata.get('general.name') or path.stem),
            'architecture':arch,'family':FAMILY_NAMES.get(arch,arch),'size_gib':round(path.stat().st_size/2**30,2),
            'template_source':origin,'template_name':Path(origin).name if origin!='gguf' else 'Incluida en el GGUF',
            'trained_context':int(context) if isinstance(context,(int,float)) and context>0 else None,
            'warnings':([] if arch in SUPPORTED else ['La compatibilidad de esta arquitectura se comprobará al cargar el modelo.']),
            'already_registered':False}


def _atomic_json(path, data):
    with tempfile.NamedTemporaryFile(mode='w',encoding='utf-8',dir=path.parent,prefix='.'+path.name,suffix='.tmp',delete=False) as stream:
        temporary = Path(stream.name)
        json.dump(data,stream,ensure_ascii=False,indent=2)
        stream.write('\n')
    try:
        os.replace(temporary,path)
    finally:
        if temporary.exists():
            temporary.unlink()


def register_local_model(value, name=None, template_path=None):
    if not IMPORT_LOCK.acquire(blocking=False):
        raise ValueError('Ya se está añadiendo otro modelo. Espera a que termine.')
    committed_asset = None
    profiles_before = None
    config_path = None
    try:
        info = inspect_local_model(value,template_path)
        if info.get('already_registered'):
            return {'status':'already_registered','model':info['model']}
        path = Path(info['path'])
        display = str(name or info['name']).strip()[:120]
        if not display:
            raise ValueError('Escribe un nombre para el modelo.')
        ascii_name = unicodedata.normalize('NFKD',display).encode('ascii','ignore').decode().lower()
        base = re.sub('[^a-z0-9]+','-',ascii_name).strip('-')[:56] or 'modelo'
        ASSETS.mkdir(parents=True,exist_ok=True)
        model_id = base
        suffix = 2
        while (ROOT/f'strata-{model_id}.json').exists() or (ASSETS/model_id).exists():
            model_id = f'{base}-{suffix}'; suffix += 1
        config_path = ROOT/f'strata-{model_id}.json'
        source, origin = _template_source(path,_metadata(path),template_path)
        sys.path.insert(0,str(SOURCE_ROOT/'tools'))
        import strata_tokenizer as ST
        from serve.frontend import ChatTemplate
        with tempfile.TemporaryDirectory(dir=ASSETS,prefix='.import-') as scratch:
            scratch = Path(scratch).resolve()
            if not scratch.is_relative_to(ASSETS.resolve()):
                raise RuntimeError('Ruta temporal no válida.')
            try:
                ST.extract(str(path),str(scratch))
            except SystemExit as error:
                raise ValueError('No se pudo preparar el tokenizador: '+str(error)) from None
            token_dir = scratch/'tokenizer'
            (token_dir/'chat_template.jinja').write_text(source,encoding='utf-8')
            tokenizer = ST.Tokenizer.from_dir(token_dir)
            special = tokenizer.special_ids or {}
            kwargs = {key:tokenizer.decode([special[meta]]) for key,meta in [('bos_token','tokenizer.ggml.bos_token_id'),('eos_token','tokenizer.ggml.eos_token_id')] if meta in special}
            try:
                rendered = ChatTemplate(token_dir/'chat_template.jinja').render([{'role':'user','content':'Hola'}],enable_thinking=True,reasoning_effort='xhigh',no_date=True,**kwargs)
                if not rendered or not tokenizer.encode(rendered,parse_special=True):
                    raise ValueError('La plantilla no produjo un mensaje válido.')
            except Exception as error:
                raise ValueError('La plantilla no pudo preparar una conversación: '+str(error)) from None
            (token_dir/'template-source.json').write_text(json.dumps({'source':origin,'sha256':hashlib.sha256(source.encode()).hexdigest()},ensure_ascii=False,indent=2),encoding='utf-8')
            arch = info['architecture']
            kv = 'q8_0' if arch in ('qwen35moe','clover_moe','kolibri1') else 'fp16'
            context = max(2048,min(16384,info.get('trained_context') or 16384))
            profiles = json.loads(PROFILES.read_text(encoding='utf-8'))
            presets = copy.deepcopy(profiles['profiles'])
            for preset in presets.values():
                preset['sampling']['repetition_penalty'] = 1.0
            for key in ('code','agent'):
                presets[key]['sampling']['presence_penalty'] = 0
            from engine_updates import executable
            engine = executable('strata', RUNTIME_ROOT/'strata/strata-poly.exe')
            asset = ASSETS/model_id
            config = {'exe':str(engine),'_val_managed_engine':True,
                      'args':['--model',str(path),'--kv',kv,'--vram-reserve-mib','512','--stage-mib','1024','--prompt-cache','1','--max-context',str(context)],
                      'cwd':str(ROOT),'tokenizer':str(asset/'tokenizer'),'model_name':model_id,'display_name':display,
                      'log':str(LOG_ROOT/f'strata-{model_id}.log'),'lib_dirs':[str(engine.parent/'lib'),str(engine.parent)],
                      'host':'127.0.0.1','port':19382,'gpu':0,'gpus_asked':True,'fit_max_tokens':True,
                      'switch_on_request':True,'reasoning_effort':'high','preserve_thinking':True,'tool_call_recovery':True,
                      'sampling':{key:value for key,value in presets['code']['sampling'].items() if key not in ('max_tokens','seed')}}
            asset.mkdir()
            committed_asset = asset
            os.replace(token_dir,asset/'tokenizer')
            profiles_before = copy.deepcopy(profiles)
            profiles.setdefault('models',{})[model_id] = {'profiles':presets,'architecture':arch,'template':str(asset/'tokenizer/chat_template.jinja'),'text_only':True}
            _atomic_json(PROFILES,profiles)
            _atomic_json(config_path,config)
        return {'status':'added','model':{'id':model_id,'display_name':display,'config':str(config_path)},'context':context}
    except Exception:
        if committed_asset is not None and (config_path is None or not config_path.exists()):
            if profiles_before is not None:
                _atomic_json(PROFILES,profiles_before)
            if committed_asset.resolve().is_relative_to(ASSETS.resolve()):
                shutil.rmtree(committed_asset)
        raise
    finally:
        IMPORT_LOCK.release()


def pick_local_file(kind='model'):
    if kind not in ('model','template','draft','mmproj','encoder','project','engine','plugin'):
        raise ValueError('Tipo de archivo no válido.')
    flags = subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0
    result = subprocess.run(command('pick',kind),capture_output=True,text=True,encoding='utf-8',timeout=300,creationflags=flags)
    if result.returncode:
        raise RuntimeError('No se pudo abrir el selector de archivos. Puedes pegar la ruta del archivo.')
    return json.loads(result.stdout)
