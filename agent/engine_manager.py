"""Backend-neutral lifecycle and OpenAI-compatible transport. No production ports."""
import ctypes
import http.client
import json
import os
import re
from pathlib import Path
import ssl
import subprocess
import threading
import time
import urllib.request
import urllib.parse
import uuid
from remote_protocols import (
    model_info,positive_int,claude_payload,ClaudeStream,openai_payload,
    COMPACT_INSTRUCTIONS,compact_transcript,openai_responses_compact_payload,extract_responses_compact_summary,
)
from runtime_paths import DATA_ROOT,RUNTIME_ROOT,LOG_ROOT
from ui_preferences import atomic_json
from engine_updates import executable as updated_executable,active_installations

class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs):raise ValueError('La conexión redirige a otra dirección; configura la dirección final explícitamente.')

def protect(value,decrypt=False):
    class Blob(ctypes.Structure):_fields_=[('size',ctypes.c_uint32),('data',ctypes.POINTER(ctypes.c_byte))]
    buffer=ctypes.create_string_buffer(value);source=Blob(len(value),ctypes.cast(buffer,ctypes.POINTER(ctypes.c_byte)));target=Blob()
    fn=ctypes.windll.crypt32.CryptUnprotectData if decrypt else ctypes.windll.crypt32.CryptProtectData
    if not fn(ctypes.byref(source),None,None,None,None,1,ctypes.byref(target)):raise ctypes.WinError()
    try:return ctypes.string_at(target.data,target.size)
    finally:
        free=ctypes.windll.kernel32.LocalFree;free.argtypes=[ctypes.c_void_p];free.restype=ctypes.c_void_p;free(target.data)


def load_failure(engine, log):
    """A clear reason instead of the engine's last log lines, when the engine says what it was."""
    import re
    match = re.search(r"unsupported architecture '([^']+)' \(supported: ([^)]*)\)", log)
    if match:
        return ('%s no ejecuta modelos de arquitectura «%s» (admite: %s). Usa llama.cpp para este modelo.'
                % (engine, match[1], match[2]))
    match = re.search(r"unknown model architecture: '([^']+)'", log)
    if match:
        return ('Esta compilación de %s no reconoce la arquitectura «%s». Actualiza el motor o usa otro.'
                % (engine, match[1]))
    lower = log.lower()
    if re.search(r'out of memory|failed to allocate|cudamalloc failed|unable to allocate|not enough memory', lower):
        return ('%s se quedó sin memoria al cargar el modelo. Baja el contexto o elige una cuantización más '
                'pequeña.' % engine)
    match = re.search(r'error loading model: (?:error loading model[^:]*: )?(.+)', log)
    if match:
        return ('%s no pudo cargar el GGUF: %s. Puede que el archivo esté incompleto o dañado, o que esta '
                'versión del motor no lo admita.' % (engine, match[1].strip()[:240]))
    # Otherwise only the engine's error lines, not the whole start-up chatter.
    errors = [line.strip() for line in log.splitlines() if re.search(r'\b(E|ERROR|error|Error)\b', line)]
    detail = ' · '.join(dict.fromkeys(errors))[-500:] if errors else log.strip()[-300:]
    return '%s no pudo cargar el GGUF: %s' % (engine, detail)


def measured_timings(usage, sent, first, end):
    """llama-server's `timings` for engines that only report token counts (Strata Rust, APIs)."""
    details = usage.get('prompt_tokens_details') or {}
    cached = details.get('cached_tokens') if isinstance(details, dict) else 0
    cached = cached if isinstance(cached, int) and cached >= 0 else 0
    prompt = usage.get('prompt_tokens') or 0
    completion = usage.get('completion_tokens') or 0
    new = max(0, prompt - cached)
    reading, writing = max(0.0, first - sent), max(0.0, end - first)
    timing = {'prompt_n': new, 'cache_n': cached, 'predicted_n': completion}
    # A handful of new tokens gives a meaningless rate; the interface then says "from cache".
    # A reply delivered in one burst (short answers, providers that buffer) has no measurable speed:
    # dividing by a few milliseconds showed tens of thousands of tokens per second.
    if new >= 8 and reading >= 0.05:
        timing['prompt_per_second'] = round(new / reading, 1)
    if completion > 3 and writing >= 0.1:
        timing['predicted_per_second'] = round((completion - 1) / writing, 1)
    return timing

def stream_finished(line):
    """True for the line that ends a streamed reply: [DONE] or a choice with a finish_reason."""
    if not line.startswith(b'data: '):return False
    if line[6:].strip()==b'[DONE]':return True
    if b'"finish_reason"' not in line:return False
    try:return any(c.get('finish_reason') for c in json.loads(line[6:]).get('choices') or [])
    except (ValueError,AttributeError):return False


PROVIDER_HINTS={401:'la clave de la API no es válida o caducó',403:'la clave no tiene permiso para este modelo',
                404:'la URL o el modelo no existen en este proveedor',408:'el proveedor tardó demasiado',
                413:'la conversación es demasiado larga para este proveedor',
                429:'se alcanzó el límite de uso o de velocidad del proveedor; espera un poco',
                500:'el proveedor tuvo un error interno',502:'el proveedor no está disponible ahora mismo',
                503:'el proveedor no está disponible ahora mismo',504:'el proveedor tardó demasiado'}


def provider_error(status,text,key=''):
    """A provider's error in plain words: its own message (never its HTML), what the code means, key hidden."""
    detail=''
    try:
        data=json.loads(text)
        error=data.get('error',data) if isinstance(data,dict) else data
        detail=error.get('message') or error.get('detail') or '' if isinstance(error,dict) else str(error)
    except ValueError:
        if not text.lstrip().startswith('<'):detail=text.strip()
    detail=' '.join(str(detail).split())[:300]
    if key:detail=detail.replace(key,'[oculta]')
    hint=PROVIDER_HINTS.get(status) or ('el proveedor tuvo un error' if status>=500 else 'el proveedor rechazó la petición')
    return f'Error del proveedor ({status}): {hint}.'+(f' Detalle: {detail}' if detail else '')


class EngineManager:
    def __init__(self):
        self.file=DATA_ROOT/'engines.json'
        # llama-server listens on 127.0.0.1:19383 without any check of its own: a web page that makes its
        # domain resolve to 127.0.0.1 (DNS rebinding) could generate with the GPU or read /slots. A key
        # known only to this process closes it (/health stays open, which is all a probe needs).
        import secrets
        self.llama_key=secrets.token_urlsafe(24)
        # A fresh install starts on llama.cpp with the build this hardware should use (CUDA / Vulkan /
        # CPU); nothing is downloaded until the user accepts it in the first-run guide.
        try:
            self.settings=json.loads(self.file.read_text(encoding='utf-8-sig')) if self.file.exists() else {'active':'llama','llama':{'variant':self.recommended_variant(),'gpu_layers':'auto'},'api':{}}
        except (OSError, ValueError):
            self.settings={'active':'llama','llama':{'variant':self.recommended_variant(),'gpu_layers':'auto'},'api':{}}
        self.kind=self.settings.get('active','strata');self.process=None;self.loaded=None;self.online=False
        self.last_usage={};self.live=False;self.last_timing={};self.lock=threading.RLock();self.remote_models=[]
        self.last_gpu={};self.gpu_at=0;self.gpu_pending=False
        # Preserve the original connection and encrypted key without migrating any secret to JSON.
        if not self.settings.get('connections') and self.settings.get('api',{}).get('base_url'):
            self.settings['api'].setdefault('id','legacy')
            self.settings['connections']={'legacy':dict(self.settings['api'])}
        self.remote_models=list(self.settings.get('api',{}).get('models',[]))
        if self.kind=='api' and self.remote_models and self.settings.get('api',{}).get('base_url'):
            self.online=True
            selected=self.settings.get('api',{}).get('selected_model')
            if selected in {self.remote_identifier(m) for m in self.remote_models}:self.loaded=selected

    def save(self):atomic_json(self.file,self.settings)
    def credential_file(self,identifier=None):
        identifier=identifier or self.settings.get('api',{}).get('id','legacy')
        if not re.fullmatch(r'[a-zA-Z0-9_-]{1,64}',identifier):raise ValueError('Identificador de conexión no válido.')
        return DATA_ROOT/('credentials/api-key.dpapi' if identifier=='legacy' else 'credentials/api-'+identifier+'.dpapi')
    def key(self):
        file=self.credential_file()
        return protect(file.read_bytes(),True).decode() if file.exists() else ''
    def builds(self):
        def read(folder):
            try:
                info=json.loads((RUNTIME_ROOT/folder/'BUILD.json').read_text(encoding='utf8'))
                return {k:info[k] for k in ('version','build','commit','cuda','source') if k in info}
            except (OSError,ValueError):return {}
        result={'strata':read('strata'),'cpu':read('llama-cpu'),'cuda':read('llama-cuda'),'vulkan':read('llama-vulkan'),
                'rust':read('strata-rust'),'custom':self.settings.get('llama',{}).get('custom_build',{})}
        for key,item in active_installations().items():
            if Path(item.get('executable','')).is_file():
                mapped={'llama-cpu':'cpu','llama-cuda':'cuda','llama-vulkan':'vulkan'}.get(key,key);base=result.get(mapped,{})
                result[mapped]={**base,'version':base.get('version','') if key.startswith('llama-') else item['tag'].lstrip('v'),'build':item['tag'],'commit':'','source':item['repository']}
        return result
    def snapshot(self):
        def public(cfg):return {**{key:value for key,value in cfg.items() if key!='api_key'},'has_key':self.credential_file(cfg.get('id','legacy')).exists()}
        remote=public(self.settings.get('api',{}))
        return {'product':'V-Agent','version':__import__('app_updates').VERSION,'active':self.kind,'llama':self.settings.get('llama',{}),'api':remote,
                'data_dir':str(DATA_ROOT),'models':self.remote_models,'loaded_model':self.loaded,'online':self.online,
                'builds':self.builds(),'connections':[public(cfg) for cfg in self.settings.get('connections',{}).values()],
                'engines':[{'id':'strata','name':'Strata'},{'id':'rust','name':'Strata Rust'},{'id':'llama','name':'llama.cpp'},{'id':'api','name':'API compatible'}],'installed_engines':self.installed_engines(),'recommended_variant':self.recommended_variant()}

    def configure(self,body):
        kind=body.get('engine')
        if kind not in ('strata','rust','llama','api'):raise ValueError('Motor desconocido.')
        if kind=='llama':
            variant=body.get('variant','cuda')
            if variant not in ('cuda','vulkan','cpu','custom'):raise ValueError('Compilación desconocida.')
            custom=str(body.get('executable','')).strip()
            if variant=='custom' and (not Path(custom).is_file() or Path(custom).suffix.lower()!='.exe'):raise ValueError('Elige un ejecutable llama-server.exe válido.')
            layers=str(body.get('gpu_layers','auto')).strip()
            if layers not in ('auto','all') and not (layers.isdigit() and 0<=int(layers)<=999):raise ValueError('Capas GPU: auto, all o un número entre 0 y 999.')
            prior=self.settings.get('llama',{})
            if variant!='custom' and not custom:custom=prior.get('executable','')
            info=prior.get('custom_build',{}) if variant!='custom' else {}
            if variant=='custom':
                # Only on explicit configuration, never in stats or token streaming.
                try:
                    result=subprocess.run([custom,'--version'],capture_output=True,timeout=4,
                        creationflags=subprocess.CREATE_NO_WINDOW,cwd=str(Path(custom).parent))
                    text=(result.stdout+result.stderr).decode('utf8',errors='replace')[:4096]
                    match=re.search(r'version:\s*([^\r\n]+)',text,re.I)
                    if match:info={'version':match.group(1).strip()[:160]}
                except (OSError,subprocess.TimeoutExpired):pass
            self.settings['llama']={'variant':variant,'executable':custom,'gpu_layers':layers,'custom_build':info}
        if kind=='api':
            connections=self.settings.get('connections',{})
            identifier=str(body.get('connection_id') or ('legacy' if not connections else self.settings.get('api',{}).get('id') or ''))
            if body.get('new_connection') or not identifier:identifier=uuid.uuid4().hex
            if not re.fullmatch(r'[a-zA-Z0-9_-]{1,64}',identifier):raise ValueError('Identificador de conexión no válido.')
            previous=connections.get(identifier,{})
            protocol=str(body.get('protocol',previous.get('protocol','openai')))
            if protocol not in ('openai','anthropic'):raise ValueError('Elige OpenAI compatible o Claude.')
            url=str(body.get('base_url',previous.get('base_url',''))).strip().rstrip('/');parsed=urllib.parse.urlsplit(url)
            if parsed.scheme not in ('https','http') or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:raise ValueError('Escribe una URL base sin credenciales ni parámetros.')
            if parsed.scheme!='https' and parsed.hostname not in ('127.0.0.1','localhost','::1'):raise ValueError('Las API externas requieren HTTPS; HTTP está permitido para conexiones locales.')
            key=str(body.get('api_key',''));file=self.credential_file(identifier)
            version=str(body.get('api_version',previous.get('api_version','2026-10-21')))
            if not re.fullmatch(r'\d{4}-\d{2}-\d{2}',version):raise ValueError('Versión Claude: usa AAAA-MM-DD.')
            timeout=int(body.get('timeout',previous.get('timeout',180)))
            if not 10<=timeout<=1800:raise ValueError('Tiempo de espera: entre 10 y 1800 segundos.')
            name=str(body.get('name',previous.get('name','Claude' if protocol=='anthropic' else parsed.hostname))).strip()[:100] or parsed.hostname
            extra={k:str(body.get(k,previous.get(k,''))).strip() for k in ('organization','project')}
            if any('\n' in value or '\r' in value for value in [key,*extra.values()]):raise ValueError('Cabecera de conexión no válida.')
            changed=previous.get('base_url')!=url or previous.get('protocol','openai')!=protocol
            if (changed and not key) or body.get('clear_key'):file.unlink(missing_ok=True)
            if key:
                file.parent.mkdir(exist_ok=True);file.write_bytes(protect(key.encode()))
            cfg={**previous,'id':identifier,'name':name,'protocol':protocol,'base_url':url,'vision':bool(body.get('vision',previous.get('vision',False))),
                 'api_version':version,'timeout':timeout,'include_usage':bool(body.get('include_usage',previous.get('include_usage',True))),
                 'send_sampling':bool(body.get('send_sampling',previous.get('send_sampling',False))),**extra}
            if changed:cfg['models']=[];cfg['model_overrides']={};cfg.pop('selected_model',None)
            self.settings.setdefault('connections',{})[identifier]=cfg;self.settings['api']=dict(cfg)
            self.remote_models=list(cfg.get('models',[]))
            self.online=bool(self.remote_models and cfg.get('base_url'))
            selected=cfg.get('selected_model')
            self.loaded=selected if self.online and selected in {self.remote_identifier(m) for m in self.remote_models} else None
        self.settings['active']=kind;self.kind=kind;self.save();return self.snapshot()

    def base(self):
        if self.kind in ('llama','rust'):return 'http://127.0.0.1:19383/v1'
        return self.settings.get('api',{}).get('base_url','').rstrip('/')
    def url(self,path):
        base=self.base()
        if not base:raise ValueError('Configura la dirección de la API.')
        if self.kind=='api' and urllib.parse.urlsplit(base).path in ('','/'):base+='/v1'
        return base+path
    def headers(self):
        key=self.key() if self.kind=='api' else self.llama_key if self.kind in ('llama','rust') else ''
        cfg=self.settings.get('api',{});headers={'Content-Type':'application/json'}
        if self.kind=='api' and cfg.get('protocol')=='anthropic':
            headers['anthropic-version']=cfg.get('api_version','2026-10-21')
            if key:headers['Authorization' if headers['anthropic-version']>='2026-10-21' else 'x-api-key']=('Bearer '+key if headers['anthropic-version']>='2026-10-21' else key)
        else:
            if key:headers['Authorization']='Bearer '+key
            for field,header in [('organization','OpenAI-Organization'),('project','OpenAI-Project')]:
                if self.kind=='api' and cfg.get(field):headers[header]=cfg[field]
        return headers
    def get(self,path,timeout=8):
        request=urllib.request.Request(self.url(path),headers=self.headers())
        try:
            with urllib.request.build_opener(NoRedirect).open(request,timeout=timeout) as response:
                try:return json.load(response)
                except ValueError:raise ValueError('La API no devolvió una respuesta JSON válida.') from None
        except urllib.error.HTTPError as error:
            text=error.read(2048).decode('utf8',errors='replace');key=self.key() if self.kind=='api' else ''
            raise ValueError(provider_error(error.code,text,key)) from None
    def connect(self):
        cfg=self.settings.get('api',{});items=[];cursor=None;seen=set()
        self.online=False;deadline=time.monotonic()+60
        for _ in range(100):
            remaining=deadline-time.monotonic()
            if remaining<=0:raise ValueError('La lista de modelos tardó más de un minuto. Vuelve a conectar.')
            query=('limit=100'+('&after_id='+urllib.parse.quote(cursor,safe='') if cursor else '')) if cfg.get('protocol')=='anthropic' else ('after='+urllib.parse.quote(cursor,safe='') if cursor else '')
            path='/models'+('?' + query if query else '')
            page=self.get(path,timeout=min(cfg.get('timeout',30),30,remaining));items.extend(page.get('data',[]))
            if not page.get('has_more'):break
            cursor=page.get('last_id')
            if not cursor or cursor in seen:raise ValueError('La API devolvió una paginación de modelos no válida.')
            seen.add(cursor)
        else:raise ValueError('La lista de modelos excede el límite de páginas.')
        models={str(item['id']):model_info(item,cfg.get('model_overrides',{})) for item in items if isinstance(item,dict) and item.get('id')}
        self.remote_models=list(models.values());cfg['models']=self.remote_models
        if cfg.get('id'):self.settings.setdefault('connections',{})[cfg['id']]=dict(cfg)
        self.online=True;self.save();return self.snapshot()

    def remote_identifier(self,model):
        cfg=self.settings.get('api',{});prefix='api--' if cfg.get('id','legacy')=='legacy' else 'api--'+cfg['id']+'--'
        return prefix+model['id']

    def selected_remote(self):return next((m for m in self.remote_models if self.remote_identifier(m)==self.loaded),None)

    def remote_context(self,model_id,context):
        model=next((m for m in self.remote_models if self.remote_identifier(m)==model_id),None)
        if not model:raise ValueError('Selecciona un modelo de la conexión actual.')
        value=positive_int(context)
        if context not in (None,'',0) and not value:raise ValueError('El contexto debe ser un número positivo de tokens.')
        cfg=self.settings['api'];overrides=cfg.setdefault('model_overrides',{})
        if value:overrides[model['id']]={'context':value}
        else:overrides.pop(model['id'],None)
        # Refresh metadata on next connection; a manual override is immediately effective.
        model['context']=value or model.get('reported_context');model['context_source']='manual' if value else 'unknown'
        cfg['models']=self.remote_models
        if cfg.get('id'):self.settings.setdefault('connections',{})[cfg['id']]=dict(cfg)
        self.save()
        return model

    def executable(self):
        if self.kind=='rust':return updated_executable('rust',RUNTIME_ROOT/'strata-rust/strata.exe')
        cfg=self.settings.get('llama',{});variant=cfg.get('variant','cuda')
        if variant=='custom':return Path(cfg.get('executable',''))
        key={'cpu':'llama-cpu','vulkan':'llama-vulkan'}.get(variant,'llama-cuda')
        # The chosen build may not be installed (fresh install, or another variant was downloaded):
        # use the first llama.cpp build that exists rather than failing to start.
        for candidate in (key,'llama-cuda','llama-vulkan','llama-cpu'):
            path=updated_executable(candidate,RUNTIME_ROOT/candidate/'llama-server.exe')
            if path.is_file():return path
        return updated_executable(key,RUNTIME_ROOT/key/'llama-server.exe')
    @staticmethod
    def recommended_variant():
        try:
            import hardware_stats,engine_recommendations
            return engine_recommendations.LLAMA_VARIANT[engine_recommendations.best_llama(hardware_stats.profile_snapshot())]
        except Exception:
            return 'cpu'
    def installed_engines(self):
        """Which engines can start right now (bundled or downloaded), for the first-run guide."""
        found={key:updated_executable(key,RUNTIME_ROOT/key/'llama-server.exe').is_file() for key in ('llama-cuda','llama-vulkan','llama-cpu')}
        found['strata']=updated_executable('strata',RUNTIME_ROOT/'strata'/'strata-poly.exe').is_file()
        found['rust']=updated_executable('rust',RUNTIME_ROOT/'strata-rust/strata.exe').is_file()
        return found
    def stop(self):
        process=self.process;self.process=None;self.loaded=None;self.live=False;self.online=False;self.last_usage={}
        if process and process.poll() is None:
            subprocess.run(['taskkill','/F','/T','/PID',str(process.pid)],capture_output=True,creationflags=subprocess.CREATE_NO_WINDOW,timeout=20)
            process.wait(timeout=10)
        return {'status':'unloaded','loaded':False,'loaded_model':None,'engine_online':False}
    def release_remote(self):
        self.loaded=None;self.live=False;self.last_usage={}
        cfg=self.settings.get('api',{})
        if 'selected_model' in cfg:
            cfg.pop('selected_model',None)
            if cfg.get('id'):self.settings.setdefault('connections',{})[cfg['id']]=dict(cfg)
            self.save()
        return {'status':'unloaded','loaded':False,'loaded_model':None,'engine_online':self.online}
    def load(self,model,context,preparation):
        # A provider model is only a selection: choosing another one simply switches to it.
        if self.loaded and self.loaded!=model['id'] and self.kind!='api':raise ValueError('Descarga primero el modelo actual.')
        if self.kind=='api':
            if not self.online:raise ValueError('Conecta la API antes de elegir un modelo.')
            if model['id'] not in {self.remote_identifier(m) for m in self.remote_models}:raise ValueError('Ese modelo no aparece en la API conectada.')
            self.loaded=model['id'];cfg=self.settings.setdefault('api',{});cfg['selected_model']=model['id']
            if cfg.get('id'):self.settings.setdefault('connections',{})[cfg['id']]=dict(cfg)
            self.save();return
        self.stop();exe=self.executable()
        if not exe.is_file():raise ValueError('No se encuentra la compilación de llama.cpp seleccionada.')
        # Never accidentally attach to or stop somebody else's server.
        import socket
        with socket.socket() as probe:
            if probe.connect_ex(('127.0.0.1',19383))==0:raise ValueError('El puerto privado 19383 está ocupado; no se ha tocado ese proceso.')
        cfg=self.settings.get('llama',{});kv=model.get('preferences',{}).get('kv','fp16');kv='f16' if kv=='fp16' else kv
        layers='0' if cfg.get('variant')=='cpu' else cfg.get('gpu_layers','auto')
        argv=[str(exe),'--model',model['path'],'--host','127.0.0.1','--port','19383','--ctx-size',str(context),'--parallel','1',
              '--n-gpu-layers',layers,'--jinja','--no-webui','--alias',model['id'],'--cache-type-k',kv,'--cache-type-v',kv]
        if self.kind=='llama':
            from load_settings import arguments,capabilities,gpu_layers
            load=model.get('preferences',{}).get('load',{})
            i=argv.index('--ctx-size');del argv[i:i+4]
            # Per model: automatic lets --fit place layers ('auto'); manual uses its own -ngl. CPU builds stay at 0.
            if cfg.get('variant')!='cpu':argv[argv.index('--n-gpu-layers')+1]=gpu_layers(load,cfg.get('gpu_layers','auto'))
            argv+=arguments(load,context,capabilities(exe))
            argv+=['--api-key',self.llama_key]
            from draft_models import arguments as draft_arguments
            argv+=draft_arguments(model.get('preferences',{}).get('draft') or {})
        if self.kind=='rust':argv=[str(exe),'serve','--model',model['path'],'--addr','127.0.0.1:19383','--gpu','--ctx',str(context),'--kv',{'fp16':'f16','q8_0':'q8','q4_0':'q4'}.get(kv,kv)]
        saved=model.get('llama_settings',{})
        if self.kind=='llama' and saved.get('mmproj'):argv+=['--mmproj',saved['mmproj']]
        if self.kind=='llama' and saved.get('template'):argv+=['--chat-template-file',saved['template']]
        engine='Strata Rust' if self.kind=='rust' else 'llama.cpp'
        preparation.begin(model['id']);preparation.update(stage='loading',message='Cargando con '+engine+'…')
        env=None
        if self.kind=='rust':
            # Same private key as llama-server; through the environment, so it stays out of the process list.
            env={**os.environ,'STRATA_API_KEY':self.llama_key}
        try:
            from runtime_paths import log_for_append,log_tail
            log_path=log_for_append(LOG_ROOT/'llama-server.log')
            start=log_path.stat().st_size if log_path.exists() else 0
            with log_path.open('a',encoding='utf8') as log:
                self.process=subprocess.Popen(argv,cwd=exe.parent,stdin=subprocess.DEVNULL,stdout=log,stderr=log,env=env,creationflags=subprocess.CREATE_NO_WINDOW)
            deadline=time.monotonic()+600
            while time.monotonic()<deadline:
                preparation.check_cancelled()
                if self.process.poll() is not None:
                    raise ValueError(load_failure(engine,log_tail(log_path)))
                if self._ready(log_path,start):
                    self.loaded=model['id'];self.loaded_context=context;self.online=True;preparation.finish();return
                time.sleep(.3)
            raise TimeoutError(engine+' no terminó de cargar en diez minutos.')
        except Exception:
            self.stop()
            if preparation.cancelled.is_set():preparation.finish_cancelled()
            else:preparation.fail('No se pudo cargar con '+engine+'; revisa el diagnóstico de carga.')
            raise

    def _ready(self,log_path,start):
        """The model is really loaded, not only the server listening.

        Strata Rust answers /v1/models with the model it is still loading (seen: listed, then
        "unsupported architecture" and exit), so its list said "ready" for a model that never ran
        and the next chat hit a closed port (WinError 10061). It writes "loaded <name>" once the
        weights are in; llama-server lists a model only after loading it.
        """
        if self.kind=='rust':
            try:
                with open(log_path,'rb') as stream:
                    stream.seek(start);text=stream.read().decode('utf-8','replace')
            except OSError:return False
            return any(line.startswith('loaded ') for line in text.splitlines())
        try:return bool(self.get('/models',timeout=1).get('data'))
        except (OSError,ValueError):return False

    def stream(self,payload,control):
        allowed={'model','messages','stream','temperature','top_p','max_tokens','seed','tools','tool_choice','presence_penalty','frequency_penalty'}
        if self.kind in ('llama','rust'):allowed|={'min_p','top_k','reasoning_effort','chat_template_kwargs'}
        if self.kind=='api':allowed.add('reasoning_effort')
        body={k:v for k,v in payload.items() if k in allowed}
        if body.get('max_tokens')==0:body.pop('max_tokens')
        if self.kind=='api':body=openai_payload(body,self.base(),self.settings.get('api',{}).get('send_sampling',False))
        if self.kind=='llama':
            body['repeat_penalty']=payload.get('repetition_penalty',1.0)
            body['chat_template_kwargs']=dict(payload.get('chat_template_kwargs') or {})
        cfg=self.settings.get('api',{});claude=self.kind=='api' and cfg.get('protocol')=='anthropic'
        if self.kind=='api' and not cfg.get('vision') and any(isinstance(m,dict) and isinstance(m.get('content'),list) and any(p.get('type')=='image_url' for p in m['content'] if isinstance(p,dict)) for m in payload.get('messages',[])):
            raise ValueError('Activa imágenes en esta conexión API antes de enviarlas al proveedor.')
        if claude:body=claude_payload(body,cfg.get('api_version','2026-10-21'),(self.selected_remote() or {}).get('max_output_tokens'))
        elif self.kind=='rust' or self.kind=='api' and cfg.get('include_usage',True):body['stream_options']={'include_usage':True}
        target=urllib.parse.urlsplit(self.url('/messages' if claude else '/chat/completions'));decoder=ClaudeStream() if claude else None
        timeout=cfg.get('timeout',180) if self.kind=='api' else 1800
        connection=(http.client.HTTPSConnection(target.hostname,target.port or 443,timeout=timeout,context=ssl.create_default_context())
                    if target.scheme=='https' else http.client.HTTPConnection(target.hostname,target.port or 80,timeout=timeout))
        self.live=True;self.last_usage={}
        # Engines without live counters (Strata Rust, APIs) report the prompt only when a round ends:
        # estimate it now from the request, calibrated on the last exact count, so the meter moves
        # while the engine reads the prompt and generates (reasoning and tool rounds included).
        chars=len(json.dumps(body.get('messages') or [],ensure_ascii=False))+len(json.dumps(body.get('tools') or [],ensure_ascii=False))
        self._live_chars=chars;self.live_prompt=self.estimate_prompt(chars);self.live_generated=0;self.live_reading=True
        try:
            if control.cancelled.is_set():return
            try:connection.connect()
            except ConnectionRefusedError:
                if self.kind in ('llama','rust') and (not self.process or self.process.poll() is not None):
                    self.stop()  # the engine closed after loading: the model is not loaded any more
                    raise ValueError('El motor se cerró y el modelo ya no está cargado. Vuelve a cargarlo; '
                                     'si vuelve a pasar, revisa el diagnóstico de carga.') from None
                raise
            control.attach(connection)
            req_path=(target.path or '/')+('?'+target.query if target.query else '')
            connection.request('POST',req_path,json.dumps(body,ensure_ascii=False).encode(),self.headers());response=connection.getresponse()
            if connection.sock is None and response.fp is not None:connection.sock=getattr(getattr(response.fp,'raw',None),'_sock',None)
            if response.status!=200:
                text=response.read(4096).decode('utf8',errors='replace');key=self.key() if self.kind=='api' else ''
                raise ValueError(provider_error(response.status,text,key))
            # Only llama-server reports its own speeds and live counts. For the others they are measured
            # here: each streamed delta is about one token, and reading lasts until the first one arrives.
            sent=time.monotonic();first=None;chunks=0;ended=False
            for line in response:
                if control.cancelled.is_set():return
                if self.kind!='llama' and line.startswith(b'data: {') and b'"delta"' in line:
                    chunks+=1;first=first or time.monotonic();self.live_generated=chunks;self.live_reading=False
                if decoder:
                    if not line.startswith(b'data:'):continue
                    raw_data=line[5:].strip()
                    if not raw_data or raw_data==b'[DONE]':continue
                    try:packet=decoder.packet(json.loads(raw_data))
                    except ValueError as error:
                        key=self.key();raise ValueError(str(error).replace(key,'[oculta]') if key else str(error)) from None
                    self.last_usage=dict(decoder.usage)
                    if packet:
                        ended=ended or stream_finished(packet)
                        yield packet
                    continue
                if line.startswith(b'data: ') and (b'"usage"' in line or b'"timings"' in line):
                    try:
                        packet=json.loads(line[6:]);usage=packet.get('usage');timing=packet.get('timings')
                        if usage:
                            self.last_usage=usage
                            if isinstance(usage.get('prompt_tokens'),int) and usage['prompt_tokens']>0:
                                self._calibration=(self._live_chars,usage['prompt_tokens'],self.loaded)
                        if usage and not timing and self.kind!='llama' and first:
                            timing=measured_timings(usage,sent,first,time.monotonic())
                            packet['timings']=timing;line=('data: '+json.dumps(packet,ensure_ascii=False)+'\n').encode()
                        if timing:
                            self.last_timing=timing
                            if not usage and self.kind=='llama':
                                self.last_usage={'prompt_tokens':timing.get('prompt_n',0)+timing.get('cache_n',0),'completion_tokens':timing.get('predicted_n',0)}
                                packet['usage']=self.last_usage
                                line=('data: '+json.dumps(packet,ensure_ascii=False)+'\n').encode()
                    except ValueError:pass
                ended=ended or stream_finished(line)
                yield line
            if self.kind=='api' and not ended and not control.cancelled.is_set():
                # The provider closed the connection without its end-of-reply mark: what arrived is a
                # fragment, not an answer, and must not be shown as complete.
                raise ValueError('La respuesta del proveedor se cortó antes de terminar (la conexión se cerró a mitad). '
                                 'Vuelve a intentarlo; si se repite, revisa la conexión o el estado del proveedor.')
        finally:self.live=False;self.live_reading=False;control.detach(connection);connection.close()
    def estimate_prompt(self,chars):
        """Prompt tokens of a request, from its size: the last exact count for this model plus the
        new characters at that model's measured characters-per-token (3.5 before any measure)."""
        calibration=getattr(self,'_calibration',None)
        if calibration and calibration[2]==self.loaded and calibration[0]>0 and calibration[1]>0:
            ratio=min(6.0,max(1.5,calibration[0]/calibration[1]))
            if chars>=calibration[0]:return int(calibration[1]+(chars-calibration[0])/ratio)
            return int(chars/ratio)
        return int(chars/3.5)

    def metrics(self):
        limit=(self.selected_remote() or {}).get('context') if self.kind=='api' else getattr(self,'loaded_context',None) if self.kind=='rust' and self.loaded else None
        prompt=self.last_usage.get('prompt_tokens');generated=self.last_usage.get('completion_tokens')
        if self.kind!='llama' and self.live:
            # The previous reply's numbers were reported as "live" and the meter stood still.
            prompt=getattr(self,'live_prompt',prompt);generated=getattr(self,'live_generated',0)
        if self.kind=='llama' and self.loaded:
            try:
                with urllib.request.urlopen(urllib.request.Request('http://127.0.0.1:19383/slots',headers={'Authorization':'Bearer '+self.llama_key}),timeout=1) as response:slots=json.load(response)
                slots=slots.get('slots') if isinstance(slots,dict) else slots
                slot=slots[0] if isinstance(slots,list) and slots else {}
                if not isinstance(slot,dict):slot={}
                limit=slot.get('n_ctx')
                if slot.get('is_processing'):
                    # Newer llama.cpp builds report next_token as a list (one entry per sequence).
                    next_token=slot.get('next_token') or {}
                    if isinstance(next_token,list):next_token=next(iter(next_token),{})
                    if isinstance(next_token,dict):
                        prompt=next_token.get('n_prompt_tokens',prompt);generated=next_token.get('n_decoded',generated)
                    # ...and moved the prompt count up to the slot itself.
                    if isinstance(slot.get('n_prompt_tokens'),int):prompt=slot['n_prompt_tokens']
            except (OSError,ValueError,TypeError,AttributeError,KeyError):pass
        last=[{'prompt_tokens':prompt,'output_tokens':generated}] if prompt is not None and generated is not None else []
        # Live decode speed: llama.cpp only reports timings when a reply ends, so measure the tokens
        # produced since this reply's first sample (an average, steadier than poll-to-poll deltas).
        tok_s=None;now=time.monotonic();mark=getattr(self,'_decode_mark',None)
        if self.live and isinstance(generated,int):
            if mark is None or generated<mark[1]:self._decode_mark=mark=(now,generated)
            elif generated>mark[1] and now-mark[0]>=0.5:tok_s=round((generated-mark[1])/(now-mark[0]),1)
        else:self._decode_mark=None
        state='reading' if self.live and self.kind!='llama' and getattr(self,'live_reading',False) else 'decoding' if self.live else 'idle'
        return {'engine':{'max_context':limit},'live':{'state':state,'prompt_tokens':prompt,'generated':generated,'tok_s':tok_s},'requests':last}

    def _post_json(self,path,payload,extra_headers=None,timeout=120):
        target=urllib.parse.urlsplit(self.url(path))
        headers={**self.headers(),**(extra_headers or {})}
        connection=(http.client.HTTPSConnection(target.hostname,target.port or 443,timeout=timeout,context=ssl.create_default_context())
                    if target.scheme=='https' else http.client.HTTPConnection(target.hostname,target.port or 80,timeout=timeout))
        try:
            req_path=(target.path or '/')+('?'+target.query if target.query else '')
            connection.request('POST',req_path,json.dumps(payload,ensure_ascii=False).encode(),headers)
            response=connection.getresponse()
            raw=response.read(4*1024*1024).decode('utf8',errors='replace')
            return response.status,raw
        finally:
            connection.close()

    def compact_context(self,model_id,messages,instructions=None):
        transcript=compact_transcript(messages)
        if not transcript.strip():
            raise ValueError('No hay historial suficiente para comprimir.')
        cfg=self.settings.get('api',{}) if self.kind=='api' else {}
        protocol=cfg.get('protocol','openai')
        if self.kind=='api':
            remote=self.selected_remote()
            if remote and model_id in (None,'','any','default',self.loaded,remote.get('id')):
                raw_model=remote['id']
            else:
                candidate=str(model_id or '')
                match=next((m for m in self.remote_models if self.remote_identifier(m)==candidate or m.get('id')==candidate),None)
                if match:
                    raw_model=match['id']
                elif candidate.startswith('api--'):
                    parts=candidate.split('--',2)
                    raw_model=parts[2] if len(parts)==3 else parts[1]
                else:
                    raw_model=candidate
        else:
            raw_model=str(model_id or self.loaded or '')
        if not raw_model:
            raise ValueError('Selecciona y carga un modelo antes de comprimir el contexto.')
        timeout=min(int(cfg.get('timeout',180) or 180),180) if self.kind=='api' else 600
        key=self.key() if self.kind=='api' else ''
        prompt=instructions or COMPACT_INSTRUCTIONS

        if self.kind=='api' and protocol=='anthropic':
            req={'model':raw_model,'system':[{'type':'text','text':prompt}],
                 'messages':[{'role':'user','content':'Historial a comprimir:\n\n'+transcript}],
                 'max_tokens':min(positive_int((self.selected_remote() or {}).get('max_output_tokens')) or 4096,4096),
                 'stream':False}
            extra={}
            if len(transcript)>=160000:
                extra['anthropic-beta']='compact-2026-01-12'
                req['context_management']={'edits':[{'type':'compact_20260112'}]}
            status,raw=self._post_json('/messages',req,extra_headers=extra,timeout=timeout)
            if status!=200:
                raise ValueError(provider_error(status,raw[:2048],key))
            try:data=json.loads(raw)
            except ValueError:raise ValueError('La API no devolvió una respuesta JSON válida al comprimir.') from None
            blocks=[str(b.get('text') or b.get('content') or '') for b in (data.get('content') or []) if isinstance(b,dict) and (b.get('text') or b.get('content'))]
            summary='\n\n'.join(blocks).strip()
            if not summary:
                raise ValueError('La API no devolvió un resumen de compactación.')
            raw_usage=data.get('usage') if isinstance(data.get('usage'),dict) else {}
            usage={'prompt_tokens':sum(raw_usage.get(k,0) or 0 for k in ('input_tokens','cache_creation_input_tokens','cache_read_input_tokens')),
                   'completion_tokens':raw_usage.get('output_tokens',0)}
            return {'ok':True,'method':'anthropic_messages','method_label':'API nativa (Anthropic /messages)','summary':summary,'usage':usage}

        if self.kind=='api' and protocol!='anthropic':
            resp_payload=openai_responses_compact_payload(raw_model,messages,prompt)
            try:
                status,raw=self._post_json('/responses/compact',resp_payload,timeout=min(timeout,90))
            except OSError:
                status,raw=404,''
            if status==200:
                try:
                    data=json.loads(raw)
                    summary,comp_item,usage=extract_responses_compact_summary(data)
                    if summary or comp_item:
                        return {'ok':True,'method':'openai_responses_compact','method_label':'API nativa (/responses/compact)',
                                'summary':summary or 'Estado de contexto compactado nativamente por la API.',
                                **({'compacted_item':comp_item} if comp_item else {}),
                                **({'usage':usage} if usage else {})}
                except ValueError:
                    pass
            elif status not in (400,404,405,422,501):
                raise ValueError(provider_error(status,raw[:2048],key))

        chat_body={'model':raw_model,'stream':False,'messages':[{'role':'system','content':prompt},{'role':'user','content':'Historial a comprimir:\n\n'+transcript}]}
        if self.kind in ('llama','rust'):
            chat_body['chat_template_kwargs']={'no_date':True,'enable_thinking':False}
        if self.kind=='api':
            chat_body=openai_payload(chat_body,self.base(),False)
            if 'thinking' in chat_body and 'reasoning_effort' not in chat_body:
                chat_body['thinking']={'type':'disabled'}
        status,raw=self._post_json('/chat/completions',chat_body,timeout=timeout)
        if status!=200:
            raise ValueError(provider_error(status,raw[:2048],key))
        try:data=json.loads(raw)
        except ValueError:raise ValueError('El servidor no devolvió una respuesta JSON válida al comprimir.') from None
        choice=(data.get('choices') or [None])[0] or {}
        summary=str(((choice.get('message') or {}).get('content')) or '').strip()
        if not summary:
            raise ValueError('El modelo no devolvió texto al comprimir el contexto.')
        raw_usage=data.get('usage') if isinstance(data.get('usage'),dict) else None
        usage=None
        if raw_usage and isinstance(raw_usage.get('prompt_tokens'),int):
            usage={'prompt_tokens':raw_usage['prompt_tokens'],'completion_tokens':int(raw_usage.get('completion_tokens') or 0)}
        method='api_chat_completions' if self.kind=='api' else 'local_chat_completions'
        label='API nativa (/chat/completions)' if self.kind=='api' else 'Resumen con modelo local'
        return {'ok':True,'method':method,'method_label':label,'summary':summary,**({'usage':usage} if usage else {})}
