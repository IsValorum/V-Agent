"""Local extensions and marketplace catalog. Catalog refresh never executes packages."""
import base64,hashlib,json,re,threading,time,urllib.request,urllib.parse
from runtime_paths import DATA_ROOT
from ui_preferences import atomic_json

ROOT=DATA_ROOT/'extensions'
def _state_path():return ROOT/'installed.json'
def _backup_path():return ROOT/'installed.json.bak'
LOCK=threading.RLock()
RESERVED={'pc','hf','duckduckgo','web','autobrowser','admin','computer'}
SOURCES={'mcp':'https://registry.modelcontextprotocol.io/v0.1/servers?limit=100&version=latest','claude':'https://raw.githubusercontent.com/anthropics/claude-plugins-official/main/.claude-plugin/marketplace.json'}
def read(name,default):
    try:return json.loads((ROOT/name).read_text(encoding='utf8'))
    except (OSError,ValueError):return default

def _read_state():
    for path in (_state_path(),_backup_path()):
        try:
            value=json.loads(path.read_text(encoding='utf8'))
            if isinstance(value,dict):return value
        except (OSError,ValueError):continue
    return None

def _legacy_servers():
    """Import manual mcp.json entries once, never bundled workers or reserved names."""
    try:block=json.loads((DATA_ROOT/'mcp.json').read_text(encoding='utf8'))
    except (OSError,ValueError):return {}
    result={}
    for name,cfg in (block.get('mcpServers') or {}).items():
        if name in RESERVED or not isinstance(cfg,dict) or cfg.get('_val_bundled'):continue
        try:result.update(validate_servers({name:cfg}))
        except ValueError:continue
    return result

def _save_state(items):
    try:
        state=_state_path()
        if state.exists():
            previous=json.loads(state.read_text(encoding='utf8'))
            if isinstance(previous,dict):atomic_json(_backup_path(),previous)
    except (OSError,ValueError):pass
    atomic_json(_state_path(),items)
    if not _backup_path().exists():atomic_json(_backup_path(),items)

def configs():
    with LOCK:
        items=_read_state()
        if items is not None:return items
        legacy=_legacy_servers()
        if legacy:
            items={name:{'config':cfg,'enabled':False} for name,cfg in legacy.items()}
            _save_state(items)
            return items
        return {}

def enabled_configs():return {name:v['config'] for name,v in configs().items() if v.get('enabled')}

def _start_if_present(hub, name, server):
    # Serialize start and removal: a queued start must not run after access is revoked.
    with LOCK:
        if hub.servers.get(name) is server:
            server.start()

def reconcile(hub, full_access):
    """Stop external servers without changing the user's saved selections."""
    if hub is None:return
    from serve.mcp import McpServer
    with LOCK:
        desired=enabled_configs() if full_access else {}
        for name in list(hub.servers):
            if name not in RESERVED and name not in desired:
                hub.servers.pop(name).close()
        for name,cfg in desired.items():
            if name not in hub.servers:
                server=McpServer(name,cfg,hub.settings);hub.servers[name]=server
                threading.Thread(target=_start_if_present,args=(hub,name,server),daemon=True).start()

def validate_servers(block):
    if not isinstance(block,dict) or not block or len(block)>30:raise ValueError('Expected mcpServers object (1–30 entries).')
    result={}
    for name,cfg in block.items():
        if not re.fullmatch(r'[a-zA-Z][a-zA-Z0-9_-]{0,35}',name) or '__' in name or name in RESERVED:raise ValueError('Use a unique MCP name; bundled names are reserved.')
        if not isinstance(cfg,dict):raise ValueError('Invalid server configuration.')
        cfg={k:v for k,v in cfg.items() if k in ('command','args','env','cwd','url','headers','type')}
        if cfg.get('url'):
            url=urllib.parse.urlsplit(cfg['url'])
            if url.scheme not in ('https','http') or not url.hostname or url.username:raise ValueError('Invalid HTTP MCP URL.')
            if cfg.get('type') not in (None,'http','streamable-http'):raise ValueError('Only Streamable HTTP is supported, not legacy SSE.')
            if not isinstance(cfg.get('headers',{}),dict):raise ValueError('Headers must be an object.')
        else:
            if not isinstance(cfg.get('command'),str) or not cfg['command'].strip():raise ValueError('Missing command or URL.')
            if not isinstance(cfg.get('args',[]),list) or any(not isinstance(a,str) for a in cfg.get('args',[])):raise ValueError('args must be a string array.')
            if not isinstance(cfg.get('env',{}),dict) or any(not isinstance(v,str) for v in cfg.get('env',{}).values()):raise ValueError('env must contain strings.')
        if '${' in json.dumps(cfg) or 'REPLACE_ME' in json.dumps(cfg):raise ValueError('Replace environment/plugin-root placeholders with local values before adding.')
        result[name]=cfg
    return result

def public():
    return [{'name':n,'enabled':v.get('enabled',False),'transport':'http' if v['config'].get('url') else 'stdio','target':v['config'].get('url') or v['config'].get('command')} for n,v in configs().items()]
def register(manifest):
    if not isinstance(manifest,dict):raise ValueError('Expected JSON object.')
    block=manifest.get('mcpServers',manifest.get('mcp_servers'))
    if not block:raise ValueError('This plugin has no inline MCP servers. Hooks, skills and OpenCode JS plugins need their own host; they are not executed by V-Agent.')
    servers=validate_servers(block)
    with LOCK:
        items=configs()
        for name,cfg in servers.items():
            if items.get(name,{}).get('enabled'):raise ValueError('Disable the server before editing its configuration.')
            items[name]={'config':cfg,'enabled':False}
        _save_state(items)
    return public()

def toggle(name,enabled,hub,full_access):
    if enabled and not full_access:raise ValueError('Custom MCPs run outside the built-in sandbox. Select Full access first, then activate this MCP manually.')
    from serve.mcp import McpServer
    with LOCK:
        items=configs()
        if name not in items:raise ValueError('Unknown MCP.')
        if name in hub.servers:hub.servers.pop(name).close()
        if enabled:
            server=McpServer(name,items[name]['config'],hub.settings);hub.servers[name]=server
            threading.Thread(target=_start_if_present,args=(hub,name,server),daemon=True).start()
        items[name]['enabled']=bool(enabled);_save_state(items)
    return public()

class Catalog:
    def __init__(self):self.busy=False;self.lock=threading.Lock();self.state=read('catalog.json',{'checked_at':0,'items':[],'errors':[]})
    def snapshot(self):
        with self.lock:return {**self.state,'busy':self.busy,'sources':SOURCES}
    def refresh(self,force=False):
        with self.lock:
            if self.busy or not force and time.time()-self.state.get('checked_at',0)<86400:return {**self.state,'busy':self.busy,'sources':SOURCES}
            self.busy=True
        def work():
            items=[];errors=[]
            for kind,url in SOURCES.items():
                try:
                    with urllib.request.urlopen(urllib.request.Request(url,headers={'User-Agent':'VAL-Agent'}),timeout=15) as response:
                        raw=response.read(4*1024*1024+1)
                    if len(raw)>4*1024*1024:raise ValueError('Catalog too large.')
                    data=json.loads(raw)
                    for entry in data.get('servers' if kind=='mcp' else 'plugins',[]):
                        record=entry.get('server',{}) if kind=='mcp' else entry
                        item={'name':record.get('name',''),'description':str(record.get('description',''))[:500],'source':kind,'version':record.get('version',''),'manifest':None,'packages':record.get('packages',[])}
                        if kind=='mcp':
                            remote=next((r for r in record.get('remotes',[]) if r.get('type')=='streamable-http' and r.get('url')),None)
                            if remote and '{' not in remote['url']:item['manifest']={'mcpServers':{re.sub('[^a-zA-Z0-9_-]','_',str(record.get('name') or 'mcp'))[:34]:{'url':remote['url']}}}
                            item['compatibility']='Streamable HTTP' if item['manifest'] else 'Requires local configuration / dependencies'
                        else:
                            if isinstance(record.get('mcpServers'),dict):item['manifest']={'mcpServers':record['mcpServers']}
                            item['compatibility']='MCP component only' if item['manifest'] else 'Host-specific plugin; inspect MCP configuration'
                            item['homepage']=record.get('homepage');item['plugin_source']=record.get('source')
                        items.append(item)
                except Exception as error:errors.append(kind+': '+str(error));items.extend(i for i in self.state.get('items',[]) if i.get('source')==kind)
            with self.lock:self.state={'checked_at':time.time(),'items':items,'errors':errors};atomic_json(ROOT/'catalog.json',self.state);self.busy=False
        threading.Thread(target=work,daemon=True).start();return self.snapshot()

def prepare_plugin(item):
    # Resolve only entries that exist in the cached official marketplace.
    known=next((i for i in read('catalog.json',{}).get('items',[]) if i.get('name')==item.get('name') and i.get('source')==item.get('source')),None)
    if not known:raise ValueError('Refresh the marketplace first.')
    if known.get('manifest'):return {'manifest':known['manifest'],'message':'MCP component. Review configuration before adding; it stays disabled.'}
    if known.get('source')=='mcp' and known.get('packages'):
        package=next((p for p in known['packages'] if p.get('registryType') in ('npm','pypi') and p.get('transport',{}).get('type')=='stdio'),None)
        if not package:raise ValueError('This package needs manual configuration. Import its mcpServers JSON.')
        identifier=package.get('identifier','');version=package.get('version','')
        if not re.fullmatch(r'[@a-zA-Z0-9_/.-]+',identifier) or not re.fullmatch(r'[a-zA-Z0-9_.+-]+',version):raise ValueError('Use the publisher configuration manually.')
        cfg={'command':'npx' if package['registryType']=='npm' else 'uvx','args':['-y',identifier+'@'+version] if package['registryType']=='npm' else [identifier+'=='+version]}
        for argument in package.get('packageArguments',[])+package.get('runtimeArguments',[]):
            value=argument.get('value') or argument.get('default')
            if not value:raise ValueError('Package needs custom arguments; import publisher configuration manually.')
            if argument.get('type')=='named':cfg['args'].append(argument['name'])
            cfg['args'].append(str(value))
        env={v['name']:v.get('default') or v.get('value') or 'REPLACE_ME' for v in package.get('environmentVariables',[]) if v.get('name')}
        if env:cfg['env']=env
        return {'manifest':{'mcpServers':{re.sub('[^a-zA-Z0-9_-]','_',known['name'])[:34]:cfg}},'message':'Review pinned package and credentials. npx/uvx must be installed; activation may download and execute the package. Replace REPLACE_ME before adding.'}
    source=known.get('plugin_source')
    if isinstance(source,str) and source.startswith('./') and '..' not in source.split('/'):
        base='https://raw.githubusercontent.com/anthropics/claude-plugins-official/main/'+source[2:].rstrip('/')
    elif isinstance(source,dict) and source.get('source')=='github' and re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+',source.get('repo','')):
        base='https://raw.githubusercontent.com/'+source['repo']+'/HEAD'
    elif isinstance(source,dict) and source.get('source')=='git-subdir':
        match=re.fullmatch(r'https://github.com/([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+?)(?:\.git)?',source.get('url',''))
        path=source.get('path','');ref=source.get('sha') or source.get('ref') or 'HEAD'
        if not match or '..' in path.split('/') or not re.fullmatch(r'[a-zA-Z0-9_./-]*',path) or not re.fullmatch(r'[a-zA-Z0-9_.-]+',ref):raise ValueError('Unsupported plugin source.')
        base='https://raw.githubusercontent.com/'+match[1]+'/'+ref+'/'+path.strip('/')
    else:raise ValueError('No portable MCP component found. Import its mcpServers JSON manually; JS hooks, skills and host APIs are not supported.')
    for suffix in ('/.mcp.json','/.claude-plugin/plugin.json'):
        try:
            with urllib.request.urlopen(base+suffix,timeout=10) as response:raw=response.read(131073)
            if len(raw)>131072:continue
            data=json.loads(raw)
            block=(data.get('mcpServers') or (data if suffix=='/.mcp.json' else None)) if isinstance(data,dict) else None
            if isinstance(block,dict) and block:return {'manifest':{'mcpServers':block},'message':'Imported MCP component only. Local scripts need a local installation path; replace placeholders. Hooks and skills are not installed.'}
        except (OSError,ValueError):continue
    raise ValueError('This plugin has no portable MCP component. Its host-specific functions cannot run in V-Agent.')

def search_registry(query):
    query=str(query).strip()[:160]
    url=SOURCES['mcp']+'&search='+urllib.parse.quote(query)
    with urllib.request.urlopen(urllib.request.Request(url,headers={'User-Agent':'VAL-Agent'}),timeout=15) as response:raw=response.read(4*1024*1024+1)
    if len(raw)>4*1024*1024:raise ValueError('Catalog too large.')
    items=[]
    for entry in json.loads(raw).get('servers',[]):
        record=entry.get('server',{});remote=next((r for r in record.get('remotes',[]) if r.get('type')=='streamable-http' and r.get('url') and '{' not in r['url']),None)
        manifest={'mcpServers':{re.sub('[^a-zA-Z0-9_-]','_',str(record.get('name') or 'mcp'))[:34]:{'url':remote['url']}}} if remote else None
        items.append({'name':record.get('name',''),'description':str(record.get('description',''))[:500],'source':'mcp','version':record.get('version',''),'manifest':manifest,'compatibility':'Streamable HTTP' if manifest else 'Requires local configuration / dependencies','packages':record.get('packages',[])})
    return items
