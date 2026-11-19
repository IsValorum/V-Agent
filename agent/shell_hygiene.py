"""What makes a terminal usable by any model, not only by one fine-tuned for a particular harness.

Models trained mostly on Linux transcripts stumble on the same things in a Windows tool: escape codes
and progress bars that fill the context with noise, programs that wait for a keyboard that is not
there, output that only arrives when a process ends, `ls`/`cat`/`grep` that do not exist, a timeout with
no next step. Harness-specific fine-tunes (e.g. LoRA adapters trained to drive one agent's terminal)
mostly teach a model those quirks; here the tool removes them instead:
  * a non-interactive, colourless environment for every command (and unbuffered Python output, so a
    background job shows its progress while it runs);
  * output cleaned the way a person reads a terminal: escape codes removed, carriage-return progress
    collapsed to its final state, trailing padding stripped, long runs of the same line summarised;
  * a short hint after the typical failures, saying what to do instead (never rewriting the command).
Hints and cleaned output are for the model, in English.
"""
import re

# Every variable is a standard opt-out understood by the tools that read it; none changes what a
# successful command does. Not set on purpose: CI (some builds turn warnings into errors under CI),
# PYTHONUTF8 (it changes open()'s default encoding inside the user's scripts) and PAGER (programs
# would try to start `cat`, which Windows does not have; git treats GIT_PAGER=cat as no pager).
QUIET_ENV = {
    'NO_COLOR': '1', 'FORCE_COLOR': '0', 'CLICOLOR': '0', 'PY_COLORS': '0', 'TERM': 'dumb',
    'PYTHONUNBUFFERED': '1', 'PYTHONIOENCODING': 'utf-8',
    'GIT_TERMINAL_PROMPT': '0', 'GCM_INTERACTIVE': 'never', 'GIT_PAGER': 'cat',
    'PIP_NO_INPUT': '1', 'PIP_DISABLE_PIP_VERSION_CHECK': '1', 'PIP_PROGRESS_BAR': 'off',
    'npm_config_progress': 'false', 'npm_config_fund': 'false', 'npm_config_update_notifier': 'false',
    'DOTNET_CLI_TELEMETRY_OPTOUT': '1', 'DOTNET_NOLOGO': '1', 'POWERSHELL_TELEMETRY_OPTOUT': '1',
}

_ANSI = re.compile(r'\x1b\[[0-?]*[ -/]*[@-~]|\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)|\x1b[@-Z\\-_]')


def decode_clixml(text):
    """Windows PowerShell writes some errors (parse errors among them) as CLIXML on stderr: `#< CLIXML <Objs…
    <S S="Error">The token '&amp;&amp;' is not…_x000D__x000A_</S>`. Keep only the readable message."""
    if not text or '#< CLIXML' not in text:
        return text
    import html
    parts = re.findall(r'<S S="Error">(.*?)</S>', text, re.S)
    if not parts:
        return text
    message = re.sub(r'_x([0-9A-Fa-f]{4})_', lambda m: chr(int(m.group(1), 16)), ''.join(parts))
    return html.unescape(message)


def clean(text):
    """Terminal output as it would look on screen, without the bytes that only drive the screen."""
    if not text:
        return text
    text = decode_clixml(text)
    text = _ANSI.sub('', text).replace('\r\n', '\n')
    lines = []
    for line in text.split('\n'):
        if '\r' in line:
            # A progress bar rewrites the same line with \r: keep what it finally showed.
            parts = [part for part in line.split('\r') if part.strip()]
            line = parts[-1] if parts else ''
        lines.append(line.rstrip())
    out, i = [], 0
    while i < len(lines):
        j = i
        while j + 1 < len(lines) and lines[j + 1] == lines[i]:
            j += 1
        repeats = j - i + 1
        if repeats > 3 and lines[i].strip():
            out.extend([lines[i], '[previous line repeated %d more times]' % (repeats - 1)])
        else:
            out.extend(lines[i:j + 1])
        i = j + 1
    return '\n'.join(out).strip('\n')


# Linux habits and what does the same on Windows (cmd / PowerShell).
UNIX_EQUIVALENTS = {
    'ls': 'dir (cmd) or Get-ChildItem (PowerShell); or the fs_list tool',
    'cat': 'type FILE (cmd) or Get-Content FILE; or the fs_read tool',
    'grep': 'findstr /n /i "text" FILE (cmd) or Select-String -Pattern "text" (PowerShell); or the fs_search tool',
    'which': 'where NAME (cmd) or Get-Command NAME (PowerShell)',
    'rm': 'del FILE / rmdir /s /q DIR (cmd) or Remove-Item -Recurse (PowerShell)',
    'cp': 'copy (cmd) or Copy-Item (PowerShell)', 'mv': 'move (cmd) or Move-Item (PowerShell)',
    'touch': 'type nul > FILE (cmd) or New-Item FILE (PowerShell)', 'pwd': 'cd with no argument (cmd)',
    'head': 'PowerShell: Get-Content FILE -TotalCount N', 'tail': 'PowerShell: Get-Content FILE -Tail N',
    'wc': 'PowerShell: (Get-Content FILE | Measure-Object -Line).Lines', 'find': 'dir /s /b *PATTERN* (cmd); or the fs_search tool',
    'sed': 'the fs_edit tool', 'awk': 'PowerShell, or a short python script', 'export': 'set NAME=value (cmd, same command line with &&)',
    'chmod': 'not needed on Windows', 'sudo': 'not available; ask the user to run it with Administrator rights',
    'bash': 'not available; this tool runs cmd or PowerShell', 'sh': 'not available; this tool runs cmd or PowerShell',
    'curl': 'curl.exe (built into Windows 10+) or the web__http_request tool', 'wget': 'curl.exe -L -o FILE URL',
    'open': 'start "" FILE (cmd)', 'clear': 'not needed', 'man': 'COMMAND /? (cmd) or Get-Help COMMAND (PowerShell)',
}
_NOT_FOUND = re.compile(
    r"""^['"]?(?P<name>[\w.\-]+)['"]? (?:no se reconoce|is not recognized)|"""
    r"""The term '(?P<ps>[\w.\-]+)' is not recognized|"""
    r"""El término '(?P<pses>[\w.\-]+)' no se reconoce|"""
    r"""(?P<sh>[\w.\-]+): command not found""", re.I | re.M)
_NO_STDIN = re.compile(
    r'EOFError: EOF when reading a line|Input redirection is not supported|Cannot read keys when either application|'
    r'ReadKey|stdin is not a tty|not a terminal|inappropriate ioctl|Unable to read from stdin|'
    r'Use --yes|non-?interactive|raw mode is not supported', re.I)
_GIT_AUTH = re.compile(r'could not read Username|terminal prompts disabled|Authentication failed for', re.I)


def _windows_tool(name):
    """Whether `name` resolves (first on PATH) to the program that ships with Windows."""
    import os
    import shutil
    found = shutil.which(name)
    root = os.environ.get('SystemRoot', r'C:\Windows')
    return bool(found) and os.path.normcase(found).startswith(os.path.normcase(root))


def _outside_double_quotes(command):
    return re.sub(r'"[^"\n]*"', '""', command)


def command_notes(command, shell):
    """Notes added to every result (success too) when the command uses bash syntax the chosen shell reads
    differently. A success can hide it: `python -c 'print(42)'` prints nothing and exits 0 in cmd."""
    notes = []
    bare = _outside_double_quotes(command)
    if shell == 'cmd':
        if re.search(r"(?:^|[\s=(])'[^'\n]*'(?=$|[\s)|&>])", bare):
            notes.append('cmd does not treat single quotes as quotes: they were passed literally. Use double quotes '
                         '(python -c "print(42)").')
        if re.search(r'(?<![%\w])\$\{?[A-Za-z_]\w*', bare):
            notes.append('cmd expands %NAME%, not $NAME (PowerShell: $env:NAME).')
        if re.search(r';\s+[A-Za-z.]', bare):  # "a; b" (bash); not PATH lists such as %PATH%;C:\tools
            notes.append('In cmd ";" does not separate commands: use & (always) or && (if the previous one succeeded).')
        if '\n' in command.strip() and re.search(r'(?i)(?:^|\s)for\s+(?:/\w+\s+)*%[a-z]\b', command):
            notes.append('Several lines run as a batch script: write for-loop variables as %%i, not %i.')
        if '/dev/null' in command:
            notes.append('Windows has no /dev/null: write NUL in its place (curl -o NUL ..., command 2> NUL).')
        # Same names, other programs: they "succeed" and print nothing useful (seen with a real model 2026-11-18).
        # Only said when this PC really runs the Windows one: with Git's Unix tools first on PATH, `find` is GNU
        # find, and a wrong note sent the model to a Windows idiom that GNU find ran on the whole C: drive.
        if re.search(r'(?:^|[&|(]\s*)find\s+\S*\s*-(?:name|type|iname|path|maxdepth)\b', bare) and _windows_tool('find'):
            notes.append('find here is Windows FIND (searches text inside files), not Unix find: list files with '
                         'dir /s /b *.py, or use the fs_search tool.')
        if re.search(r'(?:^|[&|(]\s*)timeout\s+\d+\s+\S', bare) and _windows_tool('timeout'):
            notes.append('timeout here is Windows TIMEOUT (it only waits), not a time limit for a command: use the '
                         'tool\'s timeout argument instead.')
        if re.search(r'(?:^|[&|(]\s*)(?:mkdir|md|rmdir|rd|del|erase|copy|move|dir|type)\s+-[A-Za-z]', bare):
            notes.append('cmd built-in options start with /, not - (dir /s /b, del /q, rmdir /s /q); a "-x" argument '
                         'is taken as a name.')
    elif shell == 'powershell':
        if re.search(r'&&|\|\|', _outside_double_quotes(re.sub(r"'[^'\n]*'", "''", command))):
            notes.append('Windows PowerShell 5.1 has no && or ||: use ; or if ($?) { next-command }.')
    return ''.join('\n[note] ' + note for note in notes)


def failure_hint(command, output, timed_out=False, sandboxed=False):
    """One line saying what to do after a typical failure, or ''."""
    text = output or ''
    stripped = (command or '').strip()
    if timed_out:
        if sandboxed:
            return ('\n[hint] The command did not finish within its time limit (partial output above). Raise timeout '
                    '(up to 300 s), or split the work into shorter commands.')
        return ('\n[hint] The command did not finish within its time limit (partial output above). For servers, '
                'watchers and long builds, run it with background=true and then call job_wait once; otherwise raise '
                'timeout (up to 300 s).')
    if stripped.startswith('```') or re.match(r'^[$>#]\s', stripped):
        return '\n[hint] Send only the command itself, without a prompt sign ($, >, #) or markdown fences (```).'
    if re.search(r'Invoke-WebRequest|par[aá]metros obligatorios:\s+Uri|mandatory parameters?:\s+Uri', text) and \
            re.match(r'(?i)(curl|wget)\b', stripped):
        return '\n[hint] In Windows PowerShell curl/wget are aliases of Invoke-WebRequest: call curl.exe explicitly.'
    if re.search(r'no es un separador de instrucciones|is not a valid statement separator', text):
        return '\n[hint] Windows PowerShell 5.1 has no && or ||: use ; or if ($?) { next-command }.'
    if re.match(r'(?i)mkdir\s+-p\b', stripped):
        return ('\n[hint] cmd\'s mkdir creates the parent folders by itself: drop -p and use backslashes '
                '(mkdir x\\y\\z).')
    if re.match(r'^[A-Za-z_]\w*=\S*\s+\S', stripped):
        return '\n[hint] NAME=value before a command is bash syntax; in cmd use: set NAME=value&& command'
    match = _NOT_FOUND.search(text)
    if stripped.startswith('./') and re.search(r'no se reconoce|not recognized|cannot find|no puede encontrar', text, re.I):
        match = match or re.match(r'(?P<name>\.)(?P<ps>)?(?P<pses>)?(?P<sh>)?', '.')
    if match and not sandboxed:
        name = (match.group('name') or match.group('ps') or match.group('pses') or match.group('sh') or '').lower()
        name = name[:-4] if name.endswith('.exe') else name
        if name == '.' or stripped.startswith('./'):
            return ('\n[hint] ./name is bash. In cmd run a script through its interpreter (python a.py, node a.js) '
                    'or a batch file by its name (build.cmd or .\\build.cmd).')
        if name in ('python3', 'pip3'):
            return '\n[hint] On Windows use %s (or py -3).' % ('python' if name == 'python3' else 'python -m pip')
        if name in UNIX_EQUIVALENTS:
            return '\n[hint] `%s` is a Linux command; on this Windows PC use %s.' % (name, UNIX_EQUIVALENTS[name])
        return ('\n[hint] `%s` is not installed or not on PATH. Check with `where %s`; do not guess other names.'
                % (name, name))
    if _GIT_AUTH.search(text):
        return ('\n[hint] Git needs credentials and cannot ask for them here (no keyboard, no login window). Use a public '
                'URL, or ask the user to sign in to Git first.')
    if _NO_STDIN.search(text):
        return ('\n[hint] Commands run without keyboard input. Pass the answers as arguments or flags (for example '
                '--yes / -y / --non-interactive), or pipe them in (echo y| command).')
    return ''


def batch_script(command):
    """A multi-line command for cmd as a batch file: `cmd /c` runs only the first line of a multi-line command
    line and reported success (seen 2026-11-18). UTF-8 from the second line on; ends with the last exit code."""
    lines = command.replace('\r\n', '\n').strip('\n').split('\n')
    return '@echo off\r\nchcp 65001 >nul\r\n' + '\r\n'.join(lines) + '\r\nexit /b %errorlevel%\r\n'


def fit_output(result, limit, save):
    """Keep a long result readable: its beginning and its end (where errors are), and the whole text saved
    to a file the model can read (`save(text)` returns the relative path, or None)."""
    if len(result) <= limit:
        return result
    path = save(result)
    head, tail = int(limit * 0.35), int(limit * 0.55)
    where = ('full output saved at %s: read parts of it with fs_read (offset) or search it with fs_search' % path
             if path else 'redirect the output to a file (command > out.txt) and read it with fs_read')
    return (result[:head] + '\n[... %d characters omitted; %s ...]\n' % (len(result) - head - tail, where)
            + result[-tail:])


def decode(data):
    """Bytes of a command's output as text. Commands run with UTF-8 output, but a few write in the console's
    old code page anyway (Windows PowerShell parse errors are written before UTF-8 is set): those would come
    out with replacement characters; such text is read with the OEM code page instead. UTF-16 output
    (wmic and some Windows tools) is read as such, and binary output is not shown."""
    if not data:
        return ''
    if data.count(b'\x00') * 3 > len(data):
        # UTF-16: every other byte is zero.
        try:
            decoded = data.decode('utf-16' if data[:2] in (b'\xff\xfe', b'\xfe\xff') else 'utf-16-le')
            if sum(ch.isprintable() or ch in '\r\n\t' for ch in decoded) >= 0.9 * max(1, len(decoded)):
                return decoded.lstrip('\ufeff')
        except UnicodeDecodeError:
            pass
    sample = data[:65536]
    # Not counted: tab, line breaks, backspace (spinners) and ESC (colour codes, removed later by clean()).
    control = sum(1 for byte in sample if byte < 8 or byte in (11, 12) or 14 <= byte < 27 or 28 <= byte < 32)
    if len(data) >= 64 and (b'\x00' in sample or control > 0.1 * len(sample)):
        # `type image.png` and the like: bytes that are not text only fill the context with symbols.
        return ('[binary output: %d bytes not shown; it is not text. Read files with fs_read/doc_read, or convert '
                'the output to text first.]' % len(data))
    try:
        return data.decode('utf-8')
    except UnicodeDecodeError:
        pass
    # Mixed output (a program in UTF-8, another one in the old console code page): each line on its own.
    lines = []
    for line in data.split(b'\n'):
        try:
            lines.append(line.decode('utf-8'))
        except UnicodeDecodeError:
            try:
                lines.append(line.decode('oem'))
            except (LookupError, UnicodeDecodeError):
                lines.append(line.decode('utf-8', 'replace'))
    return '\n'.join(lines)


def add_hint(result, hint):
    """The hint, unless the result already says the same (a note can carry it)."""
    return result if not hint or hint.split('] ', 1)[-1] in result else result + hint


_BASH_BACKGROUND = re.compile(r'(?<![&^])&\s*$')


def background_idiom(command, shell, sandboxed=False):
    """A refusal (before running) for bash's way of backgrounding a command, '' otherwise.

    `python -m http.server 8765 &` or `nohup npm run dev` look like "start it and go on", but in cmd the
    command runs in the foreground and blocks the call until its time limit; a real model did it twelve
    times in a row (2026-11-18). Nothing is run, so refusing loses nothing and the next call is right.
    """
    text = (command or '').strip()
    if shell != 'cmd' or not (_BASH_BACKGROUND.search(text) or re.match(r'(?i)nohup\s', text)):
        return ''
    if sandboxed:
        return ('Not run: a trailing "&" (or nohup) does not start a background process on Windows, and isolated mode '
                'has no background jobs. Run the command without it (the call waits up to its time limit), or ask '
                'the user for Full PC access to run servers.')
    return ('Not run: a trailing "&" (or nohup) does not start a background process on Windows; it would block this '
            'call until its time limit. Run the same command with background=true (without the & or nohup), then '
            'call job_wait with until set to a word the program prints when it is ready, for example until="Serving" '
            'or until="listening".')
