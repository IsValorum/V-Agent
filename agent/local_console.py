"""User-operated console with a persistent PowerShell or cmd session."""
import codecs, os, re, subprocess, threading, time, uuid

MAX_OUTPUT = 1000000


def _ps_quote(value):
    return "'" + str(value).replace("'", "''") + "'"


class Console:
    def __init__(self):
        self.lock = threading.RLock()
        self.proc = None
        self.reader = None
        self.shell = None
        self.workspace = None
        self.output = ''
        self.offset = 0
        self.run_output = ''
        self.run_id = None
        self.exit_code = None
        self.running = False
        self.sentinel = None
        self.session_id = 0
        self.started = None

    def snapshot(self):
        with self.lock:
            process = self.proc
            if self.running and process is not None and process.poll() is not None:
                self.running = False
                if self.exit_code is None:
                    self.exit_code = process.returncode
            return {
                'id': self.run_id,
                'text': self.output,
                'offset': self.offset,
                'running': bool(self.running),
                'exit_code': self.exit_code,
                'run_text': self.run_output[-200000:],
                'shell': self.shell or 'powershell',
                'cwd': self.workspace,
                'session': self.session_id,
            }

    def _append(self, text):
        self.output += text
        if len(self.output) > MAX_OUTPUT:
            self.offset += len(self.output) - MAX_OUTPUT
            self.output = self.output[-MAX_OUTPUT:]
        self.run_output += text
        if len(self.run_output) > MAX_OUTPUT * 2:
            self.run_output = self.run_output[-MAX_OUTPUT * 2:]

    def _finish_run(self, post):
        line = post.splitlines()[0] if post.splitlines() else ''
        parts = line.split('|')
        code = None
        if len(parts) >= 3 and parts[0] == '':
            # PowerShell: |True|0
            ok = parts[1].strip().lower() == 'true'
            raw = parts[2].strip()
            if raw and re.fullmatch(r'-?\d+', raw):
                code = int(raw)
            else:
                code = 0 if ok else 1
        elif len(parts) >= 2 and parts[0] == '':
            # cmd: |0
            raw = parts[1].strip()
            if raw and re.fullmatch(r'-?\d+', raw):
                code = int(raw)
        self.exit_code = code
        self.running = False
        self.sentinel = None

    def _read(self, process, session_id):
        decoder = codecs.getincrementaldecoder('utf8')(errors='replace')
        try:
            while True:
                chunk = os.read(process.stdout.fileno(), 4096)
                if not chunk:
                    break
                text = decoder.decode(chunk)
                with self.lock:
                    if session_id != self.session_id:
                        return
                    if self.shell == 'cmd':
                        text = text.replace('__VALP__', '')
                    if self.running and self.sentinel:
                        combined = self.run_output + text
                        index = combined.find(self.sentinel)
                        if index >= 0:
                            before = index - len(self.run_output)
                            if before >= 0:
                                self._append(text[:before])
                            else:
                                cut = -before
                                self.output = self.output[:-cut] if cut <= len(self.output) else ''
                                self.run_output = self.run_output[:-cut] if cut <= len(self.run_output) else ''
                            self._finish_run(combined[index + len(self.sentinel):])
                            continue
                    self._append(text)
        except OSError:
            pass
        finally:
            with self.lock:
                try:
                    tail = decoder.decode(b'', final=True)
                    if tail and session_id == self.session_id:
                        self._append(tail)
                except Exception:
                    pass
                if session_id == self.session_id:
                    if self.running:
                        self.running = False
                        if self.exit_code is None and process.poll() is not None:
                            self.exit_code = process.returncode
                    self.proc = None
                try:
                    process.stdout.close()
                except OSError:
                    pass
                if self.reader is threading.current_thread():
                    self.reader = None

    def _kill(self, process, reader):
        if process is not None and process.poll() is None:
            subprocess.run(['taskkill', '/F', '/T', '/PID', str(process.pid)], capture_output=True,
                           creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0), timeout=8)
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                pass
        if process is not None:
            try:
                if process.stdin:
                    process.stdin.close()
            except OSError:
                pass
        if reader is not None and reader is not threading.current_thread():
            reader.join(timeout=3)

    def _start_session(self, shell, cwd):
        environment = {**os.environ, 'PYTHONUTF8': '1', 'PYTHONIOENCODING': 'utf-8'}
        if shell == 'powershell':
            argv = ['powershell.exe', '-NoLogo', '-NoProfile', '-NoExit', '-Command', '-']
        else:
            argv = ['cmd.exe', '/Q', '/D', '/V:ON', '/K']
        self.proc = subprocess.Popen(argv, cwd=str(cwd), stdin=subprocess.PIPE,
                                     stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                     env=environment, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        self.shell = shell
        self.workspace = str(cwd)
        self.session_id += 1
        self.started = time.time()
        self.reader = threading.Thread(target=self._read, args=(self.proc, self.session_id), daemon=True)
        self.reader.start()
        if shell == 'powershell':
            init = ("[Console]::InputEncoding=[System.Text.Encoding]::UTF8;"
                    "[Console]::OutputEncoding=[System.Text.Encoding]::UTF8;"
                    "$OutputEncoding=[System.Text.Encoding]::UTF8;"
                    "$ProgressPreference='SilentlyContinue'")
        else:
            init = 'prompt __VALP__'
        try:
            self.proc.stdin.write((init + '\n').encode('utf8'))
            self.proc.stdin.flush()
        except OSError:
            pass

    def _drop_session(self, mark=False):
        process = self.proc
        reader = self.reader
        self.session_id += 1
        self.proc = None
        self.reader = None
        self.running = False
        self.sentinel = None
        if mark and self.output:
            self._append('\n[sesión detenida; la próxima orden la reinicia]\n')
        return process, reader

    def start(self, command, shell, cwd):
        if not isinstance(command, str) or not command.strip() or len(command) > 16000:
            raise ValueError('Enter a command (maximum 16000 characters).')
        if shell not in ('powershell', 'cmd'):
            raise ValueError('Unsupported console shell.')
        old = None
        with self.lock:
            if self.running:
                raise ValueError('A command is already running. Stop it first.')
            stale = self.proc is None or self.proc.poll() is not None or self.reader is None or self.shell != shell
            if stale and (self.proc is not None or self.reader is not None):
                old = self._drop_session()
        if old:
            self._kill(*old)
        with self.lock:
            if self.running:
                raise ValueError('A command is already running. Stop it first.')
            if self.proc is None:
                self._start_session(shell, cwd)
            elif self.shell != shell:
                raise ValueError('Cambia de consola cuando la sesión esté inactiva.')
            run_id = uuid.uuid4().hex
            self.run_id = run_id
            self.sentinel = '__VAL_DONE__' + run_id + '__'
            self.run_output = ''
            self.exit_code = None
            self.running = True
            label = 'PS ' if shell == 'powershell' else 'CMD '
            self._append('\n' + label + str(cwd) + '> ' + command + '\n')
            if shell == 'powershell':
                if self.workspace != str(cwd):
                    self.proc.stdin.write(('Set-Location -LiteralPath ' + _ps_quote(cwd) + '\n').encode('utf8'))
                    self.workspace = str(cwd)
                script = ('$global:LASTEXITCODE=$null\n' + command + '\n'
                          '$__val_ok=$?\n$__val_code=$LASTEXITCODE\n'
                          'Write-Output (' + _ps_quote(self.sentinel) + " + '|' + [string]$__val_ok + '|' + [string]$__val_code)\n")
                self.proc.stdin.write(script.encode('utf8'))
            else:
                if self.workspace != str(cwd):
                    self.proc.stdin.write(('cd /d "' + str(cwd) + '"\n').encode('utf8'))
                    self.workspace = str(cwd)
                script = (command + '\n' + 'echo ' + self.sentinel + '^|!errorlevel!\n')
                self.proc.stdin.write(script.encode('utf8'))
            try:
                self.proc.stdin.flush()
            except OSError:
                self.running = False
                raise ValueError('La sesión de consola se cerró. Inténtalo de nuevo.')
            return self.snapshot()

    def stop(self):
        with self.lock:
            if self.proc is None and not self.running:
                return self.snapshot()
            old = self._drop_session(mark=True)
        self._kill(*old)
        return self.snapshot()

    def clear(self):
        with self.lock:
            if self.running:
                raise ValueError('Stop the command before clearing its output.')
            self.output = ''
            self.run_output = ''
            self.offset = 0
            self.run_id = None
            self.exit_code = None
            return self.snapshot()

    def close(self):
        with self.lock:
            old = self._drop_session(mark=False)
        self._kill(*old)
