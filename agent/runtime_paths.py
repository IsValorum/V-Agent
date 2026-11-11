"""Read-only application resources and independently writable user data."""
import os
from pathlib import Path
import sys

SOURCE_ROOT=Path(getattr(sys,'_MEIPASS',Path(__file__).resolve().parents[1]))
DATA_ROOT=Path(os.environ.get('STRATA_AGENT_DATA') or (Path(sys.executable).parent/'data' if getattr(sys,'frozen',False) else SOURCE_ROOT/'data')).resolve()
CONFIG_ROOT=DATA_ROOT/'strata'
RUNTIME_ROOT=SOURCE_ROOT/'runtime'
SETTINGS_ROOT=DATA_ROOT/'settings'
LOG_ROOT=DATA_ROOT/'logs'

def command(role,*args):
    if getattr(sys,'frozen',False):return [sys.executable,'--role',role,'--',*map(str,args)]
    files={'agent':SOURCE_ROOT/'backend.py','strata-server':SOURCE_ROOT/'serve/server.py','pc':SOURCE_ROOT/'agent/pc_mcp.py',
           'hf':SOURCE_ROOT/'agent/hf_mcp.py','web':SOURCE_ROOT/'web_mcp/buscador_mcp.py','webtools':SOURCE_ROOT/'web_mcp/http_tools_mcp.py','autobrowser':SOURCE_ROOT/'agent/browser_mcp.py','admin':SOURCE_ROOT/'agent/admin_mcp.py','admin-helper':SOURCE_ROOT/'agent/admin_helper.py','computer':SOURCE_ROOT/'agent/computer_mcp.py','pick':SOURCE_ROOT/'agent/pick_model_file.py'}
    if role=='hf-cli':return [sys.executable,'-m','huggingface_hub.cli.hf',*map(str,args)]
    if role in ('web','webtools','autobrowser','admin','admin-helper','computer'):return [sys.executable,str(SOURCE_ROOT/'backend.py'),'--role',role,'--',*map(str,args)]
    return [sys.executable,str(files[role]),*map(str,args)]

# Windows LANGID written by the installer (Spanish, English, Portuguese, French, German).
INSTALLER_LANGUAGES={1034:'es',3082:'es',2058:'es',1033:'en',2057:'en',1046:'pt',2070:'pt',1036:'fr',1031:'de'}

def installer_language():
    """Language picked in the installer (install-language.txt next to V-Agent.exe), if any."""
    if not getattr(sys,'frozen',False):return None
    try:value=int((Path(sys.executable).resolve().parent.parent/'install-language.txt').read_text(encoding='ascii').strip())
    except (OSError,ValueError):return None
    return INSTALLER_LANGUAGES.get(value) or INSTALLER_LANGUAGES.get(value&0x3ff|0x400)

SEED_FILES=('model-profiles.json','creator-recommendations.json','template-provenance.json')

def seed_agent_files():
    """Copy the clean starting data into the user's folder when missing (first start, fresh clone)."""
    import shutil
    (CONFIG_ROOT/'agent').mkdir(parents=True,exist_ok=True)
    for name in SEED_FILES:
        dest=CONFIG_ROOT/'agent'/name
        if not dest.exists():shutil.copy2(SOURCE_ROOT/'agent'/name,dest)

def bootstrap():
    import json,shutil
    for folder in (DATA_ROOT,CONFIG_ROOT,SETTINGS_ROOT,LOG_ROOT,CONFIG_ROOT/'agent',DATA_ROOT/'cache/browser'):folder.mkdir(parents=True,exist_ok=True)
    preferences=SETTINGS_ROOT/'app-preferences.json'
    if not preferences.exists():
        # First start after installing: the interface (and its tutorial) use the installer language.
        language=installer_language()
        if language:preferences.write_text(json.dumps({'language':language},ensure_ascii=False),encoding='utf-8')
    assets=CONFIG_ROOT/'agent/model-assets'
    if not assets.exists() and (SOURCE_ROOT/'seeds/model-assets').is_dir():shutil.copytree(SOURCE_ROOT/'seeds/model-assets',assets)
    assets.mkdir(parents=True,exist_ok=True)
    seed_agent_files()
    for name in ('ui-preferences.json','model-preferences.json'):
        dest=SETTINGS_ROOT/name;seed=SOURCE_ROOT/'seeds/preferences'/name
        if not dest.exists() and seed.exists():shutil.copy2(seed,dest)
    for seed in (SOURCE_ROOT/'seeds/configs').glob('strata-*.json'):
        dest=CONFIG_ROOT/seed.name
        if dest.exists():continue
        cfg=json.loads(seed.read_text(encoding='utf-8-sig'));identifier=cfg['model_name']
        cfg['_val_managed_engine']=True
        cfg.update(exe=str(RUNTIME_ROOT/'strata/strata-poly.exe'),cwd=str(CONFIG_ROOT),port=19382,
                   tokenizer=str(assets/identifier/'tokenizer'),log=str(LOG_ROOT/(seed.stem+'.log')))
        cfg['lib_dirs']=[str(RUNTIME_ROOT/'strata/lib')]
        if cfg.get('vision'):cfg['vision']['exe']=str(RUNTIME_ROOT/'strata/strata-vision.exe')
        if cfg.get('agent_vision'):cfg['agent_vision']['exe']=str(RUNTIME_ROOT/'strata/strata-vision.exe')
        args=cfg.get('args',[])
        if '--expert-profile' in args:
            old=Path(args[args.index('--expert-profile')+1]);profile=assets/identifier/'expert-profile.txt'
            args[args.index('--expert-profile')+1]=str(profile if profile.exists() else old)
        dest.write_text(json.dumps(cfg,ensure_ascii=False,indent=2),encoding='utf8')
    for dest in CONFIG_ROOT.glob('strata-*.json'):
        cfg=json.loads(dest.read_text(encoding='utf8'))
        if cfg.get('_val_managed_engine'):
            from engine_updates import executable
            active_exe=executable('strata',RUNTIME_ROOT/'strata/strata-poly.exe')
            changed={**cfg,'exe':str(active_exe),'lib_dirs':[str(active_exe.parent/'lib'),str(active_exe.parent)],'cwd':str(CONFIG_ROOT),'port':19382}
            identifier=cfg['model_name'];changed['tokenizer']=str(assets/identifier/'tokenizer')
            changed['log']=str(LOG_ROOT/(dest.stem+'.log'))
            args=list(cfg.get('args',[]));profile=assets/identifier/'expert-profile.txt'
            if '--expert-profile' in args and profile.exists():args[args.index('--expert-profile')+1]=str(profile)
            changed['args']=args
            for key in ('vision','agent_vision'):
                if cfg.get(key):changed[key]={**cfg[key],'exe':str(RUNTIME_ROOT/'strata/strata-vision.exe')}
            if changed!=cfg:dest.write_text(json.dumps(changed,ensure_ascii=False,indent=2),encoding='utf8')
    mcp=DATA_ROOT/'mcp.json'
    servers={}
    for name,role in [('pc','pc'),('hf','hf'),('duckduckgo','web'),('web','webtools'),('autobrowser','autobrowser'),('admin','admin'),('computer','computer')]:
        argv=command(role)
        servers[name]={'command':argv[0],'args':argv[1:],'cwd':str(DATA_ROOT),
            'timeout_ms':900000 if role=='hf' else 315000 if role=='pc' else 60000,
            'env':{'PYTHONUTF8':'1','PYTHONIOENCODING':'utf-8','STRATA_AGENT_DATA':str(DATA_ROOT)}}
    existing=json.loads(mcp.read_text(encoding='utf8')) if mcp.exists() else {'mcpServers':{}}
    # Refresh bundled worker locations after moving/updating the portable app;
    # keep manually registered servers and their options intact.
    for name,entry in servers.items():
        prior=existing.setdefault('mcpServers',{}).get(name,{})
        bundled=not prior or prior.get('_val_bundled') or 'VALHarness' in prior.get('command','')
        if bundled:existing['mcpServers'][name]={**prior,**entry,'_val_bundled':True}
    mcp.write_text(json.dumps(existing,indent=2),encoding='utf8')
    empty=DATA_ROOT/'engine-mcp.json'
    if not empty.exists():empty.write_text('{"mcpServers":{}}',encoding='utf8')
    os.environ['STRATA_AGENT_DATA']=str(DATA_ROOT)
    os.environ['STRATA_AGENT_BROWSER_PROFILE']=str(DATA_ROOT/'cache/browser')
    os.environ['STRATA_AGENT_NO_OPEN']='1'
    os.environ['PATH']=str(RUNTIME_ROOT)+os.pathsep+os.environ.get('PATH','')
