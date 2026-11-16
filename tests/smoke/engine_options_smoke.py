"""Engine options for real: saved, passed to the engine process, the model still answers, cleared again.

    .venv\\Scripts\\python tests\\smoke\\engine_options_smoke.py --llama small.gguf --strata lfm.gguf --rust qwen-mtp.gguf

For each engine given: the catalog the core offers comes from the installed executable; options are
saved through the same preference call the interface uses (invalid ones are refused); after loading,
the engine process's real command line is read and must carry exactly those flags; a short chat must
still work; after clearing the options and reloading, the flags must be gone (Strata keeps them in its
config file, so this is where a stale flag would stay behind).
"""
import argparse
import sys
import time
import uuid
from pathlib import Path

import psutil

sys.path.insert(0, str(Path(__file__).resolve().parent))
from isolated_core import IsolatedCore  # noqa: E402

PLAN = {
    'llama': ({'flash_attn': 'off', 'threads': 4, 'kv_offload': False, 'warmup': False, 'cache_reuse': 256},
              ['--flash-attn off', '--threads 4', '--no-kv-offload', '--no-warmup', '--cache-reuse 256']),
    'strata': ({'threads': 6, 'kv_whole': True, 'lookup': 8},
               ['--threads 6', '--kv-whole', '--lookup 8']),
    'rust': ({'mtp': 2, 'chunk': 1024, 'threads': 6},
             ['--mtp 2', '--chunk 1024', '--threads 6']),
}


def engine_command(engine):
    """Command line of the process listening on the engine port (Strata runs its server as a child)."""
    port = 19382 if engine == 'strata' else 19383
    for conn in psutil.net_connections('tcp'):
        if conn.laddr and conn.laddr.port == port and conn.status == psutil.CONN_LISTEN and conn.pid:
            # Strata listens in a Python server that starts strata-poly.exe: read the children too.
            try:
                process = psutil.Process(conn.pid)
                return ' '.join(' '.join(p.cmdline()) for p in [process, *process.children(recursive=True)])
            except psutil.Error:
                return ''
    return ''


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    for engine in PLAN:
        parser.add_argument('--' + engine)
    args = parser.parse_args()
    rows = []

    def check(name, ok, detail=''):
        rows.append(ok)
        print(f"  {'OK  ' if ok else 'FAIL'} {name}" + (f' — {str(detail)[:240]}' if detail else ''), flush=True)

    with IsolatedCore(19371, r'%LOCALAPPDATA%\V-Agent-Data') as core:
        for engine, (values, expected) in PLAN.items():
            path = getattr(args, engine)
            if not path:
                continue
            print(f'\n== {engine}', flush=True)
            core.post('/api/harness/configure', {'engine': engine, 'variant': 'cuda'} if engine == 'llama' else {'engine': engine})
            catalog = core.get('/api/harness/engine-options')
            keys = {o['key'] for o in catalog.get('options', [])}
            check(f'{engine}: the catalog comes from the installed engine', catalog.get('engine') == engine and catalog.get('probed')
                  and set(values) <= keys, f"{len(keys)} options")
            model = core.post('/api/models/register', {'path': path}, timeout=900)['model']['id']
            status, _ = core.request('POST', '/api/models/preferences', {'model': model, 'settings': {'engine': {'threads': -1}}})
            check(f'{engine}: an invalid value is refused', status == 400, f'HTTP {status}')
            core.post('/api/models/preferences', {'model': model, 'settings': {'engine': values}})
            started = time.time()
            status, data = core.request('POST', '/api/load', {'model': model, 'context': 8192}, timeout=1800)
            command = engine_command(engine)
            missing = [flag for flag in expected if flag not in command]
            check(f'{engine}: loads with the options on its command line', status == 200 and not missing,
                  (f'{time.time() - started:.0f} s' if not missing else f'missing {missing}; HTTP {status}: {str(data)[:120]}'))
            if status == 200:
                events = core.chat('qa-opts-' + uuid.uuid4().hex[:6], 'Responde solo: listo', model, functions={}, rounds=1, max_tokens=64)
                check(f'{engine}: the model still answers with them', any(e.get('type') == 'done' for e in events),
                      [e.get('type') for e in events][-3:])
            core.request('POST', '/api/unload', {}, timeout=120)
            time.sleep(2)
            core.post('/api/models/preferences', {'model': model, 'settings': {'engine': {key: None for key in values}}})
            status, _ = core.request('POST', '/api/load', {'model': model, 'context': 8192}, timeout=1800)
            command = engine_command(engine)
            left = [flag for flag in expected if flag in command]
            check(f'{engine}: cleared options are gone after reloading', status == 200 and not left, left or 'none left')
            core.request('POST', '/api/unload', {}, timeout=120)
            time.sleep(2)
    print(f'\n{len(rows)} checks, {rows.count(False)} failed')
    sys.exit(0 if all(rows) else 1)


if __name__ == '__main__':
    main()
