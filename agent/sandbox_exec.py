"""Fail-closed Windows command execution using the bundled Microsoft MXC preview."""
import base64
import hashlib
import json
import os
from pathlib import Path
import stat
import subprocess
import tempfile
import threading
import uuid

from runtime_paths import RUNTIME_ROOT

_EXPECTED='6049c64723af1173c3739dc6cd6b2f33f6c021bb2832c4216233cba7f71aee9a'
_BINARY=RUNTIME_ROOT/'mxc'/'wxc-exec.exe'
_LOCK=threading.Lock()
_STATUS=None
_NO_WINDOW=getattr(subprocess,'CREATE_NO_WINDOW',0)


def _scan(root):
    """Reject links and oversized trees rather than granting an unchecked project."""
    pending=[Path(root)];seen=0
    while pending:
        directory=pending.pop()
        with os.scandir(directory) as entries:
            for entry in entries:
                seen+=1
                if seen>50000:raise ValueError('Project is too large to verify for isolated execution (50,000 entries).')
                info=entry.stat(follow_symlinks=False)
                if stat.S_ISLNK(info.st_mode) or getattr(info,'st_file_attributes',0)&0x400:
                    raise ValueError('Isolated execution requires a workspace without symbolic links or junctions: '+entry.path)
                if entry.is_dir(follow_symlinks=False):pending.append(Path(entry.path))
                elif os.stat(entry.path,follow_symlinks=False).st_nlink>1:raise ValueError('Isolated execution cannot use a workspace containing hard-linked files: '+entry.path)


_RUNTIMES=None


def _registered_pythons():
    """Official installers register here even when "Add to PATH" was left unchecked (PEP 514)."""
    try:import winreg
    except ImportError:return []
    found=[]
    for hive in (winreg.HKEY_CURRENT_USER,winreg.HKEY_LOCAL_MACHINE):
        try:core=winreg.OpenKey(hive,r'Software\Python\PythonCore')
        except OSError:continue
        with core:
            index=0
            while True:
                try:tag=winreg.EnumKey(core,index)
                except OSError:break
                index+=1
                try:
                    with winreg.OpenKey(core,tag+r'\InstallPath') as key:found.append((tag,winreg.QueryValue(key,None)))
                except OSError:pass
    def order(item):
        parts=[int(p) if p.isdigit() else 0 for p in item[0].split('-')[0].split('.')[:2]]
        return parts+[0]*(2-len(parts))
    return [path for _,path in sorted(found,key=order,reverse=True) if path]


def _python_home():
    """Locate a real Python install (not a Store alias or venv) to expose read-only in the container."""
    import shutil
    candidates=[shutil.which(name) for name in ('python','python3')]
    candidates+=[str(Path(path)/'python.exe') for path in _registered_pythons()]
    for found in candidates:
        if not found or 'windowsapps' in found.lower() or not Path(found).is_file():continue
        home=Path(found).resolve().parent
        config=home.parent/'pyvenv.cfg' if home.name.lower()=='scripts' else home/'pyvenv.cfg'
        if config.is_file():
            for line in config.read_text(encoding='utf-8',errors='replace').splitlines():
                key,_,value=line.partition('=')
                if key.strip().lower()=='home':home=Path(value.strip());break
        if (home/'python.exe').is_file() and (home/'Lib').is_dir():return home
    return None


def _python3_alias(home):
    """Models trained on Linux type python3; on Windows the installer only provides python.exe."""
    try:
        from runtime_paths import DATA_ROOT
        folder=Path(DATA_ROOT)/'cache'/'isolation-aliases'
        folder.mkdir(parents=True,exist_ok=True)
        shim=folder/'python3.cmd';text=f'@"{home / "python.exe"}" %*\r\n'
        if not shim.is_file() or shim.read_text(encoding='utf-8')!=text:shim.write_text(text,encoding='utf-8',newline='')
        return str(folder)
    except (OSError,ImportError):return None


def runtimes():
    """Read-only interpreter folders available inside isolation; Node and most System32 tools do not start there."""
    global _RUNTIMES
    if _RUNTIMES is None:
        home=_python_home();_RUNTIMES={}
        if home:
            _RUNTIMES['python']=str(home)
            alias=_python3_alias(home)
            if alias:_RUNTIMES['python3']=alias
    return dict(_RUNTIMES)


def _hint(code,err):
    text=err.lower()
    if code==3221225794 or 'no se reconoce' in text or 'not recognized' in text or 'acceso denegado' in text or 'access is denied' in text:
        tools=', '.join(runtimes()) or 'none'
        return ('\n[hint] Isolated mode runs CMD built-ins (echo, type, set, cd, mkdir, copy) plus: '+tools+
                '. dir, where, node, git and the drive root are unavailable here. List or read files with fs_list/fs_read; '
                'do not guess other commands. Programs outside this list need the user to switch to Full PC access.')
    return ''


def _config(root,script,timeout):
    windows=Path(os.environ.get('SystemRoot',r'C:\Windows')).resolve()
    executable=windows/'System32'/'cmd.exe'
    extra=list(runtimes().values())
    environment={'SystemRoot':str(windows),'WINDIR':str(windows),'PATH':';'.join([str(windows/'System32'),*extra]),
                 'TEMP':str(root),'TMP':str(root),'USERPROFILE':str(root),'LOCALAPPDATA':str(root),
                 'PYTHONIOENCODING':'utf-8','PYTHONDONTWRITEBYTECODE':'1'}
    return {'version':'0.8.0-alpha','containerId':'val-'+uuid.uuid4().hex,'containment':'processcontainer',
      'lifecycle':{'destroyOnExit':True,'preservePolicy':False},
      'process':{'commandLine':subprocess.list2cmdline([str(executable),'/d','/c',script.name]),
                 'cwd':str(root),'env':[f'{k}={v}' for k,v in environment.items()],'timeout':timeout*1000},
      'filesystem':{'readwritePaths':[str(root)],'readonlyPaths':[str(windows),*extra],'deniedPaths':[]},
      'network':{'defaultPolicy':'block','allowLocalNetwork':False,'allowedHosts':[],'blockedHosts':[],'enforcementMode':'capabilities'},
      'processContainer':{'leastPrivilege':True,'capabilities':[]},'fallback':{'allowDaclMutation':False}}


def _launch(root,command,timeout):
    root=Path(root).resolve()
    fd,name=tempfile.mkstemp(prefix='.val-isolated-',suffix='.cmd',dir=root)
    try:
        with os.fdopen(fd,'w',encoding='utf-8',newline='\r\n') as file:
            file.write('@echo off\nchcp 65001 >nul\n'+command+'\n')
        config=_config(root,Path(name),timeout)
        payload=base64.b64encode(json.dumps(config,ensure_ascii=False).encode('utf-8')).decode('ascii')
        with tempfile.TemporaryFile() as stdout_file,tempfile.TemporaryFile() as stderr_file:
            proc=subprocess.Popen([str(_BINARY),'--config-base64',payload],stdin=subprocess.DEVNULL,
                                  stdout=stdout_file,stderr=stderr_file,creationflags=_NO_WINDOW)
            try:proc.wait(timeout=timeout+5)
            except subprocess.TimeoutExpired:
                subprocess.run(['taskkill','/F','/T','/PID',str(proc.pid)],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=10,creationflags=_NO_WINDOW)
                proc.wait(timeout=10);raise TimeoutError('Isolated command timed out.')
            def read(stream):
                stream.seek(0);data=stream.read(64001)
                return data[:64000].decode('utf-8','replace')+('\n[Output truncated.]' if len(data)>64000 else '')
            return proc.returncode,read(stdout_file),read(stderr_file)
    finally:
        try:os.unlink(name)
        except FileNotFoundError:pass


def status():
    global _STATUS
    with _LOCK:
        if _STATUS is not None:return dict(_STATUS)
        try:
            if os.name!='nt':raise RuntimeError('Available only on Windows.')
            if hashlib.sha256(_BINARY.read_bytes()).hexdigest()!=_EXPECTED:raise RuntimeError('Missing or invalid Microsoft MXC runtime.')
            with tempfile.TemporaryDirectory(prefix='val-isolation-probe-') as folder:
                root=Path(folder);work=root/'work';outside=root/'outside';work.mkdir();outside.mkdir()
                secret=outside/'secret.txt';secret.write_text('VAL_PRIVATE_CANARY',encoding='utf-8')
                command=f'echo VAL_INSIDE>ok.txt\ntype "{secret}"\necho VAL_OUTSIDE>"{outside / "out.txt"}"\nexit /b 0'
                code,out,err=_launch(work,command,15)
                if code!=0 or not (work/'ok.txt').is_file() or 'VAL_PRIVATE_CANARY' in out or (outside/'out.txt').exists():
                    raise RuntimeError('The live filesystem isolation check failed.')
            _STATUS={'available':True,'backend':'mxc-processcontainer','network':'blocked','preview':True}
        except (OSError,ValueError,RuntimeError,subprocess.SubprocessError,TimeoutError) as error:
            _STATUS={'available':False,'backend':'mxc-processcontainer','reason':str(error)[:300],'preview':True}
        return dict(_STATUS)


def run(root,command,shell='cmd',timeout=60,background=False):
    if not isinstance(command,str) or not command.strip() or '\x00' in command or len(command)>30000:raise ValueError('Invalid command.')
    if background:raise ValueError('Background jobs are not supported in isolated mode.')
    if shell!='cmd':raise ValueError('Only CMD is available in isolated mode; PowerShell requires Full PC access.')
    capability=status()
    if not capability['available']:raise RuntimeError('Isolated execution unavailable; command was not run. '+capability.get('reason',''))
    if hashlib.sha256(_BINARY.read_bytes()).hexdigest()!=_EXPECTED:raise RuntimeError('The isolated runtime changed; command was not run.')
    from access_policy import AccessPolicy
    AccessPolicy._check_links(Path(root))
    _scan(root)
    code,out,err=_launch(root,command,max(5,min(int(timeout),300)))
    result=f'exit={code}\nshell={shell}\nisolation=Windows process container (preview); network blocked\n[stdout]\n'+(out.strip() or '(empty)')
    if err.strip():result+='\n[stderr]\n'+err.strip()
    if code:raise RuntimeError(result+_hint(code,err))
    return result
