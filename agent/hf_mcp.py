"""Local HF MCP using the official CLI/SDK; no shell, token exposure or engine dependencies."""
import json
import os
from pathlib import Path
import re
import secrets
import subprocess
import sys
from huggingface_hub import HfApi,get_token,hf_hub_download,snapshot_download
from mcp_options import options
from access_policy import AccessPolicy,AccessDenied,workspace_signature

for stream in (sys.stdin,sys.stdout,sys.stderr):
    if hasattr(stream,'reconfigure'):stream.reconfigure(encoding='utf-8')
POLICY=AccessPolicy()
CLI=Path(sys.executable).with_name('hf.exe' if os.name=='nt' else 'hf')
ALLOWED={
 'repos':{'list','ls','create','delete','delete-files','duplicate','move','settings','branch','tag'},
 'models':{'list','ls','info','card'},'datasets':{'list','ls','info','card','leaderboard','parquet'},
 'spaces':{'list','ls','info','card','logs','pause','restart','search','templates','wait'},
 'collections':{'list','ls','info','create','update','delete','add-item','update-item','delete-item'},
 'discussions':{'list','ls','info','diff','create','comment','edit','close','reopen','rename','merge'},
 'auth':{'whoami'},'version':set(),
}
TOOLS=[
 {'name':'hf_account','description':'Read the authenticated HF username and organizations. Never returns tokens.','inputSchema':{'type':'object','properties':{}}},
 {'name':'hf_cli','description':'Official HF CLI for repository, model, dataset, Space, collection and discussion management. args omit hf. Use --help to inspect exact syntax. Use hf_transfer for local uploads/downloads. Never use auth token/login/logout.','inputSchema':{'type':'object','properties':{'args':{'type':'array','items':{'type':'string'}},'timeout':{'type':'integer','minimum':5,'maximum':300}},'required':['args']}},
 {'name':'hf_transfer','description':'Upload/download HF files or folders. path is a local conversation-relative source or destination; full-PC mode permits other paths. filename selects a remote file for download.','inputSchema':{'type':'object','properties':{'action':{'type':'string','enum':['upload','download']},'repo_id':{'type':'string'},'path':{'type':'string'},'filename':{'type':'string'},'repo_type':{'type':'string','enum':['model','dataset','space']},'revision':{'type':'string'},'message':{'type':'string'}},'required':['action','repo_id','path']}}
]

def redact(value):
    text=str(value);token=get_token()
    if token:text=text.replace(token,'[REDACTED]')
    # Preserve bundled tool identifiers like hf_transfer while masking real HF tokens.
    return re.sub(r'hf_(?!transfer\b|account\b|cli\b)[A-Za-z0-9]{8,}','[REDACTED]',text)

def _normalize_cli_args(args):
    if isinstance(args,list) and args and isinstance(args[0],str) and args[0].strip().lower() in ('hf','hf.exe'):
        return args[1:]
    return args

def validate_cli(args, full_access=False):
    args=_normalize_cli_args(args)
    if not isinstance(args,list) or not args or len(args)>100 or any(not isinstance(x,str) or '\x00' in x for x in args):raise ValueError("args must be a nonempty string array (subcommand only, e.g. ['models','ls'] or ['--help']).")
    if any(x.split('=')[0] in ('--token','--hf-token','--access-token','--explore') for x in args):raise AccessDenied('Use cached local authentication; token arguments are blocked.')
    if args==['--help']:return
    group=args[0]
    if group not in ALLOWED:raise AccessDenied('This command is outside HF profile/repository management. Use hf_transfer for files.')
    if len(args)==1 or args[1] in ('--help','-h'):return
    if args[1] not in ALLOWED[group]:raise AccessDenied('Unsupported HF subcommand; inspect the group with --help.')
    if group=='auth' and args[1:]!=['whoami'] and '--help' not in args:raise AccessDenied('Only auth whoami is exposed; token and login management stay outside the model.')
    if group=='discussions' and args[1] not in ('list','ls','info','diff') and not full_access:raise AccessDenied('Discussion writes can read local attachments. Enable full-PC access explicitly for this CLI operation.')
    if not full_access and any(x.split('=')[0] in ('--body-file','--file','--output','--output-file','--local-dir','--cache-dir') or x.startswith('@') for x in args):raise AccessDenied('Local file options require full-PC mode. Use hf_transfer for scoped files.')

def call(name,args,policy=POLICY,full_access=False):
    if name=='hf_account':
        if not get_token():return {'authenticated':False,'note':'Run the dedicated HF CLI auth login outside the model.'}
        try:data=HfApi().whoami()
        except Exception as error:
            if 'Invalid user token' in str(error) or '401' in str(error):
                return {'authenticated':False,'token_invalid':True,'note':'The local HF_TOKEN environment variable or cached token is invalid or expired. Public queries and downloads still work without authentication; for private access or uploads, update HF_TOKEN or run hf auth login outside the model.'}
            raise
        return {'authenticated':True,'username':data.get('name'),'organizations':[org['name'] for org in data.get('orgs',[])],
                'token_role':(data.get('auth') or {}).get('accessToken',{}).get('role')}
    if name=='hf_cli':
        argv=_normalize_cli_args(args.get('args'));validate_cli(argv,full_access)
        timeout=max(5,min(300,int(args.get('timeout') or options('hf')['command_timeout'])))
        cmd=__import__('runtime_paths').command('hf-cli',*argv)
        flags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0
        process=subprocess.run(cmd,cwd=policy.root,stdin=subprocess.DEVNULL,capture_output=True,text=True,
                               encoding='utf-8',errors='replace',timeout=timeout,creationflags=flags)
        output=redact(process.stdout+process.stderr)
        if process.returncode and 'Invalid user token' in output and argv[:1]!=['auth']:
            anon_env={k:v for k,v in os.environ.items() if k not in ('HF_TOKEN','HUGGING_FACE_HUB_TOKEN')}
            anon_env['HF_HUB_DISABLE_IMPLICIT_TOKEN']='1'
            process=subprocess.run(cmd,cwd=policy.root,stdin=subprocess.DEVNULL,capture_output=True,text=True,
                                   encoding='utf-8',errors='replace',timeout=timeout,env=anon_env,creationflags=flags)
            output=redact(process.stdout+process.stderr)
        cap=options('hf')['max_result_chars']
        if process.returncode:raise ValueError('HF CLI exit '+str(process.returncode)+': '+output[:cap])
        return output[:cap]+('\n[Output truncated; narrow the query.]' if len(output)>cap else '')
    if name=='hf_transfer':
        path=policy.path(args.get('path'),full_access);kind=args.get('repo_type') or 'model'
        if kind not in ('model','dataset','space'):raise ValueError('Invalid repo_type.')
        repo_id=str(args.get('repo_id') or '').strip()
        if not repo_id or repo_id.startswith(('http://','https://')) or ' ' in repo_id:
            raise ValueError("repo_id must be 'owner/name' (not a full URL), e.g. 'org/model'.")
        common={'repo_id':repo_id,'repo_type':kind,'revision':args.get('revision') or 'main'}
        if args['action']=='download':
            path.mkdir(parents=True,exist_ok=True)
            # Refuse existing links/junctions before the SDK writes into a directory.
            for parent,dirs,files in os.walk(path,followlinks=False):
                for item in dirs+files:policy._check_links(Path(parent)/item)
            for token in (None,False):
                call_args={**common,**({'token':False} if token is False else {})}
                try:
                    result=hf_hub_download(**call_args,filename=args['filename'],local_dir=path) if args.get('filename') else snapshot_download(**call_args,local_dir=path)
                    return {'downloaded':str(result)}
                except Exception as error:
                    if token is None and ('Invalid user token' in str(error) or '401' in str(error)):continue
                    raise
        if args['action']!='upload':raise ValueError('Invalid action.')
        if not path.exists():raise ValueError('Local source does not exist.')
        api=HfApi();common['commit_message']=args.get('message') or 'Upload from V-Agent'
        if path.is_dir():
            for parent,dirs,files in os.walk(path,followlinks=False):
                for item in dirs+files:policy._check_links(Path(parent)/item)
            result=api.upload_folder(**common,folder_path=path,path_in_repo=args.get('filename') or '')
        else:result=api.upload_file(**common,path_or_fileobj=path,path_in_repo=args.get('filename') or path.name)
        return {'commit':str(result)}
    raise ValueError('Unknown HF tool.')

def execute_request(params):
    try:
        args = dict(params.get('arguments') or {})
        expected = os.environ.get('STRATA_PC_ACCESS_KEY', '')
        key = args.pop('_pc_access_key', '')
        ticket = args.pop('_pc_workspace', None)
        full = bool(expected and isinstance(key, str) and secrets.compare_digest(expected, key))
        policy = POLICY
        if ticket is not None:
            if not expected or not isinstance(ticket, dict) or not secrets.compare_digest(str(ticket.get('signature','')), workspace_signature(expected, ticket.get('id'))):
                raise AccessDenied('Unauthorized workspace.')
            from projects import PROJECTS
            policy = PROJECTS.workspace(POLICY,ticket['id'])
        value = call(params.get('name'), args, policy, full)
        text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
        return {'content':[{'type':'text','text':redact(text)}]}
    except Exception as error:
        return {'isError':True,'content':[{'type':'text','text':redact(error)}]}


def main():
    from stdio_worker import serve
    serve(__file__, TOOLS, 'huggingface-local', '1.1', timeout=890,persistent=True)


if __name__ == '__main__':
    if '--mcp-worker' in sys.argv:
        from stdio_worker import serve_worker
        serve_worker(execute_request)
    else:
        main()
