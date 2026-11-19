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
    model_info,positive_int,claude_payload,ClaudeStream,openai_payload,normalize_orphan_tool_messages,
    COMPACT_INSTRUCTIONS,compact_transcript,openai_responses_compact_payload,extract_responses_compact_summary,
    DEFAULT_ANTHROPIC_VERSION,PROVIDER_PRESETS,AUTH_MODES,default_user_agent,infer_provider_preset,opencode_inference_url,
    parse_extra_headers,append_api_version_query,build_provider_headers,
    extract_azure_deployment,decode_http_body,iter_http_lines,
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
    """`timings` for a provider (API) that reports only token counts: the provider's own counts, and the
    output speed as received here (its tokens over the time they took to arrive). No reading speed: the
    wait before the first token is network, queue and reading together, not a reading speed."""
    details = usage.get('prompt_tokens_details') or {}
    cached = details.get('cached_tokens') if isinstance(details, dict) else 0
    cached = cached if isinstance(cached, int) and cached >= 0 else 0
    prompt = usage.get('prompt_tokens') or 0
    completion = usage.get('completion_tokens') or 0
    new = max(0, prompt - cached)
    writing = max(0.0, end - first)
    timing = {'prompt_n': new, 'cache_n': cached, 'predicted_n': completion}
    # A reply delivered in one burst (short answers, providers that buffer) has no measurable speed:
    # dividing by a few milliseconds showed tens of thousands of tokens per second.
    if completion > 3 and writing >= 0.1:
        timing['predicted_per_second'] = round((completion - 1) / writing, 1)
    return timing


def strata_rust_timings(entry):
    """llama-server's `timings` from one of Strata Rust's finished requests (GET /api/stats `recent`):
    the engine's own clocks, as its own panel computes them (decode time starts after the first token)."""
    if not isinstance(entry, dict):
        return {}
    number = lambda key: entry.get(key) if isinstance(entry.get(key), (int, float)) and entry.get(key) >= 0 else 0
    prompt, cached, completion = number('prompt_tokens'), number('cached_tokens'), number('completion_tokens')
    prefill_ms, decode_ms = number('prefill_ms'), number('decode_ms')
    new = max(0, prompt - cached)
    timing = {'prompt_n': new, 'cache_n': cached, 'predicted_n': completion, 'prompt_ms': prefill_ms, 'predicted_ms': decode_ms}
    if new > 0 and prefill_ms > 0:
        timing['prompt_per_second'] = round(new / (prefill_ms / 1000), 1)
    if completion > 1 and decode_ms > 0:
        timing['predicted_per_second'] = round((completion - 1) / (decode_ms / 1000), 1)
    return timing

def stream_finished(line):
    """True for the line that ends a streamed reply: [DONE] or a choice with a finish_reason."""
    if not line.startswith(b'data: '):return False
    if line[6:].strip()==b'[DONE]':return True
    if b'"finish_reason"' not in line:return False
    try:return any(c.get('finish_reason') for c in json.loads(line[6:]).get('choices') or [])
    except (ValueError,AttributeError):return False


PROVIDER_HINTS={401:'la clave de la API no es válida o caducó',402:'no queda saldo o crédito en la cuenta del proveedor',
                403:'la clave no tiene permiso para este modelo',
                404:'la URL o el modelo no existen en este proveedor',408:'el proveedor tardó demasiado',
                413:'la conversación es demasiado larga para este proveedor',
                429:'se alcanzó el límite de uso o de velocidad del proveedor; espera un poco',
                500:'el proveedor tuvo un error interno',502:'el proveedor no está disponible ahora mismo',
                503:'el proveedor está saturado o no disponible ahora mismo',504:'el proveedor tardó demasiado',
                529:'el proveedor está saturado ahora mismo'}


class ProviderHTTPError(ValueError):
    """A provider's refusal with its HTTP status and the wait it asked for (Retry-After), so the agent
    can tell a busy provider (wait and retry) from a rejected request (stop), as the OpenAI/Anthropic SDKs,
    OpenCode and Goose do."""
    def __init__(self,message,status,retry_after_ms=None):
        super().__init__(message);self.status=status;self.retry_after_ms=retry_after_ms


def retry_after_ms(headers):
    """Milliseconds from retry-after-ms or retry-after (seconds or an HTTP date); None when absent."""
    try:
        value=headers.get('retry-after-ms')
        if value:return max(0,int(float(value)))
        value=headers.get('retry-after')
        if not value:return None
        if re.fullmatch(r'\s*\d+(?:\.\d+)?\s*',value):return max(0,int(float(value)*1000))
        from email.utils import parsedate_to_datetime
        import datetime
        when=parsedate_to_datetime(value)
        return max(0,int((when-datetime.datetime.now(when.tzinfo)).total_seconds()*1000))
    except (TypeError,ValueError,OverflowError):
        return None


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
                'rust':read('strata-rust'),'custom':self.settings.get('llama',{}).get('custom_build',{}),
                'strata_custom':self.settings.get('strata',{}).get('custom_build',{}),
                'rust_custom':self.settings.get('rust',{}).get('custom_build',{})}
        try:
            import maya_engine
            maya_cfg=self.settings.get('maya',{})
            maya_root=maya_engine.resolve_root(maya_cfg.get('root'))
            maya_ver=maya_engine.installed_version(maya_root)
            maya_bins=maya_engine.find_binaries(maya_root,extra_exe=maya_cfg.get('executable'))
            result['maya']={'version':maya_ver.lstrip('v') if maya_ver else '','build':maya_ver,'root':str(maya_root) if maya_root else '','executable':maya_cfg.get('executable',''),'custom_build':maya_cfg.get('custom_build',{}),'binaries':sorted(maya_bins),'source':maya_engine.MAYA_REPO} if (maya_root or maya_cfg.get('executable')) else {}
        except Exception:
            result['maya']={}
        for key,item in active_installations().items():
            if Path(item.get('executable','')).is_file():
                mapped={'llama-cpu':'cpu','llama-cuda':'cuda','llama-vulkan':'vulkan'}.get(key,key);base=result.get(mapped,{})
                result[mapped]={**base,'version':base.get('version','') if key.startswith('llama-') else item['tag'].lstrip('v'),'build':item['tag'],'commit':'','source':item['repository']}
        return result
    def snapshot(self):
        def public(cfg):return {**{key:value for key,value in cfg.items() if key!='api_key'},'has_key':self.credential_file(cfg.get('id','legacy')).exists()}
        remote=public(self.settings.get('api',{}))
        return {'product':'V-Agent','version':__import__('app_updates').VERSION,'active':self.kind,'strata':self.settings.get('strata',{'variant':'official','executable':'','custom_build':{}}),'rust':self.settings.get('rust',{'variant':'official','executable':'','custom_build':{}}),'llama':self.settings.get('llama',{}),'maya':self.settings.get('maya',{'root':'','backend':'auto'}),'api':remote,
                'data_dir':str(DATA_ROOT),'models':self.remote_models,'loaded_model':self.loaded,'online':self.online,
                'builds':self.builds(),'connections':[public(cfg) for cfg in self.settings.get('connections',{}).values()],
                'engines':[{'id':'strata','name':'Strata'},{'id':'rust','name':'Strata Rust'},{'id':'llama','name':'llama.cpp'},{'id':'maya','name':'Project Maya'},{'id':'api','name':'API compatible'}],'installed_engines':self.installed_engines(),'recommended_variant':self.recommended_variant()}

    def configure(self,body):
        kind=body.get('engine')
        if kind not in ('strata','rust','llama','maya','api'):raise ValueError('Motor desconocido.')
        prior_maya=dict(self.settings.get('maya',{}))
        if kind=='maya':body=self._prepare_maya_body(body,prior_maya)
        if kind=='maya':
            import maya_engine
            backend=str(body.get('maya_backend',self.settings.get('maya',{}).get('backend','auto'))).strip().lower()
            if backend not in ('auto','cuda','hip'):raise ValueError('Backend de Maya no válido (auto, cuda o hip).')
            raw_root=str(body.get('maya_root',self.settings.get('maya',{}).get('root',''))).strip()
            if raw_root:
                candidate=Path(raw_root).expanduser()
                if not candidate.is_dir():raise ValueError('La carpeta de Project Maya no existe.')
                if not maya_engine.is_valid_root(candidate):raise ValueError('La carpeta elegida no contiene Project Maya (maya.py y serve/server.py).')
                raw_root=str(candidate.resolve())
            self.settings['maya']=self._finalize_maya_settings(raw_root,backend,body,prior_maya)
        if kind in ('strata','rust'):
            self._configure_binary_engine(kind,body)
        if kind=='llama':
            variant=body.get('variant','cuda')
            if variant not in ('cuda','vulkan','cpu','custom'):raise ValueError('Compilación desconocida.')
            custom=str(body.get('executable','')).strip().strip('"')
            if variant=='custom':
                custom_path=Path(custom).expanduser()
                if not custom or not custom_path.is_file() or (os.name=='nt' and custom_path.suffix.lower()!='.exe'):
                    raise ValueError('Elige un ejecutable llama-server.exe válido.')
                custom=str(custom_path)
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
            preset=str(body.get('provider_preset',previous.get('provider_preset','auto'))).strip().lower()
            if preset not in PROVIDER_PRESETS:raise ValueError('Proveedor API desconocido.')
            auth_mode=str(body.get('auth_mode',previous.get('auth_mode','auto'))).strip().lower()
            if auth_mode not in AUTH_MODES:raise ValueError('Modo de autenticación API desconocido.')
            url=str(body.get('base_url',previous.get('base_url',''))).strip().rstrip('/');parsed=urllib.parse.urlsplit(url)
            if parsed.scheme not in ('https','http') or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:raise ValueError('Escribe una URL base sin credenciales ni parámetros.')
            if parsed.scheme!='https' and parsed.hostname not in ('127.0.0.1','localhost','::1'):raise ValueError('Las API externas requieren HTTPS; HTTP está permitido para conexiones locales.')
            key=str(body.get('api_key',''));file=self.credential_file(identifier)
            version=str(body.get('api_version',previous.get('api_version',DEFAULT_ANTHROPIC_VERSION)))
            if not re.fullmatch(r'\d{4}-\d{2}-\d{2}',version):raise ValueError('Versión Claude: usa AAAA-MM-DD.')
            timeout=int(body.get('timeout',previous.get('timeout',180)))
            if not 10<=timeout<=1800:raise ValueError('Tiempo de espera: entre 10 y 1800 segundos.')
            name=str(body.get('name',previous.get('name','Claude' if protocol=='anthropic' else parsed.hostname))).strip()[:100] or parsed.hostname
            extra={k:str(body.get(k,previous.get(k,''))).strip() for k in ('organization','project','user_agent','anthropic_beta','http_referer','x_title','azure_api_version')}
            if len(extra['user_agent'])>200:raise ValueError('User-Agent demasiado largo (máximo 200 caracteres).')
            extra_headers=parse_extra_headers(body['extra_headers'] if 'extra_headers' in body else previous.get('extra_headers'))
            raw_session=body['send_session_id'] if 'send_session_id' in body else previous.get('send_session_id',None)
            if raw_session not in (None,True,False,''):raise ValueError('Valor de sesión por conversación no válido.')
            send_session_id=None if raw_session in (None,'') else bool(raw_session)
            if any('\n' in value or '\r' in value for value in [key,*extra.values()]):raise ValueError('Cabecera de conexión no válida.')
            changed=previous.get('base_url')!=url or previous.get('protocol','openai')!=protocol
            if (changed and not key) or body.get('clear_key'):file.unlink(missing_ok=True)
            if key:
                file.parent.mkdir(exist_ok=True);file.write_bytes(protect(key.encode()))
            cfg={**previous,'id':identifier,'name':name,'protocol':protocol,'provider_preset':preset,'auth_mode':auth_mode,'base_url':url,
                 'vision':bool(body.get('vision',previous.get('vision',False))),
                 'api_version':version,'timeout':timeout,'include_usage':bool(body.get('include_usage',previous.get('include_usage',True))),
                 'send_sampling':bool(body.get('send_sampling',previous.get('send_sampling',False))),
                 'send_session_id':send_session_id,'extra_headers':extra_headers,**extra}
            if changed:cfg['models']=[];cfg['model_overrides']={};cfg.pop('selected_model',None)
            self.settings.setdefault('connections',{})[identifier]=cfg;self.settings['api']=dict(cfg)
            self.remote_models=list(cfg.get('models',[]))
            self.online=bool(self.remote_models and cfg.get('base_url'))
            selected=cfg.get('selected_model')
            self.loaded=selected if self.online and selected in {self.remote_identifier(m) for m in self.remote_models} else None
        self.settings['active']=kind;self.kind=kind;self.save();return self.snapshot()

    def base(self):
        if self.kind in ('llama','rust','maya'):return 'http://127.0.0.1:19383/v1'
        return self.settings.get('api',{}).get('base_url','').rstrip('/')
    def url(self,path):
        base=self.base()
        if not base:raise ValueError('Configura la dirección de la API.')
        if self.kind=='api' and urllib.parse.urlsplit(base).path in ('','/'):base+='/v1'
        target=base+path
        if self.kind=='api':
            cfg=self.settings.get('api',{})
            preset=infer_provider_preset(cfg.get('protocol','openai'),cfg.get('base_url',''),cfg.get('provider_preset','auto'))
            target=opencode_inference_url(base,path,preset) or target
            target=append_api_version_query(target,cfg,preset)
        return target
    def session_uuid(self,conversation_id=None):
        """Return a persistent UUID v4 for a given conversation_id (across turns & restarts)."""
        if not conversation_id:return str(uuid.uuid4())
        key=str(conversation_id)
        store_path=DATA_ROOT/'provider-sessions.json'
        with self.lock:
            cache=getattr(self,'_session_uuids',None)
            if cache is None:
                try:
                    loaded=json.loads(store_path.read_text(encoding='utf8'))
                    cache=loaded if isinstance(loaded,dict) else {}
                except (OSError,ValueError):cache={}
                self._session_uuids=cache
            existing=cache.get(key)
            if existing:
                try:
                    if uuid.UUID(str(existing)).version==4:return str(existing)
                except ValueError:pass
            fresh=str(uuid.uuid4())
            cache[key]=fresh
            if len(cache)>500:
                for old_key in list(cache.keys())[:-500]:cache.pop(old_key,None)
            try:atomic_json(store_path,cache)
            except OSError:pass
            return fresh
    def headers(self,stream=False,session_id=None,extra_headers=None):
        import app_updates
        default_ua=default_user_agent(app_updates.VERSION)
        if self.kind=='api':
            return build_provider_headers(self.settings.get('api',{}),self.key(),stream=stream,session_id=session_id,default_ua=default_ua,extra_headers=extra_headers)
        key=self.llama_key if self.kind in ('llama','rust','maya') else ''
        headers={'Content-Type':'application/json','User-Agent':default_ua,'Accept':'text/event-stream' if stream else 'application/json','Accept-Encoding':'identity'}
        if stream:headers['Cache-Control']='no-cache'
        if key:headers['Authorization']='Bearer '+key
        return headers
    def get(self,path,timeout=8):
        request=urllib.request.Request(self.url(path),headers=self.headers(stream=False))
        try:
            with urllib.request.build_opener(NoRedirect).open(request,timeout=timeout) as response:
                try:return json.loads(decode_http_body(response.read(),response.headers.get('Content-Encoding')).decode('utf-8'))
                except (ValueError,UnicodeDecodeError,OSError):raise ValueError('La API no devolvió una respuesta JSON válida.') from None
        except urllib.error.HTTPError as error:
            raw_err=error.read(2048)
            try:raw_err=decode_http_body(raw_err,error.headers.get('Content-Encoding'))
            except OSError:pass
            text=raw_err.decode('utf8',errors='replace');key=self.key() if self.kind=='api' else ''
            raise ValueError(provider_error(error.code,text,key)) from None
    def connect(self):
        cfg=self.settings.get('api',{});items=[];cursor=None;seen=set()
        preset=infer_provider_preset(cfg.get('protocol','openai'),cfg.get('base_url',''),cfg.get('provider_preset'))
        azure_dep=extract_azure_deployment(cfg.get('base_url','')) if preset=='azure' else ''
        self.online=False;deadline=time.monotonic()+60
        for _ in range(100):
            remaining=deadline-time.monotonic()
            if remaining<=0:raise ValueError('La lista de modelos tardó más de un minuto. Vuelve a conectar.')
            query=('limit=100'+('&after_id='+urllib.parse.quote(cursor,safe='') if cursor else '')) if cfg.get('protocol')=='anthropic' else ('after='+urllib.parse.quote(cursor,safe='') if cursor else '')
            path='/models'+('?' + query if query else '')
            try:page=self.get(path,timeout=min(cfg.get('timeout',30),30,remaining));items.extend(page.get('data',[]))
            except ValueError as err:
                if azure_dep and not items and '(404)' in str(err):
                    items=[{'id':azure_dep}];break
                raise
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

    def _probe_custom_executable(self,custom_path):
        info={'version':Path(custom_path).name,'executable':str(custom_path)}
        try:
            probe=subprocess.run([str(custom_path),'--version'],capture_output=True,timeout=5,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
            raw=(probe.stdout+probe.stderr).decode('utf8','replace')
            lines=[line.strip() for line in raw.splitlines() if 'version:' in line.lower() or 'build' in line.lower() or line.strip()]
            if lines:
                line=lines[0]
                info={'version':line.split(':',1)[-1].strip() if 'version:' in line.lower() else line[:120],'executable':str(custom_path)}
        except (OSError,subprocess.TimeoutExpired):
            pass
        return info

    def _configure_binary_engine(self,kind,body):
        label='Strata · PolyStrata (strata-poly.exe)' if kind=='strata' else 'Strata Rust (strata.exe)'
        prior=self.settings.get(kind,{})
        variant=str(body.get('variant',prior.get('variant','official'))).strip().lower()
        if variant not in ('official','custom'):raise ValueError('Compilación desconocida.')
        custom=str(body.get('executable','')).strip().strip('"')
        if variant=='custom':
            custom_path=Path(custom).expanduser()
            if not custom or not custom_path.is_file() or (os.name=='nt' and custom_path.suffix.lower()!='.exe'):
                raise ValueError('Elige un ejecutable válido para '+label+'.')
            custom=str(custom_path)
            info=self._probe_custom_executable(custom_path)
        else:
            if not custom:custom=prior.get('executable','')
            info=prior.get('custom_build',{})
        self.settings[kind]={'variant':variant,'executable':custom,'custom_build':info}

    def _prepare_maya_body(self,body,prior_maya):
        import maya_engine
        updated=dict(body)
        raw_root=str(updated.get('maya_root',prior_maya.get('root',''))).strip().strip('"')
        raw_exe=str(updated.get('maya_executable',updated.get('executable',prior_maya.get('executable','')))).strip().strip('"')
        if raw_root:
            root_path=Path(raw_root).expanduser()
            if root_path.is_file() and (os.name!='nt' or root_path.suffix.lower()=='.exe'):
                if not raw_exe:raw_exe=str(root_path)
                found=maya_engine.resolve_root_from_selection(root_path)
                raw_root=str(found) if found else str(root_path.parent)
            else:
                found=maya_engine.resolve_root_from_selection(root_path)
                if found:raw_root=str(found)
        if not raw_root and raw_exe:
            found=maya_engine.resolve_root_from_selection(raw_exe)
            if found:raw_root=str(found)
        updated['maya_root']=raw_root
        if 'maya_executable' in body or 'executable' in body or raw_exe:
            updated['maya_executable']=raw_exe
        return updated

    def _finalize_maya_settings(self,raw_root,backend,body,prior_maya):
        raw_exe=str(body.get('maya_executable',body.get('executable',prior_maya.get('executable','')))).strip().strip('"')
        if raw_exe:
            exe_path=Path(raw_exe).expanduser()
            if not exe_path.is_file() or (os.name=='nt' and exe_path.suffix.lower()!='.exe'):
                raise ValueError('Elige un ejecutable válido para Project Maya.')
            raw_exe=str(exe_path)
            info=self._probe_custom_executable(exe_path)
        else:
            info={}
        raw_py=str(body.get('maya_python',body.get('python',prior_maya.get('python','')))).strip().strip('"')
        if raw_py:
            py_path=Path(raw_py).expanduser()
            if not py_path.is_file():
                raise ValueError('Elige un intérprete de Python válido para Project Maya.')
            raw_py=str(py_path)
        return {'root':raw_root,'backend':backend,'executable':raw_exe,'python':raw_py,'custom_build':info}

    def executable(self):
        if self.kind=='strata':
            cfg=self.settings.get('strata',{})
            if cfg.get('variant')=='custom' and cfg.get('executable'):return Path(cfg['executable'])
            return updated_executable('strata',RUNTIME_ROOT/'strata/strata-poly.exe')
        if self.kind=='rust':
            cfg=self.settings.get('rust',{})
            if cfg.get('variant')=='custom' and cfg.get('executable'):return Path(cfg['executable'])
            return updated_executable('rust',RUNTIME_ROOT/'strata-rust/strata.exe')
        if self.kind=='maya':
            cfg=self.settings.get('maya',{})
            if cfg.get('executable'):return Path(cfg['executable'])
            try:
                import maya_engine
                root=maya_engine.resolve_root(cfg.get('root'))
                bins=maya_engine.find_binaries(root)
                first=next((bins[k] for k in ('maya','maya-ds4','maya-mm3') if k in bins),None)
                if first:return Path(first)
            except Exception:
                pass
            return Path()
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
        """Which engines can start right now (bundled or downloaded or custom-selected), for the first-run guide."""
        found={key:updated_executable(key,RUNTIME_ROOT/key/'llama-server.exe').is_file() for key in ('llama-cuda','llama-vulkan','llama-cpu')}
        found['llama-custom']=Path(self.settings.get('llama',{}).get('executable') or '').is_file()
        found['strata']=updated_executable('strata',RUNTIME_ROOT/'strata'/'strata-poly.exe').is_file() or Path(self.settings.get('strata',{}).get('executable') or '').is_file()
        found['rust']=updated_executable('rust',RUNTIME_ROOT/'strata-rust/strata.exe').is_file() or Path(self.settings.get('rust',{}).get('executable') or '').is_file()
        try:
            import maya_engine
            maya_cfg=self.settings.get('maya',{})
            maya_root=maya_engine.resolve_root(maya_cfg.get('root'))
            maya_bins=maya_engine.find_binaries(maya_root,extra_exe=maya_cfg.get('executable'))
            found['maya']=bool(maya_root and any(k in maya_bins for k in ('maya','maya-ds4','maya-mm3','custom')))
        except Exception:
            found['maya']=False
        return found
    def stop(self):
        process=self.process;self.process=None;self.loaded=None;self.live=False;self.online=False;self.last_usage={}
        if process and getattr(process, 'stdin', None) and not process.stdin.closed:
            process.stdin.close()
        if process and process.poll() is None:
            subprocess.run(['taskkill','/F','/T','/PID',str(process.pid)],capture_output=True,creationflags=subprocess.CREATE_NO_WINDOW,timeout=20)
            process.wait(timeout=10)
        config = getattr(self, '_maya_run_config', None)
        if config:
            config.unlink(missing_ok=True)
            self._maya_run_config = None
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
        self.stop()
        if self.kind=='maya':
            import socket, maya_engine
            with socket.socket() as probe:
                if probe.connect_ex(('127.0.0.1',19383))==0:raise ValueError('El puerto privado 19383 está ocupado; no se ha tocado ese proceso.')
            maya_cfg=self.settings.get('maya',{})
            maya_root=maya_engine.resolve_root(maya_cfg.get('root'))
            if not maya_root:raise ValueError('No se encuentra instalado Project Maya. Configura su carpeta y requisitos en Ajustes → Motor.')
            py_exe=maya_engine.find_python(maya_root,extra_python=maya_cfg.get('python'))
            cfg_path=Path(model.get('config') or '')
            if not cfg_path.is_file():raise ValueError('No se encontró el archivo de configuración maya-*.json seleccionado.')
            if maya_engine.build_status()['building']:
                raise ValueError('Espera a que termine la configuración de Project Maya.')
            if (maya_root / '.v-agent-maya-needs-setup').is_file():
                raise ValueError('Project Maya se actualizó. Pulsa Preparar modelo con Maya para reconstruir el binario.')
            if not py_exe:
                raise ValueError('Instala Python o ejecuta la configuración oficial de Project Maya.')
            config = maya_engine._read_json(cfg_path, {})
            if not isinstance(config, dict) or not config.get('exe') or not isinstance(config.get('args'), list):
                raise ValueError('Configuración de Project Maya incompleta.')
            family = maya_engine.config_family(config, cfg_path)
            target_name = {'deepseek': 'maya-ds4', 'minimax': 'maya-mm3'}.get(family, 'maya')
            configured_exe = Path(config['exe'])
            if not configured_exe.is_absolute():
                configured_exe = maya_root / configured_exe
            extra_exe = maya_cfg.get('executable')
            if extra_exe and Path(extra_exe).stem.lower() in (target_name, configured_exe.stem.lower()):
                configured_exe = Path(extra_exe)
            if not configured_exe.is_file():
                candidates = maya_engine.find_binaries(maya_root)
                configured_exe = Path(candidates.get(target_name) or configured_exe)
            if not configured_exe.is_file():
                raise ValueError(f'Falta el ejecutable {target_name}. Prepara este modelo con Project Maya.')
            config['exe'] = str(configured_exe.resolve())
            config.setdefault('model_name', model.get('display_name') or cfg_path.stem)
            config.pop('api_key', None)
            if not isinstance(config.get('tokenizer'), str) or not config['tokenizer']:
                raise ValueError('Falta el tokenizador en la configuración de Project Maya.')
            tokenizer = maya_root / config['tokenizer']
            if not (tokenizer / 'vocab.json').is_file():
                raise ValueError('Falta vocab.json. Prepara el tokenizador con la configuración oficial de Maya.')
            config['tokenizer'] = str(tokenizer.resolve())
            if context:
                context = int(context)
                if not 2048 <= context <= 1048576:
                    raise ValueError('Contexto de Maya fuera de rango (2048–1048576).')
                config['args'] = maya_engine._set_flag(config['args'], '--max-context', context)
                config['context'] = context
            # Maya resolves model and cache paths against its checkout. Keep the user's config intact.
            import tempfile
            cache = DATA_ROOT / 'cache' / 'maya'
            cache.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(mode='w', encoding='utf8', prefix='run-', suffix='.json', dir=cache, delete=False) as stream:
                self._maya_run_config = Path(stream.name)
                json.dump(config, stream, ensure_ascii=False)
            argv=[py_exe,'-m','serve.server','--engine','maya','--config',str(self._maya_run_config),'--host','127.0.0.1','--port','19383','--parent-pipe']
            preparation.begin(model['id'])
            preparation.update(stage='loading',message='Cargando con Project Maya…')
            env={**os.environ,'PATH':str(configured_exe.parent)+os.pathsep+os.environ.get('PATH',''),
                 'MAYA_API_KEY':self.llama_key,'PYTHONUNBUFFERED':'1'}
            try:
                from runtime_paths import log_for_append,log_tail
                log_path=log_for_append(LOG_ROOT/'maya-server.log')
                with log_path.open('a',encoding='utf8') as log:
                    self.process=subprocess.Popen(argv,cwd=str(maya_root),stdin=subprocess.PIPE,stdout=log,stderr=log,env=env,creationflags=subprocess.CREATE_NO_WINDOW)
                deadline=time.monotonic()+1800
                while time.monotonic()<deadline:
                    preparation.check_cancelled()
                    if self.process.poll() is not None:
                        raise ValueError(load_failure('Project Maya',log_tail(log_path)))
                    status = self.maya_health()
                    if status.get('status') == 'ok' and status.get('model') == config.get('model_name') and not status.get('unloaded'):
                        self.loaded=model['id'];self.loaded_context=status.get('max_context') or context;self.online=True;preparation.finish();return
                    time.sleep(.3)
                raise TimeoutError('Project Maya no terminó de cargar en treinta minutos.')
            except Exception:
                self.stop()
                if preparation.cancelled.is_set():preparation.finish_cancelled()
                else:preparation.fail('No se pudo cargar con Project Maya; revisa el diagnóstico de carga.')
                raise
        exe=self.executable()
        engine='Strata Rust' if self.kind=='rust' else 'llama.cpp'
        if not exe.is_file():raise ValueError('No se encuentra instalado '+engine+'. Instálalo desde Ajustes → General → Motor o usa una API externa.')
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
            import engine_options
            options=model.get('preferences',{}).get('engine') or {}
            problem=engine_options.conflicts('llama',options,kv)
            if problem:raise ValueError(problem)
            argv+=engine_options.arguments('llama',options,engine_options.help_text('llama',exe))
        if self.kind=='rust':
            argv=[str(exe),'serve','--model',model['path'],'--addr','127.0.0.1:19383','--gpu','--ctx',str(context),'--kv',{'fp16':'f16','q8_0':'q8','q4_0':'q4'}.get(kv,kv)]
            import engine_options
            argv+=engine_options.arguments('rust',model.get('preferences',{}).get('engine') or {},engine_options.help_text('rust',exe))
        saved=model.get('llama_settings',{})
        if self.kind=='llama' and saved.get('mmproj'):argv+=['--mmproj',saved['mmproj']]
        if self.kind=='llama' and saved.get('template'):argv+=['--chat-template-file',saved['template']]
        engine='Strata Rust' if self.kind=='rust' else 'llama.cpp'
        preparation.begin(model['id']);preparation.update(stage='loading',message='Cargando con '+engine+'…')
        path_dirs=[str(exe.parent)]+([str(exe.parent/'lib')] if (exe.parent/'lib').is_dir() else [])
        env={**os.environ,'PATH':os.pathsep.join(path_dirs+[os.environ.get('PATH','')])}
        if self.kind=='rust':
            # Same private key as llama-server; through the environment, so it stays out of the process list.
            env={**env,'STRATA_API_KEY':self.llama_key}
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

    def maya_health(self):
        if self.kind!='maya':return {}
        try:
            with urllib.request.urlopen(urllib.request.Request('http://127.0.0.1:19383/health',headers={'Authorization':'Bearer '+self.llama_key,'Accept':'application/json'}),timeout=1.5) as response:
                data=json.load(response)
                return data if isinstance(data,dict) else {}
        except (OSError,ValueError,urllib.error.URLError):
            return {}

    def _ready(self,log_path,start):
        """The model is really loaded, not only the server listening.

        Strata Rust answers /v1/models with the model it is still loading (seen: listed, then
        "unsupported architecture" and exit), so its list said "ready" for a model that never ran
        and the next chat hit a closed port (WinError 10061). It writes "loaded <name>" once the
        weights are in; llama-server lists a model only after loading it.
        """
        if self.kind=='maya':
            return self.maya_health().get('status')=='ok'
        if self.kind=='rust':
            try:
                with open(log_path,'rb') as stream:
                    stream.seek(start);text=stream.read().decode('utf-8','replace')
            except OSError:return False
            return any(line.startswith('loaded ') for line in text.splitlines())
        try:return bool(self.get('/models',timeout=1).get('data'))
        except (OSError,ValueError):return False

    def stream(self,payload,control,conversation_id=None):
        allowed={'model','messages','stream','temperature','top_p','max_tokens','seed','tools','tool_choice','presence_penalty','frequency_penalty'}
        if self.kind in ('llama','rust','maya'):allowed|={'min_p','top_k','reasoning_effort','chat_template_kwargs'}
        if self.kind=='api':allowed.add('reasoning_effort')
        conv_id=conversation_id if conversation_id is not None else payload.get('conversation_id')
        body={k:v for k,v in payload.items() if k in allowed}
        if body.get('max_tokens')==0:body.pop('max_tokens')
        auto_max=False
        remote=(self.selected_remote() or {}) if self.kind=='api' else {}
        if (self.kind=='api' and self.settings.get('api',{}).get('protocol')!='anthropic' and not positive_int(body.get('max_tokens'))
                and remote.get('id') not in getattr(self,'_no_auto_max',set())):
            # "No limit" must not mean the provider's default (often 4-8K tokens): reasoning used it all and
            # the reply ended empty. Send the model's own output maximum (a generous one when the provider
            # does not say); how much the model thinks is set by the thinking effort, not by this number.
            # As OpenCode does (packages/core/src/session/model-request.ts, outputLimit): the catalog's output
            # limit, 32,000 when the provider does not say, never more than 256,000 ("no reply needs more"),
            # fitted to the room the prompt leaves in the window with 15 % estimate error and 1 % headroom,
            # and never under 1,024.
            ceiling=min(positive_int(remote.get('max_output_tokens')) or 32000,256000)
            window=positive_int(remote.get('reported_context')) or positive_int(remote.get('context'))
            if window:
                # Providers refuse prompt + max_tokens above their window: leave room for this prompt.
                prompt=self.estimate_prompt(len(json.dumps(body.get('messages') or [],ensure_ascii=False))+len(json.dumps(body.get('tools') or [],ensure_ascii=False)))
                ceiling=min(ceiling,max(1024,int(window*0.99)-int(prompt*1.15)))
            body['max_tokens']=ceiling;auto_max=True
        if self.kind=='api':body=openai_payload(body,self.base(),self.settings.get('api',{}).get('send_sampling',False))
        if self.kind in ('llama','rust','maya') and isinstance(body.get('messages'),list):
            body['messages']=normalize_orphan_tool_messages(body['messages'])
        if self.kind in ('llama','maya'):
            if self.kind=='llama':body['repeat_penalty']=payload.get('repetition_penalty',1.0)
            body['chat_template_kwargs']=dict(payload.get('chat_template_kwargs') or {})
        if self.kind=='llama':
            # llama-server's own live figures: its timings on every chunk and the prompt read's progress
            # while it reads (timings_per_token, return_progress), and the final usage.
            body['timings_per_token']=True;body['return_progress']=True;body['stream_options']={'include_usage':True}
        cfg=self.settings.get('api',{});claude=self.kind=='api' and cfg.get('protocol')=='anthropic'
        if self.kind=='api' and not cfg.get('vision') and any(isinstance(m,dict) and isinstance(m.get('content'),list) and any(p.get('type')=='image_url' for p in m['content'] if isinstance(p,dict)) for m in payload.get('messages',[])):
            raise ValueError('Activa imágenes en esta conexión API antes de enviarlas al proveedor.')
        if claude:body=claude_payload(body,cfg.get('api_version',DEFAULT_ANTHROPIC_VERSION),(self.selected_remote() or {}).get('max_output_tokens'))
        elif self.kind in ('rust','maya') or self.kind=='api' and cfg.get('include_usage',True):body['stream_options']={'include_usage':True}
        target=urllib.parse.urlsplit(self.url('/messages' if claude else '/chat/completions'));decoder=ClaudeStream() if claude else None
        timeout=cfg.get('timeout',180) if self.kind=='api' else 1800
        session_id=self.session_uuid(conv_id) if self.kind=='api' else None
        req_headers=self.headers(stream=bool(body.get('stream',True)),session_id=session_id)
        connection=(http.client.HTTPSConnection(target.hostname,target.port or 443,timeout=timeout,context=ssl.create_default_context())
                    if target.scheme=='https' else http.client.HTTPConnection(target.hostname,target.port or 80,timeout=timeout))
        self.live=True;self.last_usage={}
        # What the engine itself reports during this request (never a guess): llama-server's per-chunk
        # timings and prompt progress, a provider's usage when it sends it before the end (Claude's
        # message_start, providers that stream usage). Strata Rust and Maya are asked directly (metrics()).
        self.live_usage={};self.live_timing={};self.live_progress=None;self.live_reading=True
        self._live_chars=len(json.dumps(body.get('messages') or [],ensure_ascii=False))+len(json.dumps(body.get('tools') or [],ensure_ascii=False))
        try:
            if control.cancelled.is_set():return
            try:connection.connect()
            except ConnectionRefusedError:
                if self.kind in ('llama','rust','maya') and (not self.process or self.process.poll() is not None):
                    self.stop()  # the engine closed after loading: the model is not loaded any more
                    raise ValueError('El motor se cerró y el modelo ya no está cargado. Vuelve a cargarlo; '
                                     'si vuelve a pasar, revisa el diagnóstico de carga.') from None
                raise
            control.attach(connection)
            req_path=(target.path or '/')+('?'+target.query if target.query else '')
            connection.request('POST',req_path,json.dumps(body,ensure_ascii=False).encode(),req_headers);response=connection.getresponse()
            if connection.sock is None and response.fp is not None:connection.sock=getattr(getattr(response.fp,'raw',None),'_sock',None)
            if response.status!=200:
                raw_err=response.read(4096)
                try:raw_err=decode_http_body(raw_err,response.getheader('Content-Encoding'))
                except OSError:pass
                text=raw_err.decode('utf8',errors='replace');key=self.key() if self.kind=='api' else ''
                if auto_max and response.status in (400,422) and re.search(r'max_(?:completion_)?tokens|output tokens|max.?output',text,re.I):
                    # This provider does not accept that output maximum: use its own default for this model.
                    if not hasattr(self,'_no_auto_max'):self._no_auto_max=set()
                    self._no_auto_max.add(remote.get('id'))
                    connection.close()
                    yield from self.stream(payload,control,conversation_id=conversation_id)
                    return
                raise ProviderHTTPError(provider_error(response.status,text,key),response.status,
                                        retry_after_ms({k.lower():v for k,v in response.getheaders()}))
            sent=time.monotonic();first=None;ended=False;held=None
            for line in iter_http_lines(response):
                if control.cancelled.is_set():return
                if first is None and self.kind!='llama' and line.startswith(b'data: {') and b'"delta"' in line:
                    first=time.monotonic();self.live_reading=False
                if held is not None and line.startswith(b'data: [DONE]'):
                    yield self._with_engine_timings(held);held=None
                if decoder:
                    if not line.startswith(b'data:'):continue
                    raw_data=line[5:].strip()
                    if not raw_data or raw_data==b'[DONE]':continue
                    try:packet=decoder.packet(json.loads(raw_data))
                    except ValueError as error:
                        key=self.key();raise ValueError(str(error).replace(key,'[oculta]') if key else str(error)) from None
                    self.last_usage=dict(decoder.usage)
                    # message_start carries the exact input count; the output count only comes at the end.
                    if self.last_usage.get('prompt_tokens'):self.live_usage={'prompt_tokens':self.last_usage['prompt_tokens']}
                    if packet:
                        ended=ended or stream_finished(packet)
                        yield packet
                    continue
                if line.startswith(b'data: ') and (b'"usage"' in line or b'"timings"' in line or b'"prompt_progress"' in line):
                    try:
                        packet=json.loads(line[6:]);usage=packet.get('usage');timing=packet.get('timings')
                        if not usage and (timing or packet.get('prompt_progress')) and self.kind=='llama':
                            # A live figure, not the reply's result: kept for the meters, not passed on.
                            self.live_timing=timing or self.live_timing
                            self.live_progress=packet.pop('prompt_progress',None) or self.live_progress
                            if (self.live_timing.get('predicted_n') or 0)>0:self.live_reading=False
                            packet.pop('timings',None);line=('data: '+json.dumps(packet,ensure_ascii=False)+'\n').encode()
                            timing=None
                        if usage:
                            self.last_usage=usage;self.live_usage=dict(usage)
                            if isinstance(usage.get('prompt_tokens'),int) and usage['prompt_tokens']>0:
                                self._calibration=(self._live_chars,usage['prompt_tokens'],self.loaded)
                        if usage and not timing and self.kind=='rust':
                            # Strata Rust's exact clocks are in its /api/stats once the request is recorded:
                            # this line waits for [DONE] and then carries them.
                            held=packet;continue
                        if usage and not timing and self.kind=='api' and first:
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
            if held is not None:yield self._with_engine_timings(held)
            if self.kind in ('api','maya') and not ended and not control.cancelled.is_set():
                # The provider closed the connection without its end-of-reply mark: what arrived is a
                # fragment, not an answer, and must not be shown as complete.
                raise ValueError('La respuesta del proveedor se cortó antes de terminar (la conexión se cerró a mitad). '
                                 'Vuelve a intentarlo; si se repite, revisa la conexión o el estado del proveedor.')
        finally:self.live=False;self.live_reading=False;control.detach(connection);connection.close()
    def _engine_json(self,path,body=None,timeout=1.5):
        """A local engine's own JSON endpoint (port 19383, its private key), or None."""
        try:
            data=None if body is None else json.dumps(body,ensure_ascii=False).encode()
            request=urllib.request.Request('http://127.0.0.1:19383'+path,data=data,headers={'Authorization':'Bearer '+self.llama_key,'Accept':'application/json','Content-Type':'application/json'})
            with urllib.request.urlopen(request,timeout=timeout) as response:result=json.load(response)
            return result if isinstance(result,dict) else None
        except (OSError,ValueError,urllib.error.URLError):return None
    def _with_engine_timings(self,packet):
        """Strata Rust's usage line with that request's timings from the engine (GET /api/stats)."""
        usage=packet.get('usage') or {};entry=None
        for _ in range(20):
            recent=(self._engine_json('/api/stats') or {}).get('recent') or []
            last=recent[-1] if recent and isinstance(recent[-1],dict) else None
            if last and last.get('prompt_tokens')==usage.get('prompt_tokens') and last.get('completion_tokens')==usage.get('completion_tokens'):
                entry=last;break
            time.sleep(.05)
        timing=strata_rust_timings(entry) if entry else {}
        if timing:packet['timings']=timing;self.last_timing=timing
        return ('data: '+json.dumps(packet,ensure_ascii=False)+'\n').encode()
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
        """Live and last figures as each engine reports them; a figure the engine does not report is None.

        llama.cpp: its per-chunk timings and prompt progress (stream()) and /slots. Strata Rust: GET /api/stats.
        Project Maya: GET /metrics, already in this shape. A provider (API): its usage, at the end of a reply
        (Claude also at the start), and the output speed as received."""
        number=lambda value:value if isinstance(value,(int,float)) and not isinstance(value,bool) and value>=0 else None
        if self.kind=='maya' and self.loaded:
            data=self._engine_json('/metrics',timeout=2) or {}
            if data:
                engine=dict(data.get('engine') or {});engine.setdefault('max_context',getattr(self,'loaded_context',None))
                live=dict(data.get('live') or {});live['prefill']=live.get('prefill_tok_s_mean')
                requests=[dict(row) for row in (data.get('requests') or []) if isinstance(row,dict)]
                newest=requests[0] if requests else {}
                return {'engine':engine,'live':live,'requests':requests,
                        'last':{'decode':newest.get('decode_tok_s'),'prefill':newest.get('prefill_tok_s')}}
        if self.kind=='rust' and self.loaded:
            data=self._engine_json('/api/stats') or {}
            recent=[row for row in (data.get('recent') or []) if isinstance(row,dict)]
            newest=recent[-1] if recent else None
            busy=bool(data.get('busy'));generated=number(data.get('live_tokens')) if busy else None
            state='generating' if busy and generated else 'reading' if busy else 'idle'
            tok_s=self._counter_rate(generated if busy else None)
            timing=strata_rust_timings(newest)
            requests=[{'prompt_tokens':newest.get('prompt_tokens'),'output_tokens':newest.get('completion_tokens')}] if newest else []
            # The prompt of the request being written is counted by the engine only when it ends: until then
            # the meter shows the last measured request, not a guess.
            return {'engine':{'max_context':number(data.get('ctx')) or getattr(self,'loaded_context',None)},
                    'live':{'state':state,'prompt_tokens':None,'generated':generated,'tok_s':tok_s},
                    'requests':requests,'last':{'decode':timing.get('predicted_per_second'),'prefill':timing.get('prompt_per_second')}}
        limit=(self.selected_remote() or {}).get('context') if self.kind=='api' else getattr(self,'loaded_context',None) if self.kind in ('rust','maya') and self.loaded else None
        prompt=self.last_usage.get('prompt_tokens');generated=self.last_usage.get('completion_tokens')
        last=[{'prompt_tokens':prompt,'output_tokens':generated}] if number(prompt) is not None and number(generated) is not None else []
        tok_s=prefill=prompt_read=prompt_total=None;live_prompt=live_generated=None
        if self.kind=='llama' and self.loaded:
            slot={}
            try:
                with urllib.request.urlopen(urllib.request.Request('http://127.0.0.1:19383/slots',headers={'Authorization':'Bearer '+self.llama_key}),timeout=1) as response:slots=json.load(response)
                slots=slots.get('slots') if isinstance(slots,dict) else slots
                slot=slots[0] if isinstance(slots,list) and slots and isinstance(slots[0],dict) else {}
            except (OSError,ValueError,TypeError,AttributeError,KeyError):pass
            limit=slot.get('n_ctx') or limit
            if self.live:
                timing=getattr(self,'live_timing',{}) or {};progress=getattr(self,'live_progress',None) or {}
                if timing:
                    live_prompt=(timing.get('prompt_n') or 0)+(timing.get('cache_n') or 0);live_generated=timing.get('predicted_n') or 0
                    if live_generated>0:tok_s=number(timing.get('predicted_per_second'))
                    elif number(timing.get('prompt_per_second')):prefill=round(timing['prompt_per_second'],1)
                if progress:
                    prompt_total=number(progress.get('total'));prompt_read=number(progress.get('processed'))
                    if prompt_total is not None and not live_generated:live_prompt=prompt_total
                if not timing and slot.get('is_processing'):
                    # Before the first chunk: the slot's own counters.
                    next_token=slot.get('next_token') or {}
                    if isinstance(next_token,list):next_token=next(iter(next_token),{})
                    live_prompt=slot.get('n_prompt_tokens') if isinstance(slot.get('n_prompt_tokens'),int) else (next_token or {}).get('n_prompt_tokens')
                    live_generated=(next_token or {}).get('n_decoded')
                if tok_s is not None:tok_s=round(tok_s,1)
        elif self.kind=='api' and self.live:
            live_prompt=(getattr(self,'live_usage',{}) or {}).get('prompt_tokens')
            live_generated=(getattr(self,'live_usage',{}) or {}).get('completion_tokens')
        if self.live:prompt,generated=live_prompt,live_generated
        reading=self.live and (getattr(self,'live_reading',False) or (prompt_total is not None and prompt_read is not None and prompt_read<prompt_total and not generated))
        state='reading' if reading else 'decoding' if self.live else 'idle'
        timing=getattr(self,'last_timing',{}) or {}
        return {'engine':{'max_context':limit},
                'live':{'state':state,'prompt_tokens':prompt,'generated':generated,'tok_s':tok_s,'prefill':prefill,
                        'prompt_read':prompt_read,'prompt_total':prompt_total},
                'requests':last,'last':{'decode':timing.get('predicted_per_second'),'prefill':timing.get('prompt_per_second')}}

    def count_prompt_tokens(self,messages,tools=None):
        """The exact prompt tokens of `messages` (+ `tools`, OpenAI function shapes), counted by the engine or the
        provider with the model's own tokenizer and template; None where nothing can count them (a plain
        OpenAI-compatible API has no counting endpoint)."""
        functions=[t.get('function',t) if isinstance(t,dict) else {} for t in (tools or [])]
        openai_tools=[{'type':'function','function':f} for f in functions]
        claude_tools=[{'name':f.get('name',''),'description':f.get('description',''),
                       'input_schema':f.get('parameters') or {'type':'object','properties':{}}} for f in functions]
        if self.kind=='llama' and self.loaded:
            rendered=self._engine_json('/apply-template',{'messages':messages,**({'tools':openai_tools} if openai_tools else {})},timeout=15)
            if not rendered or not isinstance(rendered.get('prompt'),str):return None
            tokens=self._engine_json('/tokenize',{'content':rendered['prompt'],'add_special':True,'parse_special':True},timeout=15)
            return len(tokens['tokens']) if tokens and isinstance(tokens.get('tokens'),list) else None
        if self.kind=='maya' and self.loaded:
            counted=self._engine_json('/tokenize',{'messages':messages,**({'tools':openai_tools} if openai_tools else {})},timeout=15)
            return counted.get('count') if counted and isinstance(counted.get('count'),int) else None
        claude_messages=[{'role':m.get('role'),'content':m.get('content')} for m in messages if isinstance(m,dict) and m.get('role') in ('user','assistant')]
        if self.kind=='rust' and self.loaded:
            counted=self._engine_json('/v1/messages/count_tokens',{'model':str(self.loaded),'messages':claude_messages,**({'tools':claude_tools} if claude_tools else {})},timeout=15)
            return counted.get('input_tokens') if counted and isinstance(counted.get('input_tokens'),int) else None
        if self.kind=='api' and self.settings.get('api',{}).get('protocol')=='anthropic' and self.selected_remote():
            try:
                status,raw=self._post_json('/messages/count_tokens',{'model':self.selected_remote()['id'],'messages':claude_messages,**({'tools':claude_tools} if claude_tools else {})},timeout=20)
                counted=json.loads(raw) if status==200 else {}
            except (OSError,ValueError):return None
            return counted.get('input_tokens') if isinstance(counted,dict) and isinstance(counted.get('input_tokens'),int) else None
        return None

    def _counter_rate(self,count):
        """Tokens per second from an engine's own live counter (Strata Rust's live_tokens) over the time between
        two readings of it: the engine's count, this clock. None until two readings half a second apart."""
        now=time.monotonic();mark=getattr(self,'_decode_mark',None)
        if count is None:self._decode_mark=None;return None
        if mark is None or count<mark[1]:self._decode_mark=(now,count);return None
        return round((count-mark[1])/(now-mark[0]),1) if count>mark[1] and now-mark[0]>=0.5 else None

    def _post_json(self,path,payload,extra_headers=None,timeout=120,session_id=None):
        target=urllib.parse.urlsplit(self.url(path))
        headers=self.headers(stream=False,session_id=session_id,extra_headers=extra_headers)
        connection=(http.client.HTTPSConnection(target.hostname,target.port or 443,timeout=timeout,context=ssl.create_default_context())
                    if target.scheme=='https' else http.client.HTTPConnection(target.hostname,target.port or 80,timeout=timeout))
        try:
            req_path=(target.path or '/')+('?'+target.query if target.query else '')
            connection.request('POST',req_path,json.dumps(payload,ensure_ascii=False).encode(),headers)
            response=connection.getresponse()
            raw_bytes=response.read(4*1024*1024)
            try:raw_bytes=decode_http_body(raw_bytes,response.getheader('Content-Encoding'))
            except OSError:pass
            raw=raw_bytes.decode('utf8',errors='replace')
            return response.status,raw
        finally:
            connection.close()

    def compact_context(self,model_id,messages,instructions=None,conversation_id=None):
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
        session_id=self.session_uuid(conversation_id) if (self.kind=='api' and conversation_id) else None
        session_kw={'session_id':session_id} if session_id else {}
        prompt=instructions or COMPACT_INSTRUCTIONS

        if self.kind=='api' and protocol=='anthropic':
            req={'model':raw_model,'system':[{'type':'text','text':prompt}],
                 'messages':[{'role':'user','content':'Conversation history to compress:\n\n'+transcript}],
                 'max_tokens':min(positive_int((self.selected_remote() or {}).get('max_output_tokens')) or 4096,4096),
                 'stream':False}
            extra={}
            if len(transcript)>=160000:
                extra['anthropic-beta']='compact-2026-01-12'
                req['context_management']={'edits':[{'type':'compact_20260112'}]}
            status,raw=self._post_json('/messages',req,extra_headers=extra,timeout=timeout,**session_kw)
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
                status,raw=self._post_json('/responses/compact',resp_payload,timeout=min(timeout,90),**session_kw)
            except OSError:
                status,raw=404,''
            if status==200:
                try:
                    data=json.loads(raw)
                    summary,comp_item,usage=extract_responses_compact_summary(data)
                    if summary or comp_item:
                        return {'ok':True,'method':'openai_responses_compact','method_label':'API nativa (/responses/compact)',
                                'summary':summary or 'Conversation state natively compacted by the API.',
                                **({'compacted_item':comp_item} if comp_item else {}),
                                **({'usage':usage} if usage else {})}
                except ValueError:
                    pass
            elif status not in (400,404,405,422,501):
                raise ValueError(provider_error(status,raw[:2048],key))

        chat_body={'model':raw_model,'stream':False,'messages':[{'role':'system','content':prompt},{'role':'user','content':'Conversation history to compress:\n\n'+transcript}]}
        if self.kind in ('llama','rust','maya'):
            chat_body['chat_template_kwargs']={'no_date':True,'enable_thinking':False}
        if self.kind=='api':
            chat_body=openai_payload(chat_body,self.base(),False)
            if 'thinking' in chat_body and 'reasoning_effort' not in chat_body:
                chat_body['thinking']={'type':'disabled'}
        status,raw=self._post_json('/chat/completions',chat_body,timeout=timeout,**session_kw)
        if status!=200:
            raise ValueError(provider_error(status,raw[:2048],key))
        try:data=json.loads(raw)
        except ValueError:raise ValueError('El servidor no devolvió una respuesta JSON válida al comprimir.') from None
        choice=(data.get('choices') or [None])[0] or {}
        summary=str(((choice.get('message') or {}).get('content')) or '').strip()
        summary=re.sub(r'<think>.*?</think>','',summary,flags=re.S).strip() or summary
        if not summary:
            raise ValueError('El modelo no devolvió texto al comprimir el contexto.')
        raw_usage=data.get('usage') if isinstance(data.get('usage'),dict) else None
        usage=None
        if raw_usage and isinstance(raw_usage.get('prompt_tokens'),int):
            usage={'prompt_tokens':raw_usage['prompt_tokens'],'completion_tokens':int(raw_usage.get('completion_tokens') or 0)}
        method='api_chat_completions' if self.kind=='api' else 'local_chat_completions'
        label='API nativa (/chat/completions)' if self.kind=='api' else 'Resumen con modelo local'
        return {'ok':True,'method':method,'method_label':label,'summary':summary,**({'usage':usage} if usage else {})}
