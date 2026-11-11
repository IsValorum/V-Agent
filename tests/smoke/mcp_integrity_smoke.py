"""Read-only MCP checks and isolated file edits against a chosen packaged core."""
import argparse
import json
import os
from pathlib import Path
import sys
import tempfile

ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT/'agent'),str(ROOT)]
from serve.mcp import McpHub

def main():
    parser=argparse.ArgumentParser();parser.add_argument('core');args=parser.parse_args()
    executable=str(Path(args.core).resolve())
    config=json.loads((ROOT/'data/mcp.json').read_text(encoding='utf8'))['mcpServers']
    with tempfile.TemporaryDirectory(prefix='val-mcp-check-') as directory:
        for server in config.values():
            server['command']=executable;server['cwd']=directory
            server.setdefault('env',{})['STRATA_AGENT_DATA']=directory
        hub=McpHub(config)
        try:
            hub.start(wait=True)
            status=hub.status()
            print(json.dumps({'servers':[(s['name'],s['status'],len(s['tools'])) for s in status['servers']]}),flush=True)
            assert all(s['status']=='ready' for s in status['servers'])
            checks=[('pc__fs_write',{'path':'test.txt','content':'alpha\nbeta\n'}),
                    ('pc__fs_edit',{'path':'test.txt','old_text':'beta','new_text':'edited'}),
                    ('pc__fs_read',{'path':'test.txt'}),
                    ('pc__shell_run',{'command':'echo VAL_ISOLATED_OK'}),
                    ('pc__fs_write',{'path':'check.py','content':'def add(a,b):\n    return a+b\n'}),
                    ('pc__code_check',{'path':'check.py'}),
                    ('pc__fs_write',{'path':'check.js','content':'function add(a,b){ return a+b; }\n'}),
                    ('pc__code_check',{'path':'check.js'}),
                    ('pc__sys_info',{}),('hf__hf_cli',{'args':['version']}),
                    ('admin__status',{}),('computer__window_list',{}),
                    ('web__http_request',{'url':'https://example.com'}),
                    ('duckduckgo__web_visit',{'url':'https://example.com'}),
                    ('duckduckgo__web_search',{'query':'Python official documentation'}),
                    ('duckduckgo__web_search',{'query':'Three.js documentation'}),
                    ('duckduckgo__web_search',{'query':'Windows accessibility keyboard shortcuts'})]
            for name,arguments in checks:
                result=hub.call(name,arguments)
                print(json.dumps({'tool':name,'ok':result['ok'],'ms':result['ms'],'chars':result['chars']}),flush=True)
                if not result['ok']:raise AssertionError(name+': '+result['text'][:500])
                if name=='pc__fs_read':assert result['text']=='alpha\nedited\n'
                if name=='pc__shell_run':assert 'VAL_ISOLATED_OK' in result['text'] and 'isolation=' in result['text']
                if name=='pc__code_check':assert json.loads(result['text'])['verification']['status']=='passed'
                if name=='duckduckgo__web_search':assert json.loads(result['text'])
        finally:hub.close()

if __name__=='__main__':main()
