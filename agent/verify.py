"""Syntax checks only. Browser execution reports runtime errors separately."""
import ast
from html.parser import HTMLParser
import json
from pathlib import Path
import re
import shutil
import subprocess
import tempfile

JAVASCRIPT_TYPES = {'', 'module', 'text/javascript', 'application/javascript',
                    'text/ecmascript', 'application/ecmascript', 'text/jscript', 'text/livescript'}


class _Scripts(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=False)
        self.blocks = []
        self.current = None

    def handle_starttag(self, tag, attrs):
        if tag == 'script':
            self.current = (dict(attrs), [])

    def handle_data(self, data):
        if self.current is not None:
            self.current[1].append(data)

    def handle_endtag(self, tag):
        if tag == 'script' and self.current is not None:
            attrs, parts = self.current
            self.blocks.append((attrs, ''.join(parts)))
            self.current = None


def scripts(html):
    parser = _Scripts()
    parser.feed(html)
    parser.close()
    return parser.blocks


def _sintaxis(cuerpo, module=None):
    node = shutil.which('node')
    if not node:
        return 'Node.js is not installed.'
    if module is None:
        module = bool(re.search(r'^\s*(?:import|export)\b|\bimport\s*\.', cuerpo, re.M))
    with tempfile.TemporaryDirectory(prefix='strata-syntax-') as folder:
        path = Path(folder)/('code.mjs' if module else 'code.cjs')
        path.write_text(cuerpo, encoding='utf-8')
        try:
            result = subprocess.run([node, '--check', str(path)], capture_output=True,
                text=True, encoding='utf-8', errors='replace', timeout=30)
        except (OSError, subprocess.TimeoutExpired) as error:
            return 'Syntax checker could not run: '+str(error)[:160]
        if result.returncode == 0:
            return None
        lines = [line for line in result.stderr.replace(str(path), 'code').splitlines() if line.strip()]
        detail = next((line for line in lines if 'SyntaxError:' in line), '')
        return ' '.join(lines[:3]+([detail] if detail else []))[:600] or 'Syntax error.'


def verificar_html(html):
    blocks = scripts(html)
    executable = [(attrs, body) for attrs, body in blocks if body.strip()
        and 'src' not in attrs and (attrs.get('type') or '').strip().lower() in JAVASCRIPT_TYPES]
    info = {'language':'html', 'scripts':len(blocks), 'chars_js':sum(len(body) for _, body in executable),
            'runtime_checked':False}
    if executable and not shutil.which('node'):
        return {'ok':None,'checked':False,'errores':[],'avisos':['Node.js is not installed; inline JavaScript was not checked.'],'info':info}
    errors = []
    for index, (attrs, body) in enumerate(executable, 1):
        error = _sintaxis(body, module=(attrs.get('type') or '').strip().lower() == 'module')
        if error:
            errors.append('Script %d: %s' % (index, error))
    return {'ok':not errors,'checked':True,'errores':errors,'avisos':[], 'info':info}


def verificar_contenido(texto, ruta):
    extension = Path(ruta).suffix.lower()
    info = {'language':extension, 'runtime_checked':False}
    if extension in ('.py', '.json'):
        try:
            if extension == '.py':
                ast.parse(texto, filename=str(ruta))
            else:
                json.loads(texto)
            return {'ok':True,'checked':True,'errores':[],'avisos':[],'info':info}
        except (SyntaxError, ValueError) as error:
            return {'ok':False,'checked':True,'errores':[str(error)],'avisos':[],'info':info}
    if extension in ('.toml','.xml','.svg','.yaml','.yml'):
        try:
            if extension=='.toml':
                import tomllib
                tomllib.loads(texto)
            elif extension in ('.xml','.svg'):
                import xml.etree.ElementTree as ET
                if '<!DOCTYPE' in texto.upper() or '<!ENTITY' in texto.upper():raise ValueError('DTD/entity declarations are not supported by this check.')
                ET.fromstring(texto)
            else:
                try:import yaml
                except ImportError:return {'ok':None,'checked':False,'errores':[],'avisos':['PyYAML is not installed.'],'info':info}
                yaml.safe_load(texto)
            return {'ok':True,'checked':True,'errores':[],'avisos':[],'info':info}
        except Exception as error:return {'ok':False,'checked':True,'errores':[str(error)[:600]],'avisos':[],'info':info}
    if extension in ('.html', '.htm'):
        return verificar_html(texto)
    if extension in ('.js', '.mjs', '.cjs'):
        if not shutil.which('node'):
            return {'ok':None,'checked':False,'errores':[],'avisos':['Node.js is not installed.'],'info':info}
        error = _sintaxis(texto, module=True if extension == '.mjs' else False if extension == '.cjs' else None)
        return {'ok':not error,'checked':True,'errores':[error] if error else [],'avisos':[],'info':info}
    if extension == '.java':
        return _java(texto, ruta, info)
    note = 'Use the project TypeScript check with explicit command access.' if extension in ('.ts','.tsx') else 'No checker configured for this extension.'
    return {'ok':None,'checked':False,'errores':[],'avisos':[note],'info':info}


def _java(texto, ruta, info):
    """Compile (never run) a copy in a temporary folder; javac reports syntax and type errors."""
    import subprocess, tempfile
    javac = shutil.which('javac')
    if not javac:
        return {'ok':None,'checked':False,'errores':[],'avisos':['javac is not installed.'],'info':info}
    with tempfile.TemporaryDirectory(prefix='val-java-') as folder:
        source = Path(folder) / Path(ruta).name
        source.write_text(texto, encoding='utf-8')
        try:
            result = subprocess.run([javac, '-encoding', 'UTF-8', '-Xlint:none', '-d', folder, str(source)],
                                    capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=60,
                                    creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        except (OSError, subprocess.TimeoutExpired) as error:
            return {'ok':None,'checked':False,'errores':[],'avisos':['javac did not finish: %s' % error],'info':info}
    output = (result.stderr or result.stdout).replace(folder, '').strip()
    return {'ok':result.returncode == 0,'checked':True,'errores':[] if result.returncode == 0 else [output[:1200]],'avisos':[],'info':info}


def verificar_archivo(ruta):
    try:
        text = Path(ruta).read_text(encoding='utf-8-sig', errors='strict')
    except (OSError, UnicodeError) as error:
        return {'ok':False,'checked':False,'errores':[str(error)],'avisos':[],'info':{}}
    result = verificar_contenido(text, ruta)
    result['info'].update(ruta=str(ruta), chars=len(text))
    from verification_evidence import evidence
    return evidence(result,'syntax')


if __name__ == '__main__':
    import sys
    for path in sys.argv[1:]:
        print(json.dumps(verificar_archivo(path), ensure_ascii=False, indent=2))
