"""Official prebuilt releases, staged locally and activated only on explicit request."""
import hashlib
import json
from pathlib import Path,PurePosixPath
import re
import shutil
import subprocess
import threading
import time
import urllib.request
import urllib.parse
import zipfile
from runtime_paths import DATA_ROOT
from ui_preferences import atomic_json

FEEDS={'llama-cpu':('ggml-org/llama.cpp',r'^llama-.*-bin-win-cpu-x64\.zip$','llama-server.exe'),
       'llama-cuda':('ggml-org/llama.cpp',r'^llama-.*-bin-win-cuda-12\.4-x64\.zip$','llama-server.exe'),
       'llama-vulkan':('ggml-org/llama.cpp',r'^llama-.*-bin-win-vulkan-x64\.zip$','llama-server.exe'),
       'strata':('simplexai-labs/PolyStrata',r'^strata-poly-windows-x64-.*\.zip$','strata-poly.exe'),
       'rust':('RustingStudio/RustingStrata',r'^strata-windows-x86_64\.exe$','strata.exe')}

def active_installations():
    try:return json.loads((DATA_ROOT/'engine-updates/active.json').read_text(encoding='utf8'))
    except (OSError,ValueError):return {}

def executable(key,fallback):
    item=active_installations().get(key,{})
    path=Path(item.get('executable') or fallback)
    return path if path.is_file() else Path(fallback)

def extract_zip(archive,target):
    with zipfile.ZipFile(archive) as z:
        if sum(i.file_size for i in z.infolist())>5*2**30:raise ValueError('Archive is too large.')
        for item in z.infolist():
            name=PurePosixPath(item.filename.replace('\\','/'))
            if name.is_absolute() or '..' in name.parts or ':' in str(name) or (item.external_attr>>16)&0o170000==0o120000:raise ValueError('Unsafe archive path.')
        z.extractall(target)

class Updates:
    def __init__(self,builds):
        self.root=DATA_ROOT/'engine-updates';self.root.mkdir(parents=True,exist_ok=True)
        self.builds=builds;self.lock=threading.RLock();self.busy=False;self.installing=False;self.progress=None
        try:
            self.state=json.loads((self.root/'status.json').read_text(encoding='utf8'))
            if not isinstance(self.state,dict) or not isinstance(self.state.get('releases',{}),dict):raise ValueError('Invalid update cache.')
        except (OSError,ValueError):self.state={'checked_at':0,'releases':{},'deferred_until':0}
        if self.state.get('error'):
            self.state['last_error']=self.state.pop('error')
        if not self.state.get('busy') and str(self.state.get('operation') or '').startswith(('Descargando','Comprobando')):
            self.state['operation']=''
    def snapshot(self):
        with self.lock:return {**self.state,'busy':self.busy,'installing':self.installing,'installed':active_installations(),'progress':dict(self.progress) if self.progress else None}
    def save(self):atomic_json(self.root/'status.json',self.state)
    def check(self,force=False):
        with self.lock:
            if force:
                self.state['deferred_until']=0
                self.save()
            if self.busy or not force and time.time()-self.state.get('checked_at',0)<86400:return self.snapshot()
            self.busy=True
        def work():
            try:
                repos={};releases={};builds=self.builds();installed=active_installations()
                for key,(repo,pattern,exe) in FEEDS.items():
                    try:
                        if repo not in repos:
                            req=urllib.request.Request('https://api.github.com/repos/'+repo+'/releases?per_page=8',headers={'User-Agent':'VAL-Agent','Accept':'application/vnd.github+json'})
                            with urllib.request.urlopen(req,timeout=15) as response:repos[repo]=json.load(response)
                        candidate=next(((release,asset) for release in repos[repo] if not release.get('draft') and (not release.get('prerelease') or key.startswith('llama-')) for asset in release.get('assets',[]) if re.fullmatch(pattern,asset['name'])),None)
                        if candidate is None:releases[key]={'available':False,'message':'No hay un precompilado compatible publicado.','repository':repo};continue
                        release,asset=candidate;tag=release['tag_name']
                        current=installed.get(key,{}).get('tag') or builds.get({'llama-cpu':'cpu','llama-cuda':'cuda','llama-vulkan':'vulkan','rust':'rust'}.get(key,key),{}).get('build') or builds.get(key,{}).get('version') or ''
                        deps=[a for a in release.get('assets',[]) if key=='llama-cuda' and a['name']=='cudart-llama-bin-win-cuda-12.4-x64.zip']
                        releases[key]={'tag':tag,'development':bool(release.get('prerelease')),'current':current,'available':tag.lstrip('v')!=str(current).lstrip('v'),'notes':str(release.get('body') or '')[:100000],'url':release['html_url'],'repository':repo,'asset':asset,'dependencies':deps}
                    except Exception as error:releases[key]={'available':False,'error':str(error),'repository':repo}
                with self.lock:self.state.update(releases=releases,checked_at=time.time());self.save()
            finally:
                with self.lock:self.busy=False;self.installing=False
        threading.Thread(target=work,daemon=True).start();return self.snapshot()
    def defer(self):
        with self.lock:self.state['deferred_until']=time.time()+86400;self.save();return self.snapshot()
    def rollback(self,key):
        with self.lock:
            if self.busy or key not in self.state.get('previous',{}):raise ValueError('No hay una versión anterior disponible.')
            active=active_installations();previous=self.state['previous'].pop(key)
            if previous:active[key]=previous
            else:active.pop(key,None)
            atomic_json(self.root/'active.json',active)
            release=self.state.get('releases',{}).get(key,{})
            mapped={'llama-cpu':'cpu','llama-cuda':'cuda','llama-vulkan':'vulkan'}.get(key,key);build=self.builds().get(mapped,{})
            current=previous.get('tag') if previous else build.get('build') or build.get('version','')
            release.update(current=current,available=release.get('tag','').lstrip('v')!=str(current).lstrip('v'))
            self.state['operation']='Restaurado: '+key;self.save();return self.snapshot()
    def install(self,key):
        if key not in FEEDS:raise ValueError('Unknown engine.')
        # A release check (not an install) may still be finishing other feeds: wait for it instead
        # of failing, so "Download and install" right after "check" just works.
        deadline=time.time()+45
        while time.time()<deadline:
            with self.lock:
                if not self.busy or self.installing:break
            time.sleep(.25)
        with self.lock:
            if self.busy:raise ValueError('Hay otra operación en curso.')
            release=self.state.get('releases',{}).get(key,{})
            if not release.get('asset'):raise ValueError('Comprueba primero las versiones oficiales.')
            self.progress={'engine':key,'received':0,'total':sum(a.get('size',0) for a in [release['asset'],*release.get('dependencies',[])]),'phase':'download'};self.busy=True;self.installing=True;self.state['operation']='Descargando '+key;self.state.pop('error',None)
        def work():
            try:
                tag=re.sub(r'[^a-zA-Z0-9_.-]','_',release['tag']);folder=self.root/key/(tag+'-'+str(time.time_ns()));folder.mkdir(parents=True)
                files=[]
                for asset in [release['asset'],*release.get('dependencies',[])]:
                    url=asset['browser_download_url'];parts=urllib.parse.urlsplit(url)
                    if parts.scheme!='https' or parts.hostname!='github.com' or not parts.path.startswith('/'+FEEDS[key][0]+'/releases/download/'):raise ValueError('Release URL is not official.')
                    with self.lock:self.progress['phase']='download'
                    path=folder/Path(asset['name']).name;digest=hashlib.sha256();size=0
                    with urllib.request.urlopen(urllib.request.Request(url,headers={'User-Agent':'VAL-Agent'}),timeout=60) as response,path.open('wb') as output:
                        while chunk:=response.read(2**20):
                            size+=len(chunk)
                            if size>2*2**30:raise ValueError('Download is too large.')
                            output.write(chunk);digest.update(chunk)
                            with self.lock:self.progress['received']+=len(chunk)
                    if size!=asset['size']:raise ValueError('Incomplete engine download.')
                    expected=asset.get('digest')
                    if expected and expected!='sha256:'+digest.hexdigest():raise ValueError('Engine checksum mismatch.')
                    files.append({'name':asset['name'],'sha256':digest.hexdigest(),'upstream_digest':expected})
                    with self.lock:self.progress['phase']='extract'
                    if path.suffix=='.zip':extract_zip(path,folder/'bin')
                    else:(folder/'bin').mkdir(exist_ok=True);shutil.copy2(path,folder/'bin'/FEEDS[key][2])
                with self.lock:self.progress['phase']='verify'
                found=list((folder/'bin').rglob(FEEDS[key][2]))
                if len(found)!=1:raise ValueError('No se encontró un único ejecutable compatible.')
                exe=found[0]
                result=subprocess.run([str(exe),'--help' if key=='strata' else '--version'],cwd=str(exe.parent),capture_output=True,text=True,encoding='utf-8',errors='replace',timeout=15,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
                if key=='strata':
                    text=(result.stdout or '')+(result.stderr or '')
                    if 'usage:' not in text.lower():raise ValueError('El precompilado no puede iniciarse; se conserva el motor anterior.')
                elif result.returncode:raise ValueError('El precompilado no puede iniciarse; se conserva el motor anterior.')
                record={'tag':release['tag'],'executable':str(exe),'repository':FEEDS[key][0],'files':files}
                active=active_installations();self.state.setdefault('previous',{})[key]=active.get(key);active[key]=record;atomic_json(self.root/'active.json',active)
                with self.lock:self.state['releases'][key]['available']=False;self.progress['phase']='complete';self.state['operation']='Actualizado: '+key;self.save()
            except Exception as error:
                with self.lock:
                    if self.progress:self.progress['phase']='error'
                    self.state['error']=str(error);self.state['operation']='';self.save()
            finally:
                with self.lock:self.busy=False;self.installing=False
        threading.Thread(target=work,daemon=True).start();return self.snapshot()
