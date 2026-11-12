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


def _es_modulo(cuerpo):
    return bool(re.search(r'^\s*(?:import|export)\b|\bimport\s*\.', cuerpo, re.M))


def _sintaxis_navegador(cuerpo, module, mantener=False):
    """Sin Node.js (lo normal en un PC de usuario) se compila en el navegador sin cabeza incluido.
    Devuelve (comprobado, error)."""
    try:
        import render_check
    except Exception as error:
        return False, 'Syntax checker unavailable: %s' % str(error)[:120]
    resultado = render_check.sintaxis_js(cuerpo, module=module, mantener=mantener)
    if resultado.get('comprobado'):
        return True, resultado.get('error')
    return False, resultado.get('error') or 'Syntax checker unavailable.'


def _sintaxis(cuerpo, module=None, mantener=False):
    if module is None:
        module = _es_modulo(cuerpo)
    node = shutil.which('node')
    if not node:
        comprobado, error = _sintaxis_navegador(cuerpo, module, mantener)
        return error if comprobado else _NO_COMPROBADO + (error or '')
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


_NO_COMPROBADO = 'NOT CHECKED: '


def verificar_html(html):
    blocks = scripts(html)
    executable = [(attrs, body) for attrs, body in blocks if body.strip()
        and 'src' not in attrs and (attrs.get('type') or '').strip().lower() in JAVASCRIPT_TYPES]
    info = {'language':'html', 'scripts':len(blocks), 'chars_js':sum(len(body) for _, body in executable),
            'runtime_checked':False}
    errors, unchecked = [], []
    # Without Node.js every block is compiled in the bundled browser: open it once for the page.
    navegador = len(executable) > 1 and not shutil.which('node')
    try:
        for index, (attrs, body) in enumerate(executable, 1):
            error = _sintaxis(body, module=(attrs.get('type') or '').strip().lower() == 'module', mantener=navegador)
            if error and error.startswith(_NO_COMPROBADO):
                unchecked.append('Script %d: %s' % (index, error[len(_NO_COMPROBADO):]))
            elif error:
                errors.append('Script %d: %s' % (index, error))
    finally:
        if navegador:
            try:
                import render_check
                render_check.cierra_sesion()
            except Exception:
                pass
    if unchecked and not errors:
        return {'ok':None,'checked':False,'errores':[],'avisos':unchecked,'info':info}
    return {'ok':not errors,'checked':True,'errores':errors,'avisos':unchecked, 'info':info}


def verificar_contenido(texto, ruta):
    extension = Path(ruta).suffix.lower()
    info = {'language':extension, 'runtime_checked':False}
    if extension in ('.py', '.json'):
        try:
            if extension == '.py':
                import warnings
                with warnings.catch_warnings():
                    warnings.simplefilter('ignore')
                    compile(texto, str(ruta), 'exec', dont_inherit=True)
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
        error = _sintaxis(texto, module=True if extension == '.mjs' else False if extension == '.cjs' else None)
        if error and error.startswith(_NO_COMPROBADO):
            return {'ok':None,'checked':False,'errores':[],'avisos':[error[len(_NO_COMPROBADO):]],'info':info}
        return {'ok':not error,'checked':True,'errores':[error] if error else [],'avisos':[],'info':info}
    if extension == '.java':
        return _java(texto, ruta, info)
    if extension == '.css':
        return _css(texto, info)
    if extension in ('.ps1', '.psm1', '.psd1'):
        return _powershell(texto, info)
    if extension in EXTERNOS:
        return _externo(texto, ruta, info)
    note = 'No checker configured for this extension.'
    return {'ok':None,'checked':False,'errores':[],'avisos':[note],'info':info}


def _css(texto, info):
    """CSS no tiene compilador a mano, pero lo que rompe una hoja entera es estructural: una llave
    sin cerrar, un comentario o una cadena abiertos. A partir de ahi el navegador descarta el resto."""
    pila, i, linea, n = [], 0, 1, len(texto)
    while i < n:
        c = texto[i]
        if c == '\n':
            linea += 1
        elif texto.startswith('/*', i):
            fin = texto.find('*/', i + 2)
            if fin < 0:
                return _falla(info, 'line %d: comment /* is never closed' % linea)
            linea += texto.count('\n', i, fin)
            i = fin + 2
            continue
        elif c in '"\'':
            j = i + 1
            while j < n and texto[j] != c:
                if texto[j] == '\\':
                    j += 1
                elif texto[j] == '\n':
                    return _falla(info, 'line %d: string is never closed' % linea)
                j += 1
            if j >= n:
                return _falla(info, 'line %d: string is never closed' % linea)
            i = j + 1
            continue
        elif c in '{([':
            pila.append((c, linea))
        elif c in '})]':
            esperado = {'}': '{', ')': '(', ']': '['}[c]
            if not pila or pila[-1][0] != esperado:
                return _falla(info, 'line %d: unexpected %r' % (linea, c))
            pila.pop()
        i += 1
    if pila:
        return _falla(info, 'line %d: %r is never closed' % (pila[-1][1], pila[-1][0]))
    return {'ok':True,'checked':True,'errores':[],'avisos':[],'info':info}


def _falla(info, mensaje):
    return {'ok':False,'checked':True,'errores':[mensaje],'avisos':[],'info':info}


def _powershell(texto, info):
    """El analizador de PowerShell viene con Windows: se usa sin ejecutar nada del script."""
    exe = shutil.which('powershell') or shutil.which('pwsh')
    if not exe:
        return {'ok':None,'checked':False,'errores':[],'avisos':['PowerShell is not available.'],'info':info}
    with tempfile.TemporaryDirectory(prefix='val-ps-') as folder:
        source = Path(folder) / 'script.ps1'
        source.write_text(texto, encoding='utf-8-sig')
        orden = ("[Console]::OutputEncoding=[Text.Encoding]::UTF8;$e=$null;$t=$null;[void][System.Management.Automation.Language.Parser]::ParseFile($env:VAL_PS_FILE,[ref]$t,[ref]$e);"
                 "$e|%{'line '+$_.Extent.StartLineNumber+': '+$_.Message}")
        try:
            result = subprocess.run([exe, '-NoProfile', '-NonInteractive', '-Command', orden], capture_output=True,
                                    text=True, encoding='utf-8', errors='replace', timeout=60,
                                    env=dict(__import__('os').environ, VAL_PS_FILE=str(source)),
                                    creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        except (OSError, subprocess.TimeoutExpired) as error:
            return {'ok':None,'checked':False,'errores':[],'avisos':['PowerShell parser did not finish: %s' % error],'info':info}
    if result.returncode != 0 and not result.stdout.strip():
        return {'ok':None,'checked':False,'errores':[],'avisos':[(result.stderr or 'PowerShell parser failed.')[:300]],'info':info}
    errores = [line for line in result.stdout.splitlines() if line.strip()]
    return {'ok':not errores,'checked':True,'errores':errores[:8],'avisos':[],'info':info}


# Compiladores habituales: si estan instalados, comprueban sintaxis (y tipos cuando es barato) sin
# ejecutar ni dejar binarios. Si no estan, se dice que no se comprobo, nunca que esta bien.
EXTERNOS = {
    '.ts': [('tsc', ['--noEmit', '--skipLibCheck', '--target', 'es2022', '--module', 'esnext', '{f}'])],
    '.tsx': [('tsc', ['--noEmit', '--skipLibCheck', '--target', 'es2022', '--module', 'esnext', '--jsx', 'preserve', '{f}'])],
    '.c': [('gcc', ['-fsyntax-only', '{f}']), ('clang', ['-fsyntax-only', '{f}'])],
    '.h': [('gcc', ['-fsyntax-only', '-x', 'c', '{f}']), ('clang', ['-fsyntax-only', '-x', 'c', '{f}'])],
    '.cpp': [('g++', ['-fsyntax-only', '-std=c++20', '{f}']), ('clang++', ['-fsyntax-only', '-std=c++20', '{f}'])],
    '.cc': [('g++', ['-fsyntax-only', '-std=c++20', '{f}']), ('clang++', ['-fsyntax-only', '-std=c++20', '{f}'])],
    '.hpp': [('g++', ['-fsyntax-only', '-x', 'c++', '-std=c++20', '{f}']), ('clang++', ['-fsyntax-only', '-x', 'c++', '-std=c++20', '{f}'])],
    '.rs': [('rustc', ['--edition', '2021', '--crate-type', 'lib', '--emit', 'metadata', '-o', '{d}/out.rmeta', '{f}'])],
    '.go': [('gofmt', ['-e', '-l', '{f}'])],
    '.php': [('php', ['-l', '{f}'])],
    '.rb': [('ruby', ['-wc', '{f}'])],
    '.lua': [('luac', ['-p', '{f}']), ('luac5.4', ['-p', '{f}'])],
    '.sh': [('sh', ['-n', '{f}'])],
    '.bash': [('sh', ['-n', '{f}'])],
}


def _externo(texto, ruta, info):
    extension = Path(ruta).suffix.lower()
    for programa, argumentos in EXTERNOS[extension]:
        exe = shutil.which(programa)
        # C:\Windows\System32\bash.exe es el lanzador de WSL: puede pedir instalar una distro.
        if not exe or 'system32' in exe.lower():
            continue
        with tempfile.TemporaryDirectory(prefix='val-check-') as folder:
            source = Path(folder) / Path(ruta).name
            source.write_text(texto, encoding='utf-8')
            orden = [exe] + [a.replace('{f}', str(source)).replace('{d}', folder) for a in argumentos]
            try:
                result = subprocess.run(orden, capture_output=True, text=True, encoding='utf-8', errors='replace',
                                        timeout=60, cwd=folder, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            except (OSError, subprocess.TimeoutExpired) as error:
                return {'ok':None,'checked':False,'errores':[],'avisos':['%s did not finish: %s' % (programa, error)],'info':info}
            salida = ((result.stderr or '') + (result.stdout or '')).replace(str(source), Path(ruta).name).replace(folder, '').strip()
        info['checker'] = programa
        # gofmt -l imprime el nombre si el formato cambia: eso no es un error; -e los errores van a stderr.
        fallo = result.returncode != 0 or (programa == 'gofmt' and bool(result.stderr.strip()))
        avisos = [salida[:600]] if salida and not fallo and programa != 'gofmt' else []
        return {'ok':not fallo,'checked':True,'errores':[salida[:1200] or 'Check failed.'] if fallo else [],'avisos':avisos,'info':info}
    nombres = ', '.join(sorted({programa for programa, _ in EXTERNOS[extension]}))
    return {'ok':None,'checked':False,'errores':[],'avisos':['Not checked: install %s to check %s files.' % (nombres, extension)],'info':info}


# Lo que se comprueba al escribir un archivo (pc_mcp.syntax_report).
COMPROBABLES = ('.py', '.json', '.js', '.mjs', '.cjs', '.yaml', '.yml', '.toml', '.xml', '.svg', '.java',
                '.css', '.ps1', '.psm1', '.psd1') + tuple(EXTERNOS)


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
