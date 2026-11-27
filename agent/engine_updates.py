"""Official prebuilt releases, staged locally and activated only on explicit request."""
import hashlib
import json
import os
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
    """Extract after checking every path; returns the files written (relative, for reuse later)."""
    with zipfile.ZipFile(archive) as z:
        if sum(i.file_size for i in z.infolist())>5*2**30:raise ValueError('Archive is too large.')
        for item in z.infolist():
            name=PurePosixPath(item.filename.replace('\\','/'))
            if name.is_absolute() or '..' in name.parts or ':' in str(name) or (item.external_attr>>16)&0o170000==0o120000:raise ValueError('Unsafe archive path.')
        z.extractall(target)
        return [item.filename.replace('\\','/') for item in z.infolist() if not item.is_dir()]


def _link_or_copy(source,target):
    """Same disk: a hard link costs no space and survives deleting the old version."""
    target.parent.mkdir(parents=True,exist_ok=True)
    try:os.link(source,target)
    except OSError:shutil.copy2(source,target)


def _remove_tree(folder, attempts=6):
    """Delete an old engine folder. Right after an install, Windows Defender (or the search indexer) often
    keeps the new .exe/.dll open for a moment and rmtree fails with "access denied": that left an old
    version on disk until the next start (seen in GitHub's Windows runners). A few short retries, read-only
    attributes cleared; a folder still in use by a running engine stays and goes on a later start."""
    import stat

    def writable(function, path, _):
        try:
            os.chmod(path, stat.S_IWRITE)
            function(path)
        except OSError:
            pass
    for attempt in range(attempts):
        try:
            shutil.rmtree(folder, onexc=writable)
        except OSError:
            pass
        if not Path(folder).exists():
            return True
        time.sleep(0.15 * (attempt + 1))
    return False


def _version_folder(record):
    """engine-updates/<key>/<tag-time>/ of an installed record (its executable is under bin/)."""
    try:
        exe=Path(record['executable'])
        for parent in exe.parents:
            if parent.name=='bin':return parent.parent
    except (KeyError,TypeError):pass
    return None

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
        # Low priority and off the startup path: deleting gigabytes must not delay the first reply.
        threading.Thread(target=self.prune,name='engine-prune',daemon=True).start()
    def prune(self,only=None):
        """Keep, per engine, only the active version (a new one is tested before it replaces it).

        Earlier versions kept every update (llama.cpp CUDA: ~1.9 GB, published almost daily), then the
        active one plus the one before it, with the downloaded .zip files beside them. A folder still in
        use by a running engine cannot be deleted on Windows: it is skipped and removed on a later start.
        """
        with self.lock:
            if self.installing:return
            active=active_installations()
            if self.state.pop('previous',None) is not None:self.save()  # no second copy any more
        for key in ([only] if only else FEEDS):
            base=self.root/key
            if not base.is_dir():continue
            keep={folder for folder in (_version_folder(active.get(key)),) if folder}
            for folder in base.iterdir():
                if not folder.is_dir():continue
                if folder in keep:
                    for archive in folder.iterdir():
                        if archive.is_file():
                            try:archive.unlink()
                            except OSError:pass
                else:_remove_tree(folder)
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
                            import app_updates
                            req=urllib.request.Request('https://api.github.com/repos/'+repo+'/releases?per_page=20',headers={'User-Agent':'V-Agent/'+app_updates.VERSION,'Accept':'application/vnd.github+json','Accept-Encoding':'identity'})
                            with urllib.request.urlopen(req,timeout=15) as response:repos[repo]=json.load(response)
                        # The newest compatible build by publication date, straight to it (no stepping through
                        # the ones in between); GitHub's list order is by creation, not publication.
                        matches=[(release,asset) for release in repos[repo] if not release.get('draft') and (not release.get('prerelease') or key.startswith('llama-')) for asset in release.get('assets',[]) if re.fullmatch(pattern,asset['name'])]
                        candidate=max(matches,key=lambda pair:str(pair[0].get('published_at') or pair[0].get('created_at') or ''),default=None)
                        if candidate is None:releases[key]={'available':False,'message':'No hay un precompilado compatible publicado.','repository':repo};continue
                        release,asset=candidate;tag=release['tag_name']
                        current=installed.get(key,{}).get('tag') or builds.get({'llama-cpu':'cpu','llama-cuda':'cuda','llama-vulkan':'vulkan','rust':'rust'}.get(key,key),{}).get('build') or builds.get(key,{}).get('version') or ''
                        deps=[a for a in release.get('assets',[]) if key=='llama-cuda' and a['name']=='cudart-llama-bin-win-cuda-12.4-x64.zip']
                        releases[key]={'tag':tag,'development':bool(release.get('prerelease')),'current':current,'available':tag.lstrip('v')!=str(current).lstrip('v'),'notes':str(release.get('body') or '')[:100000],'url':release['html_url'],'repository':repo,'asset':asset,'dependencies':deps}
                    except Exception as error:
                        import app_updates
                        known=dict((self.state.get('releases') or {}).get(key) or {})
                        known.update(available=bool(known.get('available')),error=app_updates.friendly_network_error(error) or str(error),repository=repo)
                        releases[key]=known
                try:
                    import maya_engine
                    maya_info=builds.get('maya',{}) if isinstance(builds,dict) else {}
                    maya_ver=str(maya_info.get('build') or maya_info.get('version') or '')
                    releases['maya']=maya_engine.check_latest_release(maya_ver)
                except Exception as error:
                    releases['maya']={'available':False,'source_only':True,'error':str(error),'repository':'mw00/project-maya'}
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
            if active.get(key):self.state['previous'][key]=active[key]
            if previous:active[key]=previous
            else:active.pop(key,None)
            atomic_json(self.root/'active.json',active)
            release=self.state.get('releases',{}).get(key,{})
            mapped={'llama-cpu':'cpu','llama-cuda':'cuda','llama-vulkan':'vulkan'}.get(key,key);build=self.builds().get(mapped,{})
            current=previous.get('tag') if previous else build.get('build') or build.get('version','')
            release.update(current=current,available=release.get('tag','').lstrip('v')!=str(current).lstrip('v'))
            self.state['operation']='Restaurado: '+key;self.save();return self.snapshot()
    def uninstall(self,key):
        if key=='maya':
            with self.lock:
                if self.busy:raise ValueError('Hay otra operación en curso.')
                import maya_engine
                maya_build=(self.builds() or {}).get('maya',{})
                maya_engine.uninstall_installation(maya_build.get('root'))
                rel=self.state.get('releases',{}).get('maya',{})
                if rel:
                    rel.update(current='',available=False)
                    rel.pop('error',None)
                self.progress=None;self.state.pop('error',None);self.state['operation']='Project Maya desvinculado.';self.save();return self.snapshot()
        if key not in FEEDS:raise ValueError('Unknown engine.')
        with self.lock:
            if self.busy:raise ValueError('Hay otra operación en curso.')
            folder=self.root/key;active=active_installations()
            if not folder.exists() and key not in active and key not in self.state.get('previous',{}):
                raise ValueError('Ese motor no está instalado.')
            if folder.exists():
                for attempt in range(2):
                    try:shutil.rmtree(folder);break
                    except PermissionError:
                        if attempt:raise ValueError('No se pudo eliminar el motor porque sigue en uso.')
                        time.sleep(0.35)
                    except OSError as error:
                        raise ValueError('No se pudo eliminar el motor porque sigue en uso: '+str(error))
            active.pop(key,None);atomic_json(self.root/'active.json',active)
            self.state.setdefault('previous',{}).pop(key,None)
            release=self.state.get('releases',{}).get(key,{})
            mapped={'llama-cpu':'cpu','llama-cuda':'cuda','llama-vulkan':'vulkan'}.get(key,key);build=self.builds().get(mapped,{})
            current=build.get('build') or build.get('version','')
            if release:
                tag=str(release.get('tag') or '')
                release.update(current=current,available=bool(release.get('asset') and tag and tag.lstrip('v')!=str(current).lstrip('v')))
                release.pop('error',None)
            self.progress=None;self.state.pop('error',None);self.state['operation']='Eliminado: '+key;self.save();return self.snapshot()
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
            release=self.state.get('releases',{}).get(key,{})
        if not release.get('asset'):
            # No release information yet (just after a start, or an earlier check failed): look it up now
            # and go on, instead of "check the official versions first" after the user pressed Update.
            self.check(force=True)
            deadline=time.time()+90
            while time.time()<deadline:
                with self.lock:
                    if not self.busy:break
                time.sleep(.25)
        with self.lock:
            if self.busy:raise ValueError('Hay otra operación en curso.')
            release=self.state.get('releases',{}).get(key,{})
            if not release.get('asset'):
                raise ValueError(str(release.get('error') or '') or 'No se encontró una versión publicada de este motor. Vuelve a intentarlo en unos minutos.')
            self.progress={'engine':key,'received':0,'total':sum(a.get('size',0) for a in [release['asset'],*release.get('dependencies',[])]),'phase':'download'};self.busy=True;self.installing=True;self.state['operation']='Descargando '+key;self.state.pop('error',None)
        def work():
            try:
                tag=re.sub(r'[^a-zA-Z0-9_.-]','_',release['tag']);folder=self.root/key/(tag+'-'+str(time.time_ns()));folder.mkdir(parents=True)
                work_folder[0]=folder
                files=[]
                old=active_installations().get(key) or {}
                old_bin=(_version_folder(old) or Path('/nonexistent'))/'bin'
                reusable={item['upstream_digest']:item for item in old.get('files',[]) if item.get('upstream_digest') and item.get('extracted')}
                for asset in [release['asset'],*release.get('dependencies',[])]:
                    same=reusable.get(asset.get('digest') or '')
                    if same and all((old_bin/name).is_file() for name in same['extracted']):
                        # cudart (373 MB) rarely changes between llama.cpp builds: link it instead of downloading.
                        with self.lock:self.progress['phase']='link'
                        for name in same['extracted']:
                            dest=folder/'bin'/name
                            if not dest.exists():_link_or_copy(old_bin/name,dest)
                        files.append(same)
                        with self.lock:self.progress['received']+=asset.get('size',0)
                        continue
                    url=asset['browser_download_url'];parts=urllib.parse.urlsplit(url)
                    if parts.scheme!='https' or parts.hostname!='github.com' or not parts.path.startswith('/'+FEEDS[key][0]+'/releases/download/'):raise ValueError('Release URL is not official.')
                    with self.lock:self.progress['phase']='download'
                    path=folder/Path(asset['name']).name;digest=hashlib.sha256();size=0
                    import app_updates
                    with urllib.request.urlopen(urllib.request.Request(url,headers={'User-Agent':'V-Agent/'+app_updates.VERSION,'Accept-Encoding':'identity'}),timeout=60) as response,path.open('wb') as output:
                        while chunk:=response.read(2**20):
                            size+=len(chunk)
                            if size>2*2**30:raise ValueError('Download is too large.')
                            output.write(chunk);digest.update(chunk)
                            with self.lock:self.progress['received']+=len(chunk)
                    if size!=asset['size']:raise ValueError('Incomplete engine download.')
                    expected=asset.get('digest')
                    if expected and expected!='sha256:'+digest.hexdigest():raise ValueError('Engine checksum mismatch.')
                    with self.lock:self.progress['phase']='extract'
                    if path.suffix=='.zip':extracted=extract_zip(path,folder/'bin')
                    else:(folder/'bin').mkdir(exist_ok=True);extracted=[FEEDS[key][2]];shutil.copy2(path,folder/'bin'/FEEDS[key][2])
                    path.unlink()  # The archive is not needed once extracted.
                    files.append({'name':asset['name'],'sha256':digest.hexdigest(),'upstream_digest':expected,'extracted':extracted})
                with self.lock:self.progress['phase']='verify'
                found=list((folder/'bin').rglob(FEEDS[key][2]))
                if len(found)!=1:raise ValueError('No se encontró un único ejecutable compatible.')
                exe=found[0]
                verify_env={**os.environ,'PATH':str(exe.parent)+os.pathsep+os.environ.get('PATH','')}
                result=None
                for attempt in range(2):
                    try:
                        result=subprocess.run([str(exe),'--help' if key=='strata' else '--version'],cwd=str(exe.parent),env=verify_env,capture_output=True,text=True,encoding='utf-8',errors='replace',timeout=90,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
                        break
                    except (subprocess.TimeoutExpired,PermissionError,OSError) as error:
                        is_transient=isinstance(error,(subprocess.TimeoutExpired,PermissionError)) or getattr(error,'winerror',None) in (5,32,1450)
                        if attempt==0 and is_transient:
                            time.sleep(1.5);continue
                        if isinstance(error,(subprocess.TimeoutExpired,PermissionError)) or getattr(error,'winerror',None) in (5,32,1450):
                            raise ValueError('El precompilado tardó demasiado o quedó bloqueado al comprobarse; se conserva el motor anterior.') from error
                        raise
                if result is None:
                    raise ValueError('El precompilado tardó demasiado o quedó bloqueado al comprobarse; se conserva el motor anterior.')
                if key=='strata':
                    text=(result.stdout or '')+(result.stderr or '')
                    if 'usage:' not in text.lower():raise ValueError('El precompilado no puede iniciarse; se conserva el motor anterior.')
                elif result.returncode:
                    detail=(result.stderr or result.stdout or '').strip().splitlines()
                    suffix=(' ('+detail[-1][:180]+')') if detail else f' (código {result.returncode})'
                    raise ValueError('El precompilado no puede iniciarse; se conserva el motor anterior.'+suffix)
                record={'tag':release['tag'],'executable':str(exe),'repository':FEEDS[key][0],'files':files}
                with self.lock:
                    active=active_installations();active[key]=record;atomic_json(self.root/'active.json',active)
                    entry=self.state.setdefault('releases',{}).setdefault(key,{})
                    entry['current']=release['tag'];entry['available']=False;entry.pop('error',None)
                    if self.progress:self.progress['phase']='complete'
                    self.state.pop('error',None);self.state['operation']='Actualizado: '+key;self.save()
                work_folder[0]=None
            except Exception as error:
                import app_updates
                with self.lock:
                    if self.progress:self.progress['phase']='error'
                    self.state['error']=app_updates.friendly_network_error(error) or str(error);self.state['operation']='';self.save()
            finally:
                if work_folder[0]:shutil.rmtree(work_folder[0],ignore_errors=True)  # A failed download is gigabytes of nothing.
                with self.lock:self.busy=False;self.installing=False
            self.prune(key)
        work_folder=[None]
        threading.Thread(target=work,daemon=True).start();return self.snapshot()
