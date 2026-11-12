"""Run every level of testing and write the results report for this version.

    .venv\\Scripts\\python scripts\\quality\\run_all.py --small-model D:\\models\\small.gguf ^
        --strata-model D:\\models\\lfm2-moe.gguf --rust-model D:\\models\\qwen3-moe.gguf

Runs, in order, and records each check as passed, failed or skipped:

 1. the automatic tests (Python and Node);
 2. static analysis (scripts/quality/static_analysis.py);
 3. the code checker in every language (tests/smoke/language_checks.py);
 4. XSS attacks on the model-card renderer (tests/smoke/xss_model_card.py);
 5. the interface: screen-versus-core consistency, a walk through every window and settings page
    in both themes and at the smallest window, and the repaint probe;
 6. real models on llama.cpp, Strata and Strata Rust (tests/smoke/real_models.py);
 7. the published release on GitHub (scripts/quality/verify_release.py).

The report goes to docs/test-reports/<version>.md, with raw results in build/quality/. Model file
names are left out of the report: it states what was checked, on which engine, and the outcome.
`--skip` leaves out levels by number (for example `--skip 6 7` offline or without a GPU).
"""
import argparse
import json
import os
import platform
import re
import subprocess
import sys
import time
from datetime import date
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
PY = str(ROOT / '.venv' / 'Scripts' / 'python.exe') if (ROOT / '.venv' / 'Scripts' / 'python.exe').exists() else sys.executable
OUT = ROOT / 'build' / 'quality'
sys.path[:0] = [str(ROOT / 'agent'), str(ROOT / 'tests' / 'smoke')]
for stream in (sys.stdout, sys.stderr):
    stream.reconfigure(encoding='utf-8', errors='replace')

LEVELS = {1: 'Automatic tests', 2: 'Static analysis', 3: 'Code checker', 4: 'Untrusted content',
          5: 'Interface', 6: 'Real models', 7: 'Published release'}


class Run:
    def __init__(self, models):
        self.rows, self.models = [], [Path(m) for m in models if m]

    def redact(self, text):
        text = str(text)
        for model in self.models:
            for name in {model.name, model.stem}:
                text = text.replace(name, '‹model›')
        # The architecture in an engine's refusal would name the model too.
        text = re.sub(r'(arquitectura|architecture) «[^»]+»', r'\1 «‹architecture›»', text)
        return re.sub(r'[A-Za-z]:\\Users\\[^\\\s\'"]+', r'%USERPROFILE%', text)

    def add(self, level, rows):
        for row in rows:
            row = dict(row, level=level, detail=self.redact(row.get('detail', '')), check=self.redact(row['check']))
            self.rows.append(row)

    def tool(self, level, name, argv, timeout=3600, env=None):
        """Run a tool that writes its own JSON report; a crash is a failed row with its last lines."""
        report = OUT / f'{name}.json'
        report.unlink(missing_ok=True)
        print(f'\n== [{level}] {name}', flush=True)
        started = time.time()
        result = subprocess.run([PY, *argv, '--report', str(report)], cwd=ROOT, capture_output=True, text=True,
                                encoding='utf-8', errors='replace', timeout=timeout, env={**os.environ, **(env or {})})
        (OUT / f'{name}.log').write_text(result.stdout + result.stderr, encoding='utf-8')
        print(result.stdout[-3000:], flush=True)
        if report.is_file():
            self.add(level, json.loads(report.read_text(encoding='utf-8')))
        else:
            self.add(level, [{'engine': name, 'check': f'{name} ran to the end', 'status': 'fail',
                              'detail': (result.stdout + result.stderr).strip().splitlines()[-1:] or 'no output'}])
        print(f'   ({time.time() - started:.0f} s)')

    def plain(self, level, engine, name, argv, timeout=1800):
        """Run a tool without a JSON report: its exit code is the result."""
        print(f'\n== [{level}] {name}', flush=True)
        result = subprocess.run(argv, cwd=ROOT, capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=timeout)
        output = result.stdout + result.stderr
        (OUT / (re.sub(r'\W+', '-', name).strip('-') + '.log')).write_text(output, encoding='utf-8')
        print(output[-1500:], flush=True)
        self.add(level, [{'engine': engine, 'check': name, 'status': 'pass' if result.returncode == 0 else 'fail',
                          'detail': output.strip().splitlines()[-1] if output.strip() else ''}])
        return output


def unit_tests(run):
    run.plain(1, 'build', 'interface assembles from source', [PY, 'scripts/build-ui.py'])
    output = run.plain(1, 'core', 'Python test suite', [PY, '-m', 'unittest', 'discover', '-s', 'tests'])
    count = re.search(r'Ran (\d+) tests', output)
    if count:
        run.rows[-1]['check'] = f'Python test suite ({count.group(1)} tests)'
    suites = sorted((ROOT / 'tests').glob('*.cjs'))
    failed = []
    for suite in suites:
        result = subprocess.run(['node', str(suite)], cwd=ROOT, capture_output=True, text=True, encoding='utf-8', errors='replace')
        if result.returncode:
            failed.append(suite.name)
    run.add(1, [{'engine': 'interface', 'check': f'Node interface suites ({len(suites)})', 'status': 'fail' if failed else 'pass',
                 'detail': failed or ', '.join(s.stem for s in suites)}])


def interface(run, small_model):
    if small_model:
        run.tool(5, 'ui-consistency', ['tests/smoke/ui_consistency.py', '--model', small_model])
    from isolated_core import IsolatedCore
    with IsolatedCore(19392) as core:
        url = core.base + '/'
        for size, scheme in (('1280x800', 'dark'), ('1280x800', 'light'), ('800x600', 'dark')):
            output = run.plain(5, 'interface', f'walk through every window and settings page at {size}, {scheme} theme',
                               [PY, 'tests/smoke/ui_walkthrough.py', 'tests/smoke/ui_steps.json', '--url', url, '--size', size,
                                '--scheme', scheme, '--out', str(ROOT / 'build' / 'ui-walkthrough' / f'{size}-{scheme}')])
            shots = len(list((ROOT / 'build' / 'ui-walkthrough' / f'{size}-{scheme}').glob('*.png')))
            run.rows[-1]['detail'] = f'{shots} screenshots, ' + ('no page errors' if 'Page errors: none' in output else run.rows[-1]['detail'])
        run.plain(5, 'interface', 'repaint probe: no window repaints while idle',
                  [PY, 'tests/smoke/repaint_probe.py', '--url', url, '--idle', '8'])


def write_report(run, args, started):
    import app_updates
    version = app_updates.VERSION
    target = ROOT / 'docs' / 'test-reports' / f'{version}.md'
    target.parent.mkdir(parents=True, exist_ok=True)
    counts = {s: sum(r['status'] == s for r in run.rows) for s in ('pass', 'fail', 'skip')}
    gpu = ''
    try:
        gpu = subprocess.run(['nvidia-smi', '--query-gpu=name,memory.total', '--format=csv,noheader'],
                             capture_output=True, text=True, timeout=10).stdout.strip().splitlines()[0]
    except Exception:
        pass
    mark = {'pass': '✅', 'fail': '❌', 'skip': '⏭️'}
    lines = [f'# V-Agent {version} — test results', '',
             f'Run on {date.today().isoformat()} with `scripts/quality/run_all.py`, from the source of this version '
             '(including any fixes listed as "Unreleased" in the [changelog](../../CHANGELOG.md)), '
             f'in {(time.time() - started) / 60:.0f} minutes. Every check below was executed for this report; '
             'none is copied from an earlier run.', '',
             f'**{counts["pass"]} passed · {counts["fail"]} failed · {counts["skip"]} skipped**', '',
             '| | |', '|---|---|',
             f'| System | {platform.system()} {platform.release()} ({platform.version()}), Python {platform.python_version()} |']
    if gpu:
        lines.append(f'| GPU | {gpu} |')
    lines += ['| Engines | llama.cpp (CUDA), Strata and Strata Rust, as installed by V-Agent |',
              '| Models | Real GGUF models; Mixture-of-Experts models of up to 35B parameters on Strata and Strata Rust |', '']
    for level, title in LEVELS.items():
        rows = [r for r in run.rows if r['level'] == level]
        if not rows:
            if level in args.skip:
                lines += [f'## {level}. {title}', '', '_Not run this time._', '']
            continue
        lines += [f'## {level}. {title}', '', '| | Check | Where | Detail |', '|---|---|---|---|']
        for r in rows:
            detail = r['detail'].replace('|', '\\|').replace('\n', ' ')
            lines.append(f"| {mark[r['status']]} | {r['check'].replace('|', '/')} | {r['engine']} | {detail[:220]} |")
        lines.append('')
    shots = target.parent / version
    captions = {'01-agent-run': 'A real agent run: the model writes a page, checks it, fixes what the sandboxed preview rejects',
                '02-approval': 'The write waits for approval ("Confirm changes" mode)',
                '03-model-window': 'Model window: engine, loaded model and the context the engine really runs with',
                '04-tools-window': 'Tools: agent mode, per-chat sandbox and approvals',
                '05-hugging-face': 'Hugging Face browser: files, sizes and whether each quant fits this PC',
                '06-settings-engines': 'System and engines: hardware detected and the recommended engine build',
                '07-light-theme': 'The same conversation in the light theme'}
    images = sorted(shots.glob('*.png')) if shots.is_dir() else []
    if images:
        lines += ['## The interface of this version', '',
                  f'Taken with `scripts/quality/screenshots.py` from this version\'s interface, with a model loaded on '
                  'llama.cpp and a real request (nothing staged or edited).', '']
        for image in images:
            caption = captions.get(image.stem, image.stem)
            lines += [f'**{caption}**', '', f'![{caption}]({version}/{image.name})', '']
    lines += ['## How to reproduce', '',
              'Each level is a script in this repository; [docs/QUALITY.md](../QUALITY.md) explains them and '
              '[tests/README.md](../../tests/README.md) lists their options. "Skipped" means the check could not be made '
              'on this machine or in this run (for example the model did not try the action); it is never counted as passed.', '']
    target.write_text('\n'.join(lines), encoding='utf-8')
    (OUT / 'results.json').write_text(json.dumps(run.rows, ensure_ascii=False, indent=1), encoding='utf-8')
    print(f'\nReport: {target}\n{counts}')
    return counts


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--small-model', help='small GGUF for llama.cpp (fast agent runs and the interface checks)')
    parser.add_argument('--strata-model', help='GGUF Strata supports')
    parser.add_argument('--rust-model', help='GGUF Strata Rust supports')
    parser.add_argument('--skip', type=int, nargs='*', default=[])
    parser.add_argument('--no-report', action='store_true', help='run only; leave docs/ untouched')
    args = parser.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    run = Run([args.small_model, args.strata_model, args.rust_model])
    started = time.time()
    if 1 not in args.skip:
        unit_tests(run)
    if 2 not in args.skip:
        run.tool(2, 'static', ['scripts/quality/static_analysis.py'])
    if 3 not in args.skip:
        run.tool(3, 'languages', ['tests/smoke/language_checks.py'])
    if 4 not in args.skip:
        run.tool(4, 'xss', ['tests/smoke/xss_model_card.py'])
    if 5 not in args.skip:
        interface(run, args.small_model)
    if 6 not in args.skip:
        for engine, model in (('llama', args.small_model), ('strata', args.strata_model), ('rust', args.rust_model)):
            if model:
                extra = ['--unsupported', args.small_model] if engine != 'llama' and args.small_model else []
                run.tool(6, f'real-{engine}', ['tests/smoke/real_models.py', f'--{engine}', model, *extra], timeout=7200)
    if 7 not in args.skip:
        run.tool(7, 'release', ['scripts/quality/verify_release.py', '--installer'])
    counts = {s: sum(r['status'] == s for r in run.rows) for s in ('pass', 'fail', 'skip')} if args.no_report \
        else write_report(run, args, started)
    sys.exit(1 if counts['fail'] else 0)


if __name__ == '__main__':
    main()
