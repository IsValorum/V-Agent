"""Static analysis of the whole code base, with the exact rules used for each release.

    .venv\\Scripts\\python scripts\\quality\\static_analysis.py [--report build\\quality\\static.json]

- ruff over all Python: undefined or shadowed names, unused results, bugbear and pylint error
  classes (`--select F,E9,B,PLE`, minus purely stylistic codes).
- bandit over the core, medium and high severity. Every finding was reviewed by hand and is listed
  with its reason in bandit-reviewed.json; anything new fails until it is reviewed.
- ESLint over the assembled interface (agent/ui/dist): the inline scripts and assets. ESLint is
  first run on eslint-seeded.js, which has deliberate faults, to prove the rules fire.
- Every tracked text file is scanned for stray control characters (they slip in through
  copy-paste or shell quoting and break code silently).

Tools: `pip install ruff==0.17.4 bandit==1.9.4` (or set V_AGENT_LINT_BIN to the folder holding
them) and `npm install --prefix build\\eslint eslint@9.39.1 globals@15.15.0` (or set
V_AGENT_ESLINT_DIR). A tool that is missing is reported as skipped, never as passed.
"""
import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
PYTHON_TARGETS = ['agent', 'backend.py', 'tools', 'web_mcp', 'scripts', 'tests']
RUFF_SELECT = 'F,E9,B,PLE'
# Style-only or intentional patterns in this code base (re-exports, lambdas, loop closures read at once…).
RUFF_IGNORE = 'F401,F541,E731,B008,B905,B006,B007,B904,B023,B017,B028,B009,B010'
CONTROL = re.compile(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]')
TEXT = {'.py', '.js', '.cjs', '.mjs', '.css', '.html', '.json', '.md', '.toml', '.yml', '.yaml', '.cmd', '.ps1', '.rs', '.txt'}

for stream in (sys.stdout, sys.stderr):
    stream.reconfigure(encoding='utf-8', errors='replace')
rows = []


def record(name, status, detail=''):
    rows.append({'engine': 'static analysis', 'check': name, 'status': status, 'detail': str(detail)[:400]})
    print(f"  {({'pass': 'OK     ', 'fail': 'FAIL   ', 'skip': 'SKIPPED'})[status]} {name}" + (f' — {detail}' if detail else ''))


def tool(name):
    folder = os.environ.get('V_AGENT_LINT_BIN')
    if folder:
        for candidate in (Path(folder) / (name + '.exe'), Path(folder) / name):
            if candidate.is_file():
                return str(candidate)
    return shutil.which(name)


def ruff():
    exe = tool('ruff')
    if not exe:
        return record('ruff', 'skip', 'ruff not installed')
    version = subprocess.run([exe, '--version'], capture_output=True, text=True).stdout.strip()
    result = subprocess.run([exe, 'check', '--no-cache', '--output-format', 'concise', '--select', RUFF_SELECT,
                             '--ignore', RUFF_IGNORE, *PYTHON_TARGETS], cwd=ROOT, capture_output=True, text=True)
    findings = [line for line in result.stdout.splitlines() if re.match(r'.+:\d+:\d+: ', line)]
    record(f'ruff ({version}) on all Python', 'pass' if result.returncode == 0 else 'fail',
           f'{len(findings)} findings' + (': ' + ' | '.join(findings[:5]) if findings else ''))


def bandit():
    exe = tool('bandit')
    if not exe:
        return record('bandit', 'skip', 'bandit not installed')
    result = subprocess.run([exe, '-q', '-r', 'agent', 'backend.py', 'tools', 'web_mcp', 'scripts', '-ll', '-f', 'json',
                             '-x', 'agent/ui'], cwd=ROOT, capture_output=True, text=True)
    found = Counter((r['test_id'], r['filename'].replace('\\', '/')) for r in json.loads(result.stdout)['results'])
    reviewed = {(r['test'], r['file']): r['count'] for r in json.loads((HERE / 'bandit-reviewed.json').read_text(encoding='utf-8'))['reviewed']}
    new = {f'{test} {file}': count - reviewed.get((test, file), 0) for (test, file), count in found.items()
           if count > reviewed.get((test, file), 0)}
    record(f'bandit (medium and high) on the core: {sum(found.values())} findings, all reviewed', 'fail' if new else 'pass',
           f'not reviewed: {new}' if new else f'{len(reviewed)} reviewed groups in bandit-reviewed.json')


def eslint():
    folder = Path(os.environ.get('V_AGENT_ESLINT_DIR') or ROOT / 'build' / 'eslint')
    cli = folder / 'node_modules' / 'eslint' / 'bin' / 'eslint.js'
    node = shutil.which('node')
    if not (cli.is_file() and node):
        return record('ESLint', 'skip', 'ESLint not installed (see this file\'s help)')
    dist = ROOT / 'agent' / 'ui' / 'dist'
    work = folder / 'v-agent-input'
    shutil.rmtree(work, ignore_errors=True)
    work.mkdir(parents=True)
    page = (dist / 'v-agent.html').read_text(encoding='utf-8')
    inline = [m.group(2) for m in re.finditer(r'<script(\s[^>]*)?>(.*?)</script>', page, re.S)
              if 'src=' not in (m.group(1) or '') and 'json' not in (m.group(1) or '')]
    (work / 'v-agent-inline.js').write_text('\n;\n'.join(inline), encoding='utf-8')
    for asset in (dist / 'assets').glob('*.js'):
        shutil.copy2(asset, work / asset.name)
    shutil.copy2(HERE / 'eslint-seeded.js', folder / 'eslint-seeded.js')
    shutil.copy2(HERE / 'eslint.config.mjs', folder / 'v-agent.eslint.config.mjs')

    def lint(target):
        result = subprocess.run([node, str(cli), '-c', 'v-agent.eslint.config.mjs', '--format', 'json', target],
                                cwd=folder, capture_output=True, text=True, encoding='utf-8')
        return [(Path(f['filePath']).name, m['line'], m.get('ruleId'), m['message']) for f in json.loads(result.stdout or '[]')
                for m in f['messages'] if m['severity'] == 2]

    version = subprocess.run([node, str(cli), '--version'], cwd=folder, capture_output=True, text=True).stdout.strip()
    seeded = {rule for _, _, rule, _ in lint('eslint-seeded.js')}
    expected = {'no-undef', 'valid-typeof', 'no-cond-assign'}
    record('ESLint rules fire on deliberate faults', 'pass' if expected <= seeded else 'fail', f'reported {sorted(seeded)}')
    errors = lint('v-agent-input')
    record(f'ESLint ({version}) on the assembled interface ({len(inline)} inline scripts + assets)',
           'fail' if errors else 'pass', f'{len(errors)} errors' + (': ' + ' | '.join(f'{f}:{l} {r}' for f, l, r, _ in errors[:5]) if errors else ''))


def control_characters():
    files = subprocess.run(['git', 'ls-files'], cwd=ROOT, capture_output=True, text=True).stdout.splitlines()
    files += subprocess.run(['git', 'ls-files', '--others', '--exclude-standard'], cwd=ROOT, capture_output=True, text=True).stdout.splitlines()
    bad, checked = [], 0
    for name in files:
        path = ROOT / name
        if path.suffix.lower() not in TEXT or not path.is_file():
            continue
        checked += 1
        text = path.read_text(encoding='utf-8', errors='replace')
        for number, line in enumerate(text.splitlines(), 1):
            if CONTROL.search(line):
                bad.append(f'{name}:{number}')
                break
    record(f'no stray control characters in {checked} text files', 'fail' if bad else 'pass', bad[:8] or '')


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--report', help='write the results as JSON here')
    args = parser.parse_args()
    for step in (ruff, bandit, eslint, control_characters):
        step()
    if args.report:
        Path(args.report).parent.mkdir(parents=True, exist_ok=True)
        Path(args.report).write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding='utf-8')
    sys.exit(1 if any(r['status'] == 'fail' for r in rows) else 0)


if __name__ == '__main__':
    main()
