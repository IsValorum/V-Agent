"""Optional per-model image encoder configuration. No loading on discovery/save."""
import json
import os
from pathlib import Path
from model_import import _atomic_json, _path, _metadata
from draft_settings import argument


def describe(config_path):
    path=Path(config_path);cfg=json.loads(path.read_text(encoding='utf-8-sig'))
    saved=cfg.get('vision') or cfg.get('agent_vision') or {}
    from runtime_paths import _managed_vision_encoder
    encoder=_managed_vision_encoder(saved.get('exe'))
    import kv_settings
    arch=kv_settings.describe(path).get('architecture')
    return {'enabled':bool(cfg.get('vision')),'mmproj':saved.get('mmproj',''),'encoder':encoder,
            'encoder_available':Path(encoder).is_file(),'gpu':bool(saved.get('gpu')),
            'supported':arch in ('qwen35moe','gemma4'),
            'next_load':True}


def configure(config_path,body):
    path=Path(config_path);cfg=json.loads(path.read_text(encoding='utf-8-sig'))
    old=describe(path);enabled=body.get('enabled')
    if type(enabled) is not bool:raise ValueError('Indica si quieres activar visión.')
    mmproj=body.get('mmproj','').strip();encoder=body.get('encoder','').strip() or old['encoder']
    settings={**(cfg.get('vision') or cfg.get('agent_vision') or {}),'exe':encoder,'mmproj':mmproj,'gpu':False,'elastic':True,'max_tokens':1024}
    if mmproj:
        projection=_path(mmproj,('.gguf',));meta=_metadata(projection)
        if meta.get('general.architecture')!='clip' and not any(key.startswith('clip.') for key in meta):
            raise ValueError('Ese GGUF no es un proyector visual (mmproj).')
        settings['mmproj']=str(projection)
    if enabled:
        # Registry configurations use model_type/backend depending on the pack.
        from serve.models import discover
        model=next((m for m in discover(path.parent) if Path(m['config'])==path),{})
        if model.get('backend') not in ('qwen35moe','gemma4'):
            raise ValueError('La integración visual de este motor no está verificada para esta arquitectura.')
        if not mmproj:raise ValueError('Elige el mmproj correspondiente a este modelo.')
        if not Path(encoder).is_file() or Path(encoder).name.lower() not in ('strata-vision.exe','strata-vision'):
            raise ValueError('Falta strata-vision. Selecciona el codificador visual instalado con Strata.')
        weight=argument(cfg.get('args',[]),'--model','')
        settings['model']=str((Path(cfg.get('cwd') or path.parent)/weight).resolve())
        weight_meta=_metadata(Path(settings['model']))
        architecture=weight_meta.get('general.architecture','')
        width=weight_meta.get(architecture+'.embedding_length');projected=meta.get('clip.vision.projection_dim')
        if isinstance(width,int) and isinstance(projected,int) and width!=projected:
            raise ValueError(f'El mmproj entrega {projected} dimensiones; este modelo requiere {width}.')
        settings.setdefault('threads',max(1,(os.cpu_count() or 4)//2))
        cfg['vision']=settings
    else:cfg.pop('vision',None)
    cfg['agent_vision']=settings;_atomic_json(path,cfg)
    return describe(path)
