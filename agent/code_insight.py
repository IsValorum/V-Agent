"""Deeper static checks after the syntax check: mistakes that parse fine and still break at run time.

Never runs the checked code. Each check returns (errors, warnings) as short English lines for the model:
  * Python: pyflakes (undefined names, a local used before assignment, duplicate arguments, unused
    imports and variables) and imported modules that are neither the standard library, nor a file of
    the project, nor installed in the user's Python;
  * HTML: local files the page loads (scripts, styles, images, frames, pages it links to) that do not
    exist, duplicate ids, and scripts that look up an id the page does not have;
  * CSS: local url(...) files that do not exist;
  * JavaScript: relative imports / require() of files that do not exist.
"""
import ast
import os
import re
import shutil
import subprocess
import sys
import urllib.parse
from html.parser import HTMLParser
from pathlib import Path

MAX_LINES = 10
_SCHEME = re.compile(r'^[a-zA-Z][a-zA-Z0-9+.-]*:')

# pyflakes message classes that are a guaranteed failure when the code runs (or does not compile).
_PY_ERRORS = {
    'UndefinedName', 'UndefinedLocal', 'UndefinedExport', 'DuplicateArgument', 'YieldOutsideFunction',
    'ReturnOutsideFunction', 'ContinueOutsideLoop', 'BreakOutsideLoop', 'DefaultExceptNotLast',
    'TwoStarredExpressions', 'TooManyExpressionsInStarredAssignment', 'ForwardAnnotationSyntaxError',
    'PercentFormatInvalidFormat', 'PercentFormatMixedPositionalAndNamed', 'PercentFormatExpectedMapping',
    'PercentFormatExpectedSequence', 'PercentFormatPositionalCountMismatch', 'PercentFormatMissingArgument',
    'StringDotFormatInvalidFormat', 'StringDotFormatMissingArgument', 'StringDotFormatMixingAutomatic',
}


def python(text, path):
    """pyflakes + missing modules. The text already compiled."""
    errors, warnings = [], []
    try:
        tree = ast.parse(text, filename=str(path))
    except (SyntaxError, ValueError):
        return errors, warnings
    try:
        from pyflakes import checker
        found = checker.Checker(tree, filename=str(path))
        for message in sorted(found.messages, key=lambda m: (m.lineno, getattr(m, 'col', 0))):
            line = 'line %d: %s' % (message.lineno, message.message % message.message_args)
            (errors if type(message).__name__ in _PY_ERRORS else warnings).append(line)
    except ImportError:
        warnings.append('Static analysis (pyflakes) is not available; only syntax was checked.')
    missing = missing_modules(tree, path)
    for name, line in missing:
        warnings.append('line %d: module %r is not in the standard library, not a file of the project and not '
                        'installed in the Python on this PC (pip install %s), so this import would fail.'
                        % (line, name, name))
    return errors[:MAX_LINES], warnings[:MAX_LINES]


def _user_python():
    for name in ('python', 'python3', 'py'):
        exe = shutil.which(name)
        # The WindowsApps "python.exe" opens the Microsoft Store instead of running Python.
        if exe and 'windowsapps' not in exe.lower():
            return exe
    return None


def missing_modules(tree, path):
    """[(module, line)] of absolute imports that cannot be found. Empty when it cannot be decided."""
    wanted = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                wanted.setdefault(alias.name.split('.')[0], node.lineno)
        elif isinstance(node, ast.ImportFrom) and not node.level and node.module:
            wanted.setdefault(node.module.split('.')[0], node.lineno)
    stdlib = set(getattr(sys, 'stdlib_module_names', ())) | {'__future__'}
    folder = Path(path).resolve().parent if path else None
    roots = [folder, *list(folder.parents)[:3]] if folder else []

    def local(name):
        return any((root / (name + '.py')).is_file() or (root / name).is_dir() or (root / (name + '.pyd')).is_file()
                   for root in roots)
    candidates = {name: line for name, line in wanted.items() if name not in stdlib and not local(name)}
    if not candidates:
        return []
    exe = _user_python()
    if not exe:
        return []
    probe = ('import importlib.util,sys\n'
             'for n in sys.argv[1:]:\n'
             '    try:\n'
             '        found=importlib.util.find_spec(n) is not None\n'
             '    except Exception:\n'
             '        found=True\n'
             '    if not found:print(n)')
    try:
        result = subprocess.run([exe, '-I', '-c', probe, *sorted(candidates)], capture_output=True, text=True,
                                encoding='utf-8', errors='replace', timeout=20,
                                creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    except (OSError, subprocess.TimeoutExpired):
        return []
    if result.returncode != 0:
        return []
    absent = {line.strip() for line in result.stdout.splitlines() if line.strip()}
    return sorted(((name, candidates[name]) for name in absent if name in candidates), key=lambda item: item[1])


def _local_target(value, base):
    """The file a relative URL points to, or None when it is not a local relative file."""
    value = (value or '').strip()
    if (not value or value.startswith(('#', '//', '/', '{', '$', '<', '%')) or '{{' in value or '${' in value
            or _SCHEME.match(value)):
        return None
    value = urllib.parse.unquote(value.split('#', 1)[0].split('?', 1)[0])
    if not value or value.endswith('/'):
        return None
    return (base / value)


class _Page(HTMLParser):
    LOADS = {('script', 'src'), ('img', 'src'), ('source', 'src'), ('video', 'src'), ('video', 'poster'),
             ('audio', 'src'), ('iframe', 'src'), ('embed', 'src'), ('object', 'data'), ('input', 'src'), ('track', 'src')}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.refs, self.ids = [], []

    def handle_starttag(self, tag, attrs):
        values = dict(attrs)
        line = self.getpos()[0]
        if values.get('id'):
            self.ids.append((values['id'], line))
        for name, value in attrs:
            if (tag, name) in self.LOADS:
                self.refs.append((tag, name, value, line))
        if tag == 'link' and values.get('href'):
            rel = (values.get('rel') or '').lower()
            if any(word in rel for word in ('stylesheet', 'icon', 'preload', 'modulepreload', 'manifest')):
                self.refs.append((tag, 'href', values['href'], line))
        if tag == 'a' and values.get('href'):
            target = values['href'].split('#', 1)[0].split('?', 1)[0].lower()
            if target.endswith(('.html', '.htm', '.css', '.js', '.pdf', '.json', '.txt', '.csv', '.png', '.jpg', '.svg')):
                self.refs.append((tag, 'href', values['href'], line))


def _id_lookups(code):
    return set(re.findall(r'getElementById\(\s*[\'"]([^\'"]+)[\'"]\s*\)', code)) | \
        set(re.findall(r'querySelector(?:All)?\(\s*[\'"]#([A-Za-z_][\w-]*)[\'"]\s*\)', code))


def html(text, path, scripts):
    """Missing local files, duplicate ids and id lookups with no element. `scripts` are the inline bodies."""
    errors, warnings = [], []
    page = _Page()
    try:
        page.feed(text)
        page.close()
    except Exception:
        return errors, warnings
    base = Path(path).resolve().parent if path and Path(path).resolve().parent.is_dir() else None
    code = '\n'.join(scripts)
    if base is not None:
        for tag, attribute, value, line in page.refs:
            target = _local_target(value, base)
            if target is None:
                continue
            if not target.exists():
                message = ('line %d: <%s %s="%s"> points to a file that does not exist (%s next to the page)'
                           % (line, tag, attribute, value, os.path.relpath(target, base)))
                (errors if tag in ('script', 'link', 'iframe') else warnings).append(message)
            elif tag == 'script' and target.suffix.lower() in ('.js', '.mjs') and target.stat().st_size <= 512 * 1024:
                try:
                    code += '\n' + target.read_text(encoding='utf-8', errors='replace')
                except OSError:
                    pass
    seen = {}
    for ident, line in page.ids:
        if ident in seen:
            warnings.append('line %d: id "%s" is used again (first at line %d); getElementById returns only the first'
                            % (line, ident, seen[ident]))
        else:
            seen[ident] = line
    for ident in sorted(_id_lookups(code) - set(seen)):
        # Elements the script creates itself (id set in code or in an HTML string) are fine.
        made = re.search(r'''(?:\.id\s*=\s*|id\s*[:=]\s*|setAttribute\(\s*['"]id['"]\s*,\s*)['"`]%s['"`]|id=\\?['"]%s\\?['"]'''
                         % (re.escape(ident), re.escape(ident)), code)
        if not made:
            warnings.append('script looks up id "%s" but the page has no element with that id (it would get null)' % ident)
    return errors[:MAX_LINES], warnings[:MAX_LINES]


def css(text, path):
    warnings = []
    base = Path(path).resolve().parent if path and Path(path).resolve().parent.is_dir() else None
    if base is None:
        return [], []
    for match in re.finditer(r'url\(\s*([\'"]?)([^\'")]+)\1\s*\)', text):
        target = _local_target(match.group(2), base)
        if target is not None and not target.exists():
            line = text.count('\n', 0, match.start()) + 1
            warnings.append('line %d: url(%s) points to a file that does not exist' % (line, match.group(2)))
    return [], warnings[:MAX_LINES]


_IMPORT = re.compile(r'''(?:\bimport\s*(?:[\w*{}\s,$]+\s*from\s*)?|\bexport\s+[\w*{}\s,$]+\s*from\s*|\bimport\s*\(\s*)['"](\.{1,2}/[^'"\s]+)['"]''')
_REQUIRE = re.compile(r'''\brequire\(\s*['"](\.{1,2}/[^'"\s]+)['"]\s*\)''')


def javascript(text, path):
    """Relative imports that point nowhere. ES modules need the exact file name; require() tries the usual ones."""
    errors, warnings = [], []
    base = Path(path).resolve().parent if path and Path(path).resolve().parent.is_dir() else None
    if base is None:
        return errors, warnings
    for match in _IMPORT.finditer(text):
        target = base / match.group(1)
        if not target.exists():
            line = text.count('\n', 0, match.start()) + 1
            errors.append('line %d: imports "%s", which does not exist (ES modules need the exact file name, '
                          'including .js)' % (line, match.group(1)))
    for match in _REQUIRE.finditer(text):
        target = base / match.group(1)
        options = [target, Path(str(target) + '.js'), Path(str(target) + '.json'), Path(str(target) + '.cjs'),
                   target / 'index.js']
        if not any(option.is_file() for option in options):
            line = text.count('\n', 0, match.start()) + 1
            errors.append('line %d: require("%s") finds no file' % (line, match.group(1)))
    return errors[:MAX_LINES], warnings[:MAX_LINES]
