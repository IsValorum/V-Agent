"""Do V-Agent's MCP servers recover when a call fails?

    .venv\\Scripts\\python tests\\smoke\\mcp_recovery.py

Starts the real tool servers (the same hub the core uses, in a throw-away data folder) and, for each
server: sends calls that must fail (unknown tool, wrong or missing arguments, a path outside the
sandbox, a missing file) and checks that each one comes back as a clear error result, that the server
is still alive and that a correct call right after works. Then it kills each server process and checks
that the next call starts it again by itself. Exit code 1 if any server does not recover.
"""
import json
import os
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for stream in (sys.stdout, sys.stderr):
    stream.reconfigure(encoding='utf-8', errors='replace')
os.environ['STRATA_AGENT_DATA'] = tempfile.mkdtemp(prefix='va-mcp-recovery-')
sys.path[:0] = [str(ROOT / 'agent'), str(ROOT), str(ROOT / 'tools')]

rows = []


def check(name, ok, detail=''):
    rows.append((name, ok))
    print(f"  {'OK  ' if ok else 'FAIL'} {name}" + (f' — {str(detail)[:220]}' if detail else ''), flush=True)


def call(hub, name, args):
    server, tool = hub.routes()[name]
    try:
        result = server.call(tool, args, 60)
        text = __import__('serve.mcp', fromlist=['result_text']).result_text(result)
        return (not result.get('isError'), text)
    except Exception as error:  # an exception instead of an error result
        return (None, f'{type(error).__name__}: {error}')


# Per server: calls that must fail, then a correct one that must work.
CASES = {
    'pc': ([('pc__fs_read', {'path': 'no-existe.txt'}), ('pc__fs_read', {}), ('pc__fs_write', {'path': 'C:/Windows/x.txt', 'content': 'x'}),
            ('pc__fs_edit', {'path': 'nada.txt', 'old_text': 'a', 'new_text': 'b'}), ('pc__fs_list', {'path': '../..'}),
            ('pc__code_check', {'path': 'falta.py'}), ('pc__file_history', {'path': 'falta.txt', 'revision': 'x'})],
           ('pc__fs_write', {'path': 'ok.txt', 'content': 'hola'})),
    'hf': ([('hf__hf_cli', {'args': '--no-existe'}), ('hf__hf_transfer', {})], ('hf__hf_account', {})),
    'duckduckgo': ([('duckduckgo__web_visit', {'url': 'notaurl'}), ('duckduckgo__web_visit', {})], None),
    'web': ([('web__http_request', {'url': 'file:///C:/Windows/win.ini'}), ('web__http_request', {})], None),
    'autobrowser': ([('autobrowser__click', {'selector': '#nada'}), ('autobrowser__navigate', {'url': 'javascript:alert(1)'})],
                    ('autobrowser__tabs', {})),
    'admin': ([('admin__run', {'command': ''})], ('admin__status', {})),  # stop is idempotent: nothing to fail
    'computer': ([('computer__mouse_click', {'x': 'a'}), ('computer__window_focus', {'title': 'ventana-que-no-existe-xyz'})], ('computer__window_list', {})),
}


def main():
    from runtime_paths import bootstrap
    bootstrap()  # the starting files a real start-up creates (mcp.json…)
    import agent
    hub = agent.create_agent_hub()
    hub.start(wait=True)
    status = {s['name']: s['status'] for s in hub.status()['servers']}
    print('servers:', status)
    for name, (bad, good) in CASES.items():
        server = hub.servers.get(name)
        if not server or server.status != 'ready':
            check(f'{name}: starts', False, server.error if server else 'not configured')
            continue
        routes = hub.routes()
        for tool, args in bad:
            if tool not in routes:
                check(f'{name}: {tool} exists', False, 'tool not offered')
                continue
            ok, text = call(hub, tool, args)
            reported = ok is False or (ok is True and (text.lower().startswith('error') or '"ok": false' in text))
            check(f'{name}: {tool}({json.dumps(args)[:60]}) fails as a clear error result', reported and len(text.strip()) > 12, text[:160])
            alive = server.transport is not None and server.transport.alive()
            if not alive:
                check(f'{name}: alive after the failed call', False, 'server process ended')
        if good:
            ok, text = call(hub, *good)
            check(f'{name}: a correct call works after the failures', ok is True and not text.lower().startswith('error:'), text[:120])
        # Crash the server: the next call must start it again.
        proc = getattr(server.transport, 'process', None) or getattr(server.transport, 'proc', None)
        if proc is not None:
            proc.kill(); proc.wait(10); time.sleep(.5)
            probe = good or bad[0]
            ok, text = call(hub, *probe)
            check(f'{name}: restarts by itself after its process dies', ok is not None and server.transport.alive(), text[:120])
    failed = [n for n, ok in rows if not ok]
    print(f'\n{len(rows)} checks, {len(failed)} failed')
    for s in hub.servers.values():
        s.close()
    sys.exit(1 if failed else 0)


if __name__ == '__main__':
    main()
