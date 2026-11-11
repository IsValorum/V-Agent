"""Exercise the installed MCP executables, including extractor data files.

Run after packaging: .venv/Scripts/python tests/mcp_bundle_smoke.py [--search]
Uses public example.com and, optionally, a public documentation search.
Never authenticates, modifies HF content, or loads a model.
"""
import argparse
import json
import os
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'agent'),str(ROOT)]
os.environ.setdefault('STRATA_AGENT_DATA',str(ROOT/'data'))
from serve.mcp import hub_from_config

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--config',default=str(ROOT/'data/mcp.json'))
    parser.add_argument('--search',action='store_true')
    args=parser.parse_args()
    hub=hub_from_config({},args.config)
    calls=[('pc__sys_info',{}),('hf__hf_cli',{'args':['version']}),
           ('duckduckgo__web_visit',{'url':'https://example.com'})]
    if args.search:calls.append(('duckduckgo__web_search',{'query':'Python official documentation'}))
    failures=[]
    try:
        hub.start(wait=True)
        for name,arguments in calls:
            result=hub.call(name,arguments)
            print(json.dumps({'tool':name,'ok':result['ok'],'ms':result['ms'],'chars':result['chars']}))
            if not result['ok']:failures.append(name+': '+result['text'][:300])
            elif name.endswith('web_visit'):
                page=json.loads(result['text'])
                if not page.get('content') or page.get('url')!='https://example.com':failures.append('Invalid public page result.')
            elif name.endswith('web_search'):
                results=json.loads(result['text'])
                if not results or any(not r.get('link','').startswith('http') for r in results):failures.append('Search returned no public links.')
    finally:hub.close()
    if failures:raise SystemExit('\n'.join(failures))

if __name__=='__main__':main()
