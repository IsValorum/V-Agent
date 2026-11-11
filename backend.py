"""One executable entry point for the API, owned engine server and bundled MCPs."""
import os
from pathlib import Path
import sys

ROOT=Path(getattr(sys,'_MEIPASS',Path(__file__).resolve().parent))
sys.path[:0]=[str(ROOT/'agent'),str(ROOT/'tools'),str(ROOT/'web_mcp'),str(ROOT)]

def main():
    import argparse
    parser=argparse.ArgumentParser();parser.add_argument('--role',default='agent');parser.add_argument('--port',type=int,default=19380);parser.add_argument('--data-dir')
    args,rest=parser.parse_known_args()
    if args.data_dir:os.environ['STRATA_AGENT_DATA']=args.data_dir
    rest=rest[1:] if rest and rest[0]=='--' else rest
    from runtime_paths import bootstrap,LOG_ROOT
    # Signed minor updates (MCP servers, tool descriptions): verified again at every start.
    import components
    components.enable_overlay()
    if args.role=='agent':bootstrap()
    sys.argv=[sys.argv[0],*rest]
    if args.role=='agent':
        os.environ['STRATA_HARNESS_PORT']=str(args.port)
        stream=open(LOG_ROOT/'agent.log','a',encoding='utf8',buffering=1);sys.stdout=sys.stderr=stream
        import agent,desktop_runtime
        desktop_runtime.install(agent)
        agent.main()
    elif args.role=='strata-server':
        from serve.server import main as run
        run()
    elif args.role in ('pc','hf'):
        import importlib
        module=importlib.import_module('pc_mcp' if args.role=='pc' else 'hf_mcp')
        if '--mcp-worker' in rest:
            from stdio_worker import serve_worker
            serve_worker(module.execute_request)
        else:module.main()
    elif args.role=='web':
        from buscador_mcp import mcp
        mcp.run()
    elif args.role=='webtools':
        from http_tools_mcp import mcp
        mcp.run()
    elif args.role=='autobrowser':
        import browser_mcp
        browser_mcp.mcp.run()
    elif args.role=='admin':
        import admin_mcp
        admin_mcp.mcp.run()
    elif args.role=='computer':
        import computer_mcp
        computer_mcp.mcp.run()
    elif args.role=='admin-helper':
        import admin_helper
        admin_helper.main()
    elif args.role=='hf-cli':
        from huggingface_hub.cli.hf import main as run
        run()
    elif args.role=='pick':
        import runpy
        runpy.run_path(str(ROOT/'agent/pick_model_file.py'),run_name='__main__')
    else:raise SystemExit('Unknown process role')

if __name__=='__main__':main()
