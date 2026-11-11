"""Compatibility boundary for the proven harness loop and pluggable engines.

Only this new copy installs the boundary. Engine-specific work stays in adapters;
the conversation, tools, drafts and UI protocols are shared.
"""
import hashlib
import json
import os
import threading
from pathlib import Path
from runtime_paths import DATA_ROOT,CONFIG_ROOT,RUNTIME_ROOT
from engine_manager import EngineManager
import plugins
from engine_updates import Updates,executable as updated_executable


def inspect_llama_import(value, template_path=None):
    file=Path(value).expanduser().resolve()
    if not file.is_file() or file.suffix.lower()!='.gguf':raise ValueError('Elige un GGUF instalado.')
    from gguf_reader import GGUFFile
    meta=GGUFFile(file,skip_tokenizer=True).metadata
    template=''
    if template_path:
        from model_import import _path, _validate_source
        selected=_path(template_path,('.jinja','.jinja2'))
        if selected.stat().st_size>262144:raise ValueError('La plantilla es demasiado grande (máximo 256 KB).')
        _validate_source(selected.read_text(encoding='utf-8-sig'));template=str(selected)
    identifier='local-'+hashlib.sha256(str(file).encode()).hexdigest()[:16]
    record=DATA_ROOT/'llama-added.json'
    entries=json.loads(record.read_text(encoding='utf8')) if record.exists() else []
    return {'name':file.name,'path':str(file),'family':meta.get('general.architecture'),
            'size_gib':round(file.stat().st_size/2**30,2),'size_bytes':file.stat().st_size,
            'template_name':Path(template).name if template else ('Incluida en el GGUF' if meta.get('tokenizer.chat_template') else 'Predeterminada del motor'),
            'architecture':meta.get('general.architecture'),'backend':'llama.cpp',
            'warnings':['La compatibilidad se comprobará al cargar en el motor.'],
            'already_registered':any(item.get('id')==identifier for item in entries),
            'identifier':identifier,'template':template,
            'context':meta.get(str(meta.get('general.architecture',''))+'.context_length') or 16384}


def register_llama_import(info, name=None):
    from ui_preferences import atomic_json
    record=DATA_ROOT/'llama-added.json'
    entries=json.loads(record.read_text(encoding='utf8')) if record.exists() else []
    identifier=info['identifier'];existing=next((item for item in entries if item.get('id')==identifier),None)
    if existing is None:
        entries.append({'id':identifier,'path':info['path'],'display_name':str(name or info['name']).strip()[:200] or info['name'],'context':info['context']})
        atomic_json(record,entries)
    if info['template']:
        folder=DATA_ROOT/'llama-configs';folder.mkdir(parents=True,exist_ok=True)
        config=folder/(hashlib.sha256(('llama--'+identifier).encode()).hexdigest()[:24]+'.json')
        saved=json.loads(config.read_text(encoding='utf8')) if config.exists() else {}
        saved.setdefault('engine_kind','llama');saved.setdefault('model_name','llama--'+identifier)
        saved.setdefault('args',['--model',info['path']]);saved.setdefault('context',info['context'])
        saved['template']=info['template'];atomic_json(config,saved)
    return {'status':'already_registered' if existing else 'registered','model':{'id':'llama--'+identifier}}


def _safe(job):
    try:job()
    except Exception:pass


def install(a):
    from app_preferences import AppPreferences
    from mcp_options import OPTIONS
    from tool_approvals import APPROVALS
    import thinking_policy
    preferences=AppPreferences()
    manager=EngineManager();updates=Updates(manager.builds);updates.check();a.PROVIDERS=manager;strata_auto=a.VRAM_AUTO;a.VRAM_AUTO=strata_auto and manager.kind=='strata'
    def update_payload(state=None):
        state=updates.check() if state is None else state
        try:
            from hardware_stats import profile_snapshot
            from engine_recommendations import recommend
            profile=profile_snapshot();recommended=recommend(profile,state.get('releases') or {})
            state={**state,'hardware':profile,'recommendations':recommended['engines'],'hardware_summary':recommended['summary']}
        except Exception:
            state={**state,'hardware':{},'recommendations':[],'hardware_summary':''}
        return state
    original={name:getattr(a,name) for name in ('installed_models','selected_model','engine_health','current_model','load_agent_model','unload_agent_model',
        'change_context','start_engine','stop_engine','stats','require_loaded_model','engine_context','engine_chat_stream','tokenizer_del_modelo','configure_model_draft')}
    default_profiles=json.loads(a.PROFILE_PATH.read_text(encoding='utf8'))['profiles']

    def models():
        if manager.kind=='strata':return original['installed_models']()
        entries=[]
        if manager.kind in ('llama','rust'):
            sources=a.registry.discover(CONFIG_ROOT)
            extra=DATA_ROOT/'llama-added.json'
            if extra.exists():sources+=json.loads(extra.read_text(encoding='utf8'))
        else:sources=[{**item,'id':manager.remote_identifier(item),'remote_id':item['id'],'display_name':item.get('display_name') or item['id'],'path':None,'backend':manager.settings.get('api',{}).get('name','API'),'remote':True} for item in manager.remote_models]
        ignored=set(json.loads(a.PROFILE_PATH.read_text(encoding='utf8')).get('ignored_models',[]))
        for source in sources:
            original_id=source['id'];identifier=(('rust--' if manager.kind=='rust' else 'llama--')+original_id) if manager.kind in ('llama','rust') else original_id
            if original_id in ignored or identifier in ignored:continue
            baseline={'sampling':default_profiles['code']['sampling'],'effort':'high','rounds':50,'context':source.get('context') or 16384,'kv':'fp16'}
            if original_id in a.MODEL_PREFERENCES.creators:a.MODEL_PREFERENCES.creators[identifier]=a.MODEL_PREFERENCES.creators[original_id]
            pref=a.MODEL_PREFERENCES.get(identifier,baseline)
            folder=DATA_ROOT/'llama-configs';folder.mkdir(exist_ok=True);config=folder/(hashlib.sha256(identifier.encode()).hexdigest()[:24]+'.json')
            saved=json.loads(config.read_text(encoding='utf8')) if config.exists() else {}
            config_data={**saved,'engine_kind':manager.kind,'model_name':identifier,'args':['--model',source.get('path') or ''],'context':pref['context']}
            if not config.exists():config.write_text(json.dumps(config_data),encoding='utf8')
            path=source.get('path');name=source.get('display_name') if original_id.startswith('local-') else (Path(path).name if path else source['display_name'])
            entries.append({**source,'id':identifier,'config':str(config),'gguf_name':name,'display_name':name,'context':pref['context'] if manager.kind in ('llama','rust') else source.get('context'),
                'status':'loaded' if manager.loaded==identifier else 'available','current':manager.loaded==identifier,'agent_profiles':default_profiles,'preferences':pref,
                'kv':{'current':pref.get('kv','fp16'),'options':([{'value':k,'label':label,'description':'Formato de caché de llama.cpp.'} for k,label in [('fp16','FP16'),('bf16','BF16'),('q8_0','Q8_0'),('q4_0','Q4_0')]] if manager.kind in ('llama','rust') else [])},
                'draft':{'integrated':False,'available':False,'files':[],'tokens':0,'source':'off'},'vision_settings':{'enabled':bool(saved.get('mmproj')),'mmproj':saved.get('mmproj',''),'supported':manager.kind=='llama','encoder_available':True,'encoder':'Integrado en llama.cpp'},'llama_settings':saved})
        if manager.kind=='rust':
            for item in entries:item['kv']['options']=[o for o in item['kv']['options'] if o['value'] in ('fp16','q8_0')]
        return {'models':entries,'data':entries,'loaded':bool(manager.loaded),'loaded_model':manager.loaded,'engine_online':manager.online or manager.kind in ('llama','rust'),
                'manual_loading':True,'current':manager.loaded,'profiles':default_profiles,'profile_version':1,'preparation':a.PREPARATION.snapshot()}

    def selected(name):
        if manager.kind=='strata':return original['selected_model'](name)
        item=next((item for item in models()['data'] if item['id']==name),None)
        if not item:raise ValueError('Ese modelo no está disponible en el motor seleccionado.')
        return item

    def health():
        if manager.kind=='strata':return original['engine_health']()
        if manager.kind in ('llama','rust') and manager.process and manager.process.poll() is not None:manager.stop()
        return {'status':'ok','loaded':bool(manager.loaded),'model':manager.loaded}

    def load(name,context=None):
        if updates.installing:raise ValueError('Espera a que termine la comprobación o actualización del motor.')
        if manager.kind=='strata':
            for file in CONFIG_ROOT.glob('strata-*.json'):
                cfg=json.loads(file.read_text(encoding='utf8'))
                if not cfg.get('_val_managed_engine'):continue
                exe=updated_executable('strata',RUNTIME_ROOT/'strata/strata-poly.exe')
                if str(exe)!=cfg.get('exe'):
                    cfg['exe']=str(exe);cfg['lib_dirs']=[str(exe.parent/'lib'),str(exe.parent)];__import__('ui_preferences').atomic_json(file,cfg)
        if manager.kind=='strata':
            model=selected(name);saved=a.MODEL_PREFERENCES.load(name)
            if saved and not (health() or {}).get('loaded'):
                from load_settings import effective
                from ui_preferences import atomic_json
                file=Path(model['config']);cfg=json.loads(file.read_text(encoding='utf-8-sig'));args=cfg.get('args',[])
                while '--prompt-cache' in args:
                    i=args.index('--prompt-cache');del args[i:i+2]
                args+=['--prompt-cache',str(effective(saved)['checkpoints'])];cfg['args']=args;atomic_json(file,cfg)
            return original['load_agent_model'](name,context)
        model=selected(name);manager.load(model,context or model['preferences']['context'],a.PREPARATION)
        return {'status':'loaded','model':model,'loaded':True,'loaded_model':name,'engine_online':True,'preparation':a.PREPARATION.snapshot()}

    def context(tokens,name=None):
        if manager.kind=='strata':return original['change_context'](tokens,name)
        if manager.kind=='api':raise ValueError('El contexto del modelo externo lo administra el proveedor.')
        name=name or manager.loaded;reloaded=manager.loaded==name
        a.MODEL_PREFERENCES.save(name,{'context':tokens})
        if reloaded:manager.stop();load(name,tokens)
        return {'status':'ok','context':tokens,'model':name,'reloaded':reloaded}

    def require(name):
        if manager.kind=='strata':return original['require_loaded_model'](name)
        if not manager.loaded:raise a.ModelStateError('Selecciona y carga un modelo en el motor actual.')
        if name not in (None,'','any','default',manager.loaded):raise a.ModelStateError('El modelo seleccionado no está cargado.')
        return manager.loaded

    def stream(payload,control):
        info=thinking_policy.capability(selected(payload.get('model')),manager.kind)
        thinking_policy.apply(payload,payload.get('reasoning_effort') or ('none' if payload.get('chat_template_kwargs',{}).get('enable_thinking') is False else info['default']),info)
        if manager.kind=='strata':yield from original['engine_chat_stream'](payload,control)
        else:
            if manager.kind=='api':payload={**payload,'model':manager.selected_remote()['id']}
            yield from manager.stream(payload,control)

    def stats():
        if manager.kind=='strata':return system_metrics(original['stats']())
        import psutil
        metrics=manager.metrics();ram=psutil.virtual_memory();usage=a.context_usage(metrics,bool(manager.loaded))
        timing=manager.last_timing
        return system_metrics({'engine_online':manager.online or manager.kind in ('llama','rust'),'loaded':bool(manager.loaded),'model':manager.loaded,'preparation':a.PREPARATION.snapshot(),
                'live':metrics['live'],'last':{'decode':timing.get('predicted_per_second'),'prefill':timing.get('prompt_per_second')},'context_usage':usage,
                **a.hardware_stats.snapshot()})

    import psutil
    logical_cpus=psutil.cpu_count()
    def system_metrics(result):
        result['cpu']={'percent':psutil.cpu_percent(interval=None),'logical':logical_cpus}
        try:
            disk=psutil.disk_usage(str(DATA_ROOT))
            result['storage']={'used_gib':round(disk.used/2**30,1),'total_gib':round(disk.total/2**30,1),'percent':disk.percent}
        except OSError:result['storage']={}
        return result

    def annotated_models():
        result=models()
        for model in result.get('data',[]):model['thinking']=thinking_policy.capability(model,manager.kind)
        return result
    a.installed_models=annotated_models;a.selected_model=selected;a.engine_health=health;a.load_agent_model=load;a.require_loaded_model=require;a.change_context=context;a.engine_chat_stream=stream;a.stats=stats
    a.current_model=lambda:original['current_model']() if manager.kind=='strata' else (manager.loaded,selected(manager.loaded)['config'] if manager.loaded else None)
    a.unload_agent_model=lambda:original['unload_agent_model']() if manager.kind=='strata' else manager.release_remote() if manager.kind=='api' else manager.stop()
    a.stop_engine=lambda *args,**kwargs:original['stop_engine'](*args,**kwargs) if manager.kind=='strata' else manager.stop()
    a.start_engine=lambda name=None:original['start_engine'](name) if manager.kind=='strata' else ({'status':'ready','engine_online':True} if manager.kind=='llama' else manager.connect())
    a.tokenizer_del_modelo=lambda *args:original['tokenizer_del_modelo'](*args) if manager.kind=='strata' else None
    a.engine_context=lambda:original['engine_context']() if manager.kind=='strata' else manager.metrics()['engine'].get('max_context')
    old_validate=a.kv_settings.validate
    a.kv_settings.FORMATS['bf16']=('BF16','Formato BF16 de llama.cpp.')
    def validate(config,value):
        cfg=json.loads(Path(config).read_text(encoding='utf8'))
        if cfg.get('engine_kind') in ('llama','rust'):
            if value not in (('fp16','q8_0') if cfg.get('engine_kind')=='rust' else ('fp16','bf16','q8_0','q4_0')):raise ValueError('Formato KV no habilitado para esta compilación.')
            return value
        return old_validate(config,value)
    a.kv_settings.validate=validate
    from local_console import Console
    from browser_bridge import BrowserBridge
    console=Console()
    browser=BrowserBridge()
    import atexit
    atexit.register(console.close)
    atexit.register(browser.close)
    import extensions
    catalog=extensions.Catalog();catalog.refresh()
    import model_hub,external_models

    def add_gguf(path,name=None,settings=None):
        """Add a GGUF for llama.cpp (as the Add model dialog does) and keep the settings it came with."""
        settings=settings or {};template_path=None
        if settings.get('template'):
            text=str(settings['template'])
            if len(text.encode())>262144:raise ValueError('La plantilla es demasiado grande (máximo 256 KB).')
            folder=DATA_ROOT/'imported-templates';folder.mkdir(parents=True,exist_ok=True)
            template_path=folder/(hashlib.sha256(text.encode()).hexdigest()[:24]+'.jinja');template_path.write_text(text,encoding='utf-8')
        info=inspect_llama_import(str(path),str(template_path) if template_path else None)
        result=register_llama_import(info,name)
        model='llama--'+info['identifier'];preferences={}
        from model_preferences import RANGES
        sampling={k:v for k,v in (settings.get('sampling') or {}).items() if k in RANGES and isinstance(v,(int,float)) and not isinstance(v,bool) and RANGES[k][0]<=v<=RANGES[k][1]}
        for key in ('top_k','max_tokens','seed'):
            if key in sampling:sampling[key]=int(sampling[key])
        if sampling:preferences['sampling']=sampling
        if isinstance(settings.get('context'),int):preferences['context']=max(2048,min(262144,settings['context']))
        if settings.get('kv') in ('fp16','bf16','q8_0','q4_0'):preferences['kv']=settings['kv']
        if preferences:a.MODEL_PREFERENCES.save(model,preferences)
        return {'id':model,'status':result['status'],'applied':sorted(preferences)}

    def hub_register(path,job):
        return add_gguf(path,Path(job['name']).stem)['id']
    hub_downloads=model_hub.Downloads(register=hub_register)

    def registered_paths():
        record=DATA_ROOT/'llama-added.json'
        try:entries=json.loads(record.read_text(encoding='utf8')) if record.exists() else []
        except ValueError:entries=[]
        return {os.path.normcase(str(Path(item.get('path','')).resolve())) for item in entries if item.get('path')}

    def model_settings(model_id):
        item=selected(model_id);pref=item.get('preferences') or {}
        settings={'name':item.get('display_name') or model_id,'path':item.get('path'),'sampling':pref.get('sampling') or {},
                  'context':pref.get('context'),'kv':pref.get('kv')}
        template=(item.get('llama_settings') or {}).get('template')
        if template and Path(template).is_file():settings['template']=Path(template).read_text(encoding='utf-8-sig')
        return settings

    def automatic_updates():
        """A few seconds after start: apply the newest signed minor update (1.0.0 C1, C2…) and fetch
        a newer installer if there is one, so a fresh install always ends up on the latest release.
        Both are verified against the maintainer's key; installing a full update still asks first."""
        import time
        time.sleep(4)
        try:
            from components import COMPONENTS
            if COMPONENTS.check().get('available'):COMPONENTS.apply()
        except Exception:pass
        try:
            from app_updates import UPDATES as app_update
            if app_update.check().get('available'):app_update.download()
        except Exception:pass
    if os.environ.get('V_AGENT_NO_AUTO_UPDATE')!='1':
        threading.Thread(target=automatic_updates,name='v-agent-auto-updates',daemon=True).start()

    old_handler=a.Handler
    class Handler(old_handler):
        def do_GET(self):
            if self.path=='/api/harness/console':self._json(200,console.snapshot());return
            if self.path=='/api/harness/browser/pending':self._json(200,{'items':browser.take()});return
            if self.path=='/api/harness/market':self._json(200,{'catalog':catalog.refresh(),'installed':extensions.public(),'health':a.HUB.status() if a.HUB else {}});return
            if self.path=='/api/harness/plugins':self._json(200,{'plugins':plugins.public(),'root':str(plugins.ROOT)});return
            if self.path.startswith('/assets/branding/'):
                from runtime_paths import SOURCE_ROOT
                import re
                name=self.path.removeprefix('/assets/branding/')
                if re.fullmatch(r'(?:originals/(?:gold|silver|jade|blue|rose|ruby|violet|ivory)\.png|(?:gold|silver|jade|blue|rose|ruby|violet|ivory)-(?:card\.jpg|mark\.png|cutout\.svg|icon\.png))',name):
                    try:
                        raw=(SOURCE_ROOT/'agent/assets/branding'/name).read_bytes();self.send_response(200)
                        self.send_header('Content-Type','image/svg+xml' if name.endswith('.svg') else 'image/png' if name.endswith('.png') else 'image/jpeg');self.send_header('Content-Length',str(len(raw)));self.send_header('X-Content-Type-Options','nosniff');self.send_header('Cache-Control','public, max-age=86400');self.end_headers();self.wfile.write(raw)
                    except OSError:self._json(404,{'error':'Logo not found.'})
                else:self._json(404,{'error':'Logo not found.'})
                return
            assets={'/assets/ui-mcp.js':('ui-mcp.js','text/javascript; charset=utf-8'),
                    '/assets/ui-motion.js':('ui-motion.js','text/javascript; charset=utf-8'),
                    '/assets/ui-i18n.js':('ui-i18n.js','text/javascript; charset=utf-8'),
                    '/assets/ui-panels.css':('ui-panels.css','text/css; charset=utf-8'),
                    '/assets/locales.json':('locales.json','application/json; charset=utf-8')}
            if self.path in assets:
                from runtime_paths import UI_DIST
                name,mime=assets[self.path]
                raw=(UI_DIST/'assets'/name).read_bytes()
                self.send_response(200);self.send_header('Content-Type',mime);self.send_header('Content-Length',str(len(raw)));self.send_header('Cache-Control','no-store');self.end_headers();self.wfile.write(raw);return
            if self.path.split('?')[0] in ('/assets/ui-patch.css','/assets/ui-patch.js'):
                # Interface fixes from the signed components channel (empty when none is applied).
                import components
                name=self.path.split('?')[0].rsplit('/',1)[1]
                found=components.resource(name,Path('/nonexistent')/name)
                raw=found.read_bytes() if found.is_file() else b''
                self.send_response(200);self.send_header('Content-Type','text/css; charset=utf-8' if name.endswith('.css') else 'text/javascript; charset=utf-8')
                self.send_header('Content-Length',str(len(raw)));self.send_header('Cache-Control','no-store');self.send_header('X-Content-Type-Options','nosniff');self.end_headers();self.wfile.write(raw);return
            if self.path=='/api/harness/preferences':self._json(200,preferences.get());return
            if self.path=='/api/harness/mcp-options':self._json(200,OPTIONS.get());return
            if self.path=='/api/harness/updates':self._json(200,update_payload());return
            if self.path=='/api/harness/app-update':
                from app_updates import UPDATES as app_update
                self._json(200,app_update.snapshot());return
            if self.path=='/api/harness/components':
                from components import COMPONENTS
                self._json(200,COMPONENTS.snapshot());return
            if self.path=='/api/harness/hardware':self._json(200,update_payload());return
            if self.path.startswith('/api/harness/hub/') or self.path.startswith('/api/harness/external/'):
                import urllib.parse
                parts=urllib.parse.urlsplit(self.path);query=urllib.parse.parse_qs(parts.query);arg=lambda key:(query.get(key) or [''])[0]
                try:
                    if parts.path=='/api/harness/hub/search':self._json(200,{'models':model_hub.search(arg('q'),arg('sort') or 'downloads',arg('kind') or 'text')})
                    elif parts.path=='/api/harness/hub/model':
                        from hardware_stats import profile_snapshot
                        hardware=profile_snapshot();gpu=hardware.get('primary_gpu') or {}
                        self._json(200,{**model_hub.details(arg('repo')),'hardware':{'vram_mib':gpu.get('vram_mib') or 0,'ram_gib':(hardware.get('ram') or {}).get('total_gib') or 0}})
                    elif parts.path=='/api/harness/hub/downloads':self._json(200,hub_downloads.snapshot())
                    elif parts.path=='/api/harness/external/scan':
                        result=external_models.scan();known=registered_paths()
                        for item in result['models']:item['registered']=os.path.normcase(str(Path(item['path']).resolve())) in known
                        self._json(200,result)
                    else:self._json(404,{'error':'Ruta desconocida.'})
                except Exception as error:self._json(400,{'error':str(error)[:300]})
                return
            if self.path=='/api/harness/state':self._json(200,manager.snapshot());return
            if manager.kind!='strata' and self.path=='/api/context/usage':
                run=dict(a.ACTIVE_CONTEXT_RUN);usage=a.context_usage(manager.metrics(),bool(manager.loaded)) if run else None
                self._json(200,{**run,'usage':usage} if run else {'run_id':None,'usage':None});return
            if manager.kind!='strata' and self.path=='/api/vision/status':
                enabled=bool(selected(manager.loaded).get('llama_settings',{}).get('mmproj')) if manager.loaded and manager.kind=='llama' else manager.settings.get('api',{}).get('vision',False)
                self._json(200,{'model':manager.loaded,'vision':{'enabled':enabled}});return
            super().do_GET()
        def do_POST(self):
            handled=self.path.startswith('/api/harness/') or (manager.kind=='llama' and self.path in ('/api/models/inspect','/api/models/register','/api/models/vision'))
            if not handled:return super().do_POST()
            if not a.ui_origin_allowed(self.headers.get('Origin'),a.PORT):
                self._json(403,{'error':'Esta acción requiere los controles locales de V-Agent.'});return
            if self.path=='/api/harness/memory-estimate':
                try:
                    size=int(self.headers.get('Content-Length') or 0)
                    if not 0<size<=16384:raise ValueError('Solicitud de memoria no válida.')
                    body=json.loads(self.rfile.read(size));model=selected(body.get('model'))
                    if manager.kind=='api':raise ValueError('La memoria del proveedor no se administra en este equipo.')
                    context=body.get('context',model.get('context') or 16384)
                    if type(context) is not int or not 2048<=context<=262144:raise ValueError('Contexto fuera de rango.')
                    kv=body.get('kv') or model.get('preferences',{}).get('kv','fp16')
                    if manager.kind=='strata':a.kv_settings.validate(model['config'],kv)
                    elif kv not in {item['value'] for item in model.get('kv',{}).get('options',[])}:raise ValueError('Formato de caché KV no admitido por el motor seleccionado.')
                    from load_settings import validate,capabilities
                    from memory_estimate import estimate
                    load=validate(body.get('load',model.get('preferences',{}).get('load',{})))
                    caps=capabilities(manager.executable()) if manager.kind=='llama' else {}
                    if manager.kind=='strata':
                        config=json.loads(Path(model['config']).read_text(encoding='utf-8-sig'));args=config.get('args',[]);caps['prompt_batch']=int(args[args.index('--prompt-batch')+1]) if '--prompt-batch' in args else 1024
                    cfg=manager.settings.get('llama',{});layers='auto' if manager.kind=='strata' else '0' if cfg.get('variant')=='cpu' else cfg.get('gpu_layers','auto')
                    result=estimate(model,context,kv,load,manager.kind,layers,caps)
                    from draft_models import validate as validate_draft,weight_bytes
                    draft=validate_draft(body.get('draft') or model.get('preferences',{}).get('draft') or {})
                    draft_size=weight_bytes(draft)
                    if draft_size:
                        result['draft']=draft_size;result['weights']=int(result.get('weights') or 0)+draft_size
                        if result.get('total') is not None:result['total']+=draft_size
                        if result.get('gpu_full_offload') is not None:result['gpu_full_offload']+=draft_size
                        result.setdefault('notes',[]).append('El draft suma sus pesos; su caché y buffers añaden consumo adicional.')
                    self._json(200,{'memory':result,'capabilities':caps})
                except (ValueError,OSError,KeyError,TypeError,EOFError) as error:self._json(400,{'error':str(error)})
                return
            if self.path=='/api/harness/console':
                try:
                    size=int(self.headers.get('Content-Length') or 0)
                    if not 0<size<=20000:raise ValueError('Invalid console request.')
                    body=json.loads(self.rfile.read(size))
                    if body.get('action')=='stop':result=console.stop()
                    elif body.get('action')=='clear':result=console.clear()
                    elif body.get('action')=='run':
                        if a.ACCESS.snapshot()['mode']!='full_pc':raise ValueError('La consola requiere Acceso completo. Actívalo manualmente en el chat.')
                        if body.get('cwd'):
                            cwd=Path(str(body['cwd'])).expanduser().resolve()
                            if not cwd.is_dir():raise ValueError('La carpeta de la consola no existe.')
                        elif body.get('conversation_id'):
                            cwd=a.PROJECTS.workspace(a.ACCESS,body['conversation_id']).root
                        else:cwd=DATA_ROOT
                        result=console.start(body.get('command'),body.get('shell','powershell'),cwd)
                    else:raise ValueError('Unknown console action.')
                    self._json(200,result)
                except (ValueError,OSError) as error:self._json(400,{'error':str(error)})
                return
            if self.path in ('/api/harness/browser','/api/harness/browser/result'):
                try:
                    size=int(self.headers.get('Content-Length') or 0)
                    limit=131072 if self.path.endswith('/result') else 65536
                    if not 0<size<=limit:raise ValueError('Solicitud de navegador no válida.')
                    body=json.loads(self.rfile.read(size))
                    if self.path.endswith('/result'):
                        ok=browser.resolve(str(body.get('id') or ''),body.get('result'),body.get('error'))
                        self._json(200,{'ok':ok})
                        return
                    action=str(body.get('action') or '')
                    if action not in ('open','navigate','snapshot','text','click','fill','press','eval','back','forward','reload','close'):
                        raise ValueError('Acción de navegador no admitida.')
                    args=body.get('args') if isinstance(body.get('args'),dict) else {}
                    timeout=max(1,min(int(body.get('timeout') or 30),90))
                    try:result=browser.request(action,args,timeout)
                    except TimeoutError as error:
                        self._json(504,{'error':str(error)})
                        return
                    self._json(200,{'result':result})
                except (ValueError,OSError) as error:self._json(400,{'error':str(error)})
                return
            if self.path.startswith('/api/harness/admin/'):
                try:
                    action=self.path.rsplit('/',1)[-1]
                    if action not in ('start','status','stop'):raise ValueError('Acción de administrador no admitida.')
                    if not a.HUB:raise ValueError('Los MCP todavía no están listos.')
                    result=a.HUB.call('admin__'+action,{})
                    text=result.get('text') if isinstance(result,dict) else str(result)
                    try:parsed=json.loads(text)
                    except (TypeError,ValueError):parsed={'ok':False,'error':str(text)[:300]}
                    self._json(200,parsed)
                except (ValueError,OSError) as error:self._json(400,{'error':str(error)})
                return
            if self.path=='/api/harness/plugins':
                try:
                    size=int(self.headers.get('Content-Length') or 0)
                    if not 0<size<=200000:raise ValueError('Solicitud de plugin no válida.')
                    body=json.loads(self.rfile.read(size));action=body.get('action')
                    if action=='install_path':result=plugins.install_path(body.get('path'))
                    elif action=='install_manifest':result=plugins.install_manifest(body.get('manifest'))
                    elif action=='toggle':
                        if type(body.get('enabled')) is not bool:raise ValueError('Estado de plugin no válido.')
                        result=plugins.set_enabled(body.get('id'),body.get('enabled'))
                    elif action=='remove':result=plugins.remove(body.get('id'))
                    else:raise ValueError('Acción de plugin desconocida.')
                    self._json(200,{'plugins':result,'root':str(plugins.ROOT)})
                except (ValueError,OSError) as error:self._json(400,{'error':str(error)})
                return
            if self.path=='/api/harness/market':
                try:
                    size=int(self.headers.get('Content-Length') or 0)
                    if not 0<size<=131072:raise ValueError('Request too large.')
                    body=json.loads(self.rfile.read(size))
                    if body.get('action')=='search':
                        found=extensions.search_registry(body.get('query',''))
                        with catalog.lock:
                            existing={(i['source'],i['name']):i for i in catalog.state.get('items',[])}
                            existing.update({(i['source'],i['name']):i for i in found});catalog.state['items']=list(existing.values())
                            from ui_preferences import atomic_json
                            atomic_json(extensions.ROOT/'catalog.json',catalog.state)
                        result={'items':found}
                    elif body.get('action')=='refresh':result=catalog.refresh(True)
                    elif body.get('action')=='register':result=extensions.register(body.get('manifest'))
                    elif body.get('action')=='prepare':result=extensions.prepare_plugin(body.get('item',{}))
                    elif body.get('action')=='toggle':
                        if not a.ENGINE_LOCK.acquire(blocking=False):raise ValueError('Stop generation before changing MCPs.')
                        try:result=extensions.toggle(body.get('name'),body.get('enabled') is True,a.HUB,a.ACCESS.snapshot()['mode']=='full_pc')
                        finally:a.ENGINE_LOCK.release()
                    else:raise ValueError('Unknown action.')
                    self._json(200,result)
                except (ValueError,OSError) as error:self._json(400,{'error':str(error)})
                return
            if self.path in ('/api/harness/preferences','/api/harness/mcp-options'):
                try:
                    size=int(self.headers.get('Content-Length') or 0)
                    if not 0<size<=4096:raise ValueError('Solicitud no válida.')
                    store=OPTIONS if self.path.endswith('/mcp-options') else preferences
                    self._json(200,store.save(json.loads(self.rfile.read(size))))
                except (ValueError,OSError) as error:self._json(400,{'error':str(error)})
                return
            if self.path=='/api/harness/components':
                # Signed minor updates (MCP servers, tool descriptions); see components.py.
                from components import COMPONENTS
                try:
                    size=int(self.headers.get('Content-Length') or 0)
                    if not 0<size<=1024:raise ValueError('Invalid request.')
                    action=json.loads(self.rfile.read(size)).get('action')
                    if action=='check':result=COMPONENTS.check()
                    elif action=='apply':result=COMPONENTS.apply()
                    elif action=='reset':result=COMPONENTS.reset()
                    else:raise ValueError('Unknown action.')
                    self._json(200,result)
                except (ValueError,OSError) as error:self._json(400,{'error':str(error)})
                return
            if self.path=='/api/harness/app-update':
                # V-Agent's own signed updates (see app_updates.py): check, download+verify, launch.
                from app_updates import UPDATES as app_update
                try:
                    size=int(self.headers.get('Content-Length') or 0)
                    if not 0<size<=1024:raise ValueError('Invalid request.')
                    action=json.loads(self.rfile.read(size)).get('action')
                    if action=='check':result=app_update.check()
                    elif action=='download':
                        if not app_update.snapshot().get('available'):raise ValueError('No hay una actualización verificada.')
                        threading.Thread(target=_safe,args=(app_update.download,),daemon=True).start();result=app_update.snapshot()
                    elif action=='launch':
                        if (health() or {}).get('loaded'):raise ValueError('Descarga el modelo antes de instalar la actualización.')
                        result={**app_update.snapshot(),**app_update.launch()}
                    else:raise ValueError('Unknown action.')
                    self._json(200,result)
                except (ValueError,OSError) as error:self._json(400,{'error':str(error)})
                return
            if self.path.startswith('/api/harness/updates/'):
                try:
                    size=int(self.headers.get('Content-Length') or 0)
                    if not 0<size<=4096:raise ValueError('Invalid request.')
                    body=json.loads(self.rfile.read(size));action=self.path.rsplit('/',1)[1]
                    if action=='check':result=updates.check(True)
                    elif action=='defer':result=updates.defer()
                    elif action in ('install','rollback'):
                        if not a.ENGINE_LOCK.acquire(blocking=False):raise ValueError('Espera a que termine la operación actual.')
                        try:
                            if (health() or {}).get('loaded') or a.PREPARATION.snapshot().get('active'):raise ValueError('Descarga el modelo antes de actualizar motores.')
                            result=updates.install(body.get('engine')) if action=='install' else updates.rollback(body.get('engine'))
                        finally:a.ENGINE_LOCK.release()
                    else:raise ValueError('Unknown action.')
                    self._json(200,update_payload(result))
                except (ValueError,OSError) as error:self._json(400,{'error':str(error)})
                return
            if self.path.startswith('/api/harness/hub/') or self.path.startswith('/api/harness/external/'):
                try:
                    size=int(self.headers.get('Content-Length') or 0)
                    if not 0<size<=4*2**20:raise ValueError('Solicitud no válida.')
                    body=json.loads(self.rfile.read(size))
                    if self.path=='/api/harness/hub/download':result=hub_downloads.start(body.get('repo'),body.get('file'))
                    elif self.path=='/api/harness/hub/cancel':result=hub_downloads.cancel(body.get('id'))
                    elif self.path=='/api/harness/hub/folder':result=hub_downloads.set_folder(body.get('path'))
                    elif self.path=='/api/harness/external/import':
                        items=body.get('items')
                        if not isinstance(items,list) or not 0<len(items)<=200:raise ValueError('Elige al menos un modelo.')
                        done=[]
                        for item in items:
                            try:done.append({'path':item.get('path'),**add_gguf(item.get('path',''),item.get('name'),item)})
                            except (ValueError,OSError,KeyError) as error:done.append({'path':item.get('path'),'error':str(error)[:200]})
                        result={'results':done}
                    elif self.path=='/api/harness/external/export':
                        settings=model_settings(body.get('model'));target=body.get('target')
                        if target=='lmstudio':result={'written':external_models.export_lmstudio(settings['path'],settings)}
                        elif target=='unsloth':result={'written':external_models.export_unsloth(settings['name'],settings)}
                        elif target=='file':result={'file':{'type':'v-agent-model-settings','version':1,'models':[settings]}}
                        else:raise ValueError('Destino desconocido.')
                    else:raise ValueError('Acción desconocida.')
                    self._json(200,result)
                except (ValueError,OSError,KeyError,TypeError) as error:self._json(400,{'error':str(error)[:300]})
                return
            if self.path=='/api/harness/approval':
                try:
                    size=int(self.headers.get('Content-Length') or 0)
                    if not 0<size<=4096:raise ValueError('Invalid request.')
                    body=json.loads(self.rfile.read(size));APPROVALS.resolve(body.get('id'),body.get('allowed'),bool(body.get('remember',False)));self._json(200,{'ok':True})
                except (ValueError,OSError) as error:self._json(400,{'error':str(error)})
                return
            if not a.ENGINE_LOCK.acquire(blocking=False):self._json(409,{'error':'Detén la generación antes de cambiar el motor.'});return
            try:
                size=int(self.headers.get('Content-Length') or 0)
                if not 0<size<=65536:raise ValueError('Solicitud no válida.')
                body=json.loads(self.rfile.read(size))
                if self.path=='/api/harness/configure':
                    if (health() or {}).get('loaded'):raise ValueError('Descarga el modelo actual antes de cambiar de motor.')
                    a.stop_engine();state=manager.configure(body);a.VRAM_AUTO=strata_auto and manager.kind=='strata';self._json(200,state)
                elif self.path=='/api/harness/connect':self._json(200,manager.connect())
                elif self.path=='/api/harness/model-context':self._json(200,manager.remote_context(body.get('model'),body.get('context')))
                elif self.path=='/api/models/vision':
                    model=selected(body['model']);path=Path(model['config']);cfg=json.loads(path.read_text())
                    mmproj=str(body.get('mmproj','')).strip()
                    if body.get('enabled') and (not Path(mmproj).is_file() or Path(mmproj).suffix.lower()!='.gguf'):raise ValueError('Elige un mmproj GGUF compatible.')
                    cfg['mmproj']=mmproj if body.get('enabled') else '';a.MODEL_PREFERENCES.save(model['id'],{})
                    from ui_preferences import atomic_json
                    atomic_json(path,cfg);self._json(200,{'vision':{'enabled':bool(cfg['mmproj']),'mmproj':mmproj,'supported':True,'encoder_available':True,'encoder':'Integrado en llama.cpp'}})
                elif self.path in ('/api/models/inspect','/api/models/register'):
                    info=inspect_llama_import(body.get('path',''),body.get('template_path'))
                    if self.path.endswith('/inspect'):self._json(200,info)
                    else:self._json(200,register_llama_import(info,body.get('name')))
                else:self._json(404,{'error':'Acción desconocida.'})
            except (ValueError,OSError,KeyError) as error:self._json(400,{'error':str(error)})
            finally:a.ENGINE_LOCK.release()
    a.Handler=Handler
