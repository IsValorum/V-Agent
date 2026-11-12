"""Feed the code checker a correct and a broken file in every language it handles, for real.

    .venv\\Scripts\\python tests\\smoke\\language_checks.py [--report build\\quality\\languages.json]

The agent calls this checker after writing code (agent/verify.py) and the page check
(agent/render_check.py) for web pages. Each case writes a file and runs the same function:

- Python (compiled, not just parsed), JSON, TOML, XML, SVG, CSS, PowerShell, JavaScript as script,
  module and CommonJS, and HTML with classic and module scripts: the correct file passes and the
  broken one is reported with an error.
- Languages that need an external compiler (C, C++, Rust, Go, TypeScript, PHP, Ruby, Lua, shell):
  when the compiler is installed the broken file must be reported; when it is not, the result must
  say "not checked" — never "fine".
- Web pages run as in the sandboxed preview: a page that touches localStorage at load fails there,
  so the checker must report it; the same page with the access guarded must pass.
- JavaScript is checked once with Node.js and once without it (the bundled browser is used instead).
"""
import argparse
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for stream in (sys.stdout, sys.stderr):
    stream.reconfigure(encoding='utf-8', errors='replace')
os.environ.setdefault('STRATA_AGENT_DATA', tempfile.mkdtemp(prefix='va-languages-'))
bundled = ROOT / 'browser' / 'chrome-headless-shell-win64' / 'chrome-headless-shell.exe'
if bundled.is_file():
    os.environ.setdefault('STRATA_AGENT_BROWSER', str(bundled))
sys.path[:0] = [str(ROOT / 'agent'), str(ROOT)]
import render_check  # noqa: E402
import verify  # noqa: E402

# (file, content, expected): True = must pass, False = must be reported.
BUILT_IN = [
    ('ok.py', 'def f():\n    return 1\n', True),
    ('return_outside.py', 'x = 1\nreturn x\n', False),  # parses, but does not compile
    ('await_outside.py', 'async def f():\n    pass\nawait f()\n', False),
    ('ok.json', '{"a": [1, 2]}', True),
    ('bad.json', '{"a": [1, 2}', False),
    ('ok.toml', 'title = "x"\n[server]\nport = 80\n', True),
    ('bad.toml', 'title = "x\n', False),
    ('ok.xml', '<a><b>1</b></a>', True),
    ('bad.xml', '<a><b>1</a>', False),
    ('entity.xml', '<!DOCTYPE a [<!ENTITY x "y">]><a>&x;</a>', False),
    ('ok.svg', '<svg xmlns="http://www.w3.org/2000/svg"><circle r="4"/></svg>', True),
    ('bad.svg', '<svg xmlns="http://www.w3.org/2000/svg"><circle r="4"></svg>', False),
    ('ok.css', 'body { color: red; }\n.a { background: url("x.png"); }\n', True),
    ('unclosed_block.css', 'body { color: red;\n.a { margin: 0 }\n', False),
    ('unclosed_comment.css', '/* not closed\nbody{}\n', False),
    ('ok.ps1', 'param($x)\nif ($x) { Write-Output "hola" }\n', True),
    ('bad.ps1', 'if ($x) { Write-Output "hola"\n', False),
]
JAVASCRIPT = [
    ('ok.js', 'const a = 1;\nfunction f(){ return a }\n', True),
    ('bad.js', 'const a = ;\n', False),
    ('ok.mjs', "import {\n  a,\n  b\n} from './x.js';\nexport const c = await Promise.resolve(a + b);\n", True),
    ('bad.mjs', "import x from './x.js';\n\nconst y = x +;\n", False),
    ('ok.cjs', "const fs = require('fs');\nmodule.exports = { fs };\n", True),
    ('bad.cjs', "module.exports = {;\n", False),
    ('ok.html', '<!doctype html><script>let a=1;</script><script type="module">import {b} from "./b.js"; console.log(b)</script>', True),
    ('bad.html', '<!doctype html><script>let a=;</script>', False),
]
EXTERNAL = [
    ('bad.c', 'int main(void){ return ; ', 'gcc/clang'),
    ('bad.cpp', 'int main(){ int x = ; }', 'g++/clang++'),
    ('bad.rs', 'fn main() { let x = ; }', 'rustc'),
    ('bad.go', 'package main\nfunc main() { x := }\n', 'gofmt'),
    ('bad.ts', 'const a: number = ;\n', 'tsc'),
    ('bad.php', '<?php echo "a" ?>\n<?php $x = ; ?>', 'php'),
    ('bad.rb', 'def f(\n', 'ruby'),
    ('bad.lua', 'local x = \n', 'luac'),
    ('bad.sh', 'if true; then echo a\n', 'sh'),
    ('bad.java', 'public class A { public static void main(String[] a){ int x = ; } }\n', 'javac'),
]
PREVIEW = [
    ('theme.html', '<!doctype html><button id=t>Theme</button><script>document.body.dataset.theme='
                   'localStorage.getItem("theme")||"light";</script>', False),
    ('theme_guarded.html', '<!doctype html><button id=t>Theme</button><script>let v="light";'
                           'try{v=localStorage.getItem("theme")||v}catch(e){}document.body.dataset.theme=v;</script>', True),
]
rows = []


def check(name, ok, detail=''):
    rows.append({'engine': 'code checker', 'check': name, 'status': 'pass' if ok else 'fail', 'detail': str(detail)[:300]})
    print(f"  {'OK  ' if ok else 'FAIL'} {name}" + (f' — {detail}' if detail else ''))


def first(result):
    return str((result.get('errores') or result.get('avisos') or [''])[0])[:120].replace('\n', ' ')


def run(folder, cases, label=''):
    for name, text, expected in cases:
        path = folder / name
        path.write_text(text, encoding='utf-8')
        result = verify.verificar_archivo(str(path))
        verdict = 'passes' if expected else 'is reported'
        check(f'{name}{label} {verdict}', result.get('ok') is expected, first(result) or f"ok={result.get('ok')}")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--report', help='write the results as JSON here')
    args = parser.parse_args()
    with tempfile.TemporaryDirectory() as temp:
        folder = Path(temp)
        run(folder, BUILT_IN)
        if shutil.which('node'):
            run(folder, JAVASCRIPT, ' (Node.js)')
        original = shutil.which
        shutil.which = lambda name, *a, **k: None if name == 'node' else original(name, *a, **k)
        try:
            run(folder, JAVASCRIPT, ' (bundled browser, no Node.js)')
        finally:
            shutil.which = original
        for name, text, tool in EXTERNAL:
            path = folder / name
            path.write_text(text, encoding='utf-8')
            result = verify.verificar_archivo(str(path))
            if result.get('ok') is None:
                check(f'{name}: without {tool} it says "not checked", not "fine"', not result.get('checked'), first(result))
            else:
                check(f'{name}: reported by {tool}', result.get('ok') is False, first(result))
        for name, text, expected in PREVIEW:
            path = folder / name
            path.write_text(text, encoding='utf-8')
            result = render_check.render_de_archivo(str(path), espera_ms=800)
            errors = result.get('errores') or []
            verdict = 'opens cleanly in the sandboxed preview' if expected else 'is reported: it fails in the sandboxed preview'
            check(f'{name} {verdict}', (not errors) is expected, str(errors[:1])[:120] or 'no errors')
        render_check.cierra_sesion()
    failed = [r for r in rows if r['status'] == 'fail']
    print(f'\n{len(rows)} checks, {len(failed)} failed')
    if args.report:
        Path(args.report).parent.mkdir(parents=True, exist_ok=True)
        Path(args.report).write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding='utf-8')
    sys.exit(1 if failed else 0)


if __name__ == '__main__':
    main()
