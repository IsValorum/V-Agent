"""Project-aware checks. Discovery never executes project code or installs tools."""
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import time


def plans(path,root_limit=None):
    path=Path(path).absolute();root=path if path.is_dir() else path.parent;checks=[]
    if path.is_file():
        markers=('package.json','pyproject.toml','Cargo.toml','go.mod','pom.xml','CMakeLists.txt','Makefile','build.gradle','.strata/checks.json')
        for candidate in (root,*list(root.parents)[:6]):
            if root_limit and not candidate.is_relative_to(Path(root_limit).absolute()):break
            if any((candidate/name).is_file() for name in markers):root=candidate;break
    if root_limit:
        from access_policy import AccessPolicy
        for name in ('package.json','tsconfig.json','pyproject.toml','pytest.ini','Cargo.toml','go.mod','pom.xml','CMakeLists.txt','Makefile','.strata/checks.json'):
            AccessPolicy._check_links(root/name)
    def add(key,argv,kind='project'):
        argv=list(argv)
        if not os.path.isabs(argv[0]) and ('/' in argv[0] or '\\' in argv[0]):argv[0]=str(root/argv[0])
        executable=shutil.which(argv[0])
        checks.append({'id':key,'command':argv,'available':bool(executable),'kind':kind})
    if path.is_file():
        commands={'.php':['php','-l'],'.rb':['ruby','-c'],'.sh':['bash','-n'],'.ps1':[],
                  '.c':['clang','-fsyntax-only'],'.cpp':['clang++','-fsyntax-only'],'.cc':['clang++','-fsyntax-only']}
        if path.suffix in commands and commands[path.suffix]:add('syntax',commands[path.suffix]+[os.path.relpath(path,root)],'syntax')
    if (root/'package.json').is_file():
        try:
            package=json.loads((root/'package.json').read_text(encoding='utf-8-sig'))
            for name in ('lint','typecheck','check','test','build'):
                if name in package.get('scripts',{}):add(name,['npm','run',name])
        except (ValueError,OSError):pass
        if (root/'tsconfig.json').is_file() and not any(c['id']=='typecheck' for c in checks):
            exe=root/'node_modules/typescript/bin/tsc'
            if exe.is_file():add('typecheck',['node',str(exe),'--noEmit','--pretty','false'])
    if (root/'Cargo.toml').is_file():
        add('check',['cargo','check','--offline']);add('test',['cargo','test','--offline'])
    if (root/'go.mod').is_file():
        add('check',['go','vet','./...']);add('test',['go','test','./...'])
    if any(root.glob('*.csproj')) or any(root.glob('*.sln')):add('build',['dotnet','build','--no-restore','--nologo'])
    if (root/'pom.xml').is_file():add('test',['mvn','--offline','test'])
    if (root/'CMakeLists.txt').is_file() and (root/'build/CMakeCache.txt').is_file():add('build',['cmake','--build','build','--parallel','2'])
    if (root/'Makefile').is_file():add('build-plan',['make','-n'],'dry-run')
    if (root/'pyproject.toml').is_file() or (root/'pytest.ini').is_file():
        add('lint',['ruff','check','.']);add('test',['pytest','-q'])
    custom=root/'.strata/checks.json'
    if custom.is_file():
        if custom.stat().st_size>32768:raise ValueError('Project check configuration exceeds 32 KB.')
        data=json.loads(custom.read_text(encoding='utf-8-sig'))
        if not isinstance(data,dict) or not isinstance(data.get('checks'),list):raise ValueError('Project configuration requires a checks array.')
        if len(data['checks'])>24:raise ValueError('At most 24 project checks are supported.')
        for item in data['checks']:
            if not isinstance(item,dict):raise ValueError('Each check must be an object with id and command.')
            key=item.get('id');argv=item.get('command')
            if not isinstance(key,str) or not re.fullmatch(r'[a-zA-Z0-9_.-]{1,48}',key):raise ValueError('Invalid check ID.')
            if not isinstance(argv,list) or not 1<=len(argv)<=64 or not all(isinstance(x,str) and x and '\0' not in x for x in argv):raise ValueError('Checks require a command argument array.')
            checks=[c for c in checks if c['id']!=key];add(key,argv,'custom')
    return root,checks


def inspect(path,run=False,check=None,full_access=False,timeout=60,root_limit=None):
    root,checks=plans(path,root_limit)
    result={'root':str(root),'checks':checks,'executed':False,'coverage':'Syntax, configured static checks and project tests are separate; none guarantees semantic or visual correctness.'}
    if not run:return result
    if not full_access:raise PermissionError('Project commands require Toda la PC. Syntax checks remain available without it.')
    plan=next((c for c in checks if c['id']==check),None)
    if not plan:raise ValueError('Choose a listed check ID; inspect the project first.')
    if not plan['available']:raise ValueError('Required tool is not installed: '+plan['command'][0])
    seconds=max(1,min(120,int(timeout)));started=time.perf_counter()
    with tempfile.TemporaryDirectory(prefix='strata-diagnostic-') as folder:
        out=Path(folder)/'stdout';err=Path(folder)/'stderr'
        with out.open('wb') as stdout,err.open('wb') as stderr:
            process=subprocess.Popen(plan['command'],cwd=root,stdout=stdout,stderr=stderr,stdin=subprocess.DEVNULL,
                creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0),env={**os.environ,'NO_COLOR':'1','CI':'1','GOTOOLCHAIN':'local','GOPROXY':'off'})
            try:code=process.wait(timeout=seconds)
            except subprocess.TimeoutExpired:
                if os.name=='nt':subprocess.run(['taskkill','/F','/T','/PID',str(process.pid)],capture_output=True,creationflags=subprocess.CREATE_NO_WINDOW,timeout=15)
                else:
                    import psutil
                    for child in psutil.Process(process.pid).children(recursive=True):child.kill()
                    process.kill()
                process.wait(timeout=10);code=None
        def read(file):
            with file.open('rb') as stream:return stream.read(16000).decode('utf-8',errors='replace')
        result.update(executed=True,check=check,exit_code=code,ok=code==0,timed_out=code is None,
            stdout=read(out),stderr=read(err),truncated=out.stat().st_size>16000 or err.stat().st_size>16000,
            elapsed_ms=round((time.perf_counter()-started)*1000))
    return result
