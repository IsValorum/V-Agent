"""Watch the context meter's data source while a real model thinks and uses tools.

    .venv\\Scripts\\python tests\\smoke\\live_context_probe.py --engine llama --model D:\\models\\small.gguf

Starts an isolated core, sends a request that needs several tool calls, and polls
/api/context/usage (what the interface polls) every 0.3 s. It prints a timeline of the values and of
the reply's phases (thinking, text, tool call, tool result) and checks that the count moves during
each phase, as it does in the stream, instead of standing still until a round ends.
Exit code 1 when the count is missing once the reply started, never went live, or stood still for
more than 10 s (engines without progress reports, like Strata Rust, are still while reading a prompt).
"""
import argparse
import json
import sys
import threading
import time
import urllib.request
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from isolated_core import IsolatedCore  # noqa: E402

REQUEST = ('Crea tres archivos: uno.txt con el texto 1, dos.txt con el texto 2 y tres.txt con el texto 3. '
           'Después lee los tres y dime cuánto suman los números.')


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--engine', choices=('llama', 'strata', 'rust'), required=True)
    parser.add_argument('--model', required=True)
    parser.add_argument('--effort', default='medium', help='reasoning effort sent with the request')
    parser.add_argument('--engines-from', default=r'%LOCALAPPDATA%\V-Agent-Data')
    args = parser.parse_args()
    with IsolatedCore(19399, args.engines_from) as core:
        core.post('/api/harness/configure', {'engine': args.engine, 'variant': 'cuda'} if args.engine == 'llama' else {'engine': args.engine})
        model = core.post('/api/models/register', {'path': args.model}, timeout=900)['model']['id']
        core.post('/api/load', {'model': model, 'context': 8192}, timeout=1800)
        conversation = 'qa-live-' + uuid.uuid4().hex[:8]
        phases, samples, done = [], [], threading.Event()
        start = time.time()

        def stream():
            body = {'model': model, 'conversation_id': conversation, 'messages': [{'role': 'user', 'content': REQUEST}],
                    'functions': {'files': True}, 'effort': args.effort, 'sampling': {'temperature': 0, 'max_tokens': 3000},
                    'rounds': 10, 'agent_profile': 'balanced', 'permission_mode': 'run'}
            request = urllib.request.Request(core.base + '/api/chat', json.dumps(body).encode(),
                                             {'Content-Type': 'application/json', 'Origin': core.base})
            with urllib.request.urlopen(request, timeout=900) as response:
                for line in response:
                    if line.startswith(b'data: '):
                        try:
                            event = json.loads(line[6:])
                        except ValueError:
                            continue
                        kind = event.get('type')
                        if not phases or phases[-1][1] != kind:
                            phases.append((round(time.time() - start, 2), kind))
            done.set()

        threading.Thread(target=stream, daemon=True).start()
        while not done.is_set() and time.time() - start < 600:
            data = core.get('/api/context/usage', timeout=5)
            usage = data.get('usage') or {}
            samples.append((round(time.time() - start, 2), usage.get('used'), usage.get('source')))
            time.sleep(.3)
    # Timeline: phase changes and the count at that moment.
    print('phases:', ' → '.join(f'{t}s {k}' for t, k in phases if k in ('reasoning', 'content', 'tool', 'tool_result', 'done')))
    changes = [(t, u, s) for i, (t, u, s) in enumerate(samples) if i == 0 or u != samples[i - 1][1]]
    print('count changes:', ', '.join(f'{t}s={u}({s})' for t, u, s in changes))
    live = any(s == 'live' for _, _, s in samples)
    # Longest stretch without a change while the reply was running.
    longest, last_t, last_u = 0.0, samples[0][0] if samples else 0, None
    for t, u, _ in samples:
        if u != last_u:
            last_t, last_u = t, u
        longest = max(longest, t - last_t)
    # Between the first and the last live sample: before the round starts and after the reply ends
    # the core has no run to report, by design.
    live_at = [i for i, (_, _, src) in enumerate(samples) if src == 'live']
    inside = samples[live_at[0]:live_at[-1] + 1] if live_at else []
    gaps = sum(u is None for _, u, _ in inside)
    print(f'live samples: {live}; samples without a value during the reply: {gaps}; longest stretch without a change: '
          f'{longest:.1f} s over {samples[-1][0] if samples else 0:.0f} s')
    # Strata Rust sends nothing while it reads a prompt or drafts a tool call, so a few seconds
    # without a change are expected there; a value must still be there all the time.
    sys.exit(0 if live and not gaps and longest <= 10.0 else 1)


if __name__ == '__main__':
    main()
