"""pc_mcp: servidor MCP mínimo (stdio) para interactuar con el PC.

Herramientas (descripciones cortas a propósito, para no inflar el prompt):
  fs_list(path)                  lista una carpeta
  fs_read(path, max_chars, offset)       lee un archivo de texto
  fs_write(path, content)        escribe un archivo de texto (crear o reemplazar entero)
  fs_edit(path, old_text, new_text, all) cambia un bloque exacto de un archivo existente
  shell_run(command, timeout, shell) ejecuta cmd o PowerShell y devuelve la salida
  sys_info()                     CPU, RAM, disco y GPU

fs_edit existe por lo que se vio el 2026-11-03 con un modelo local: sin un editor de
reemplazo, el modelo reescribia el fichero entero una y otra vez (56 versiones, 108 bloques)
y nunca guardaba. Es el razon del "Agent-Computer Interface" de SWE-agent (create rechazado si
el fichero ya existe; old_str unico o no se aplica) y de los SEARCH/REPLACE de aider.

Por defecto solo accede a sandbox/. Los comandos del host requieren una
autorización de acceso completo que el modelo no puede establecer.
"""
import json
import base64
import difflib
import os
import pathlib
import subprocess
import sys
import tempfile
import threading
import uuid
import secrets
import shutil
import re
import time
import urllib.error
import urllib.request
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
from file_versions import VERSIONS
from access_policy import AccessDenied, AccessPolicy, workspace_signature

POLICY = AccessPolicy()

for _stream in (sys.stdin, sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="strict")

PROTO = "2025-06-18"
from mcp_options import options

TOOLS = [
    {"name":"project_map","description":"List project files and key symbols on demand, without reading whole files into context.","inputSchema":{"type":"object","properties":{"path":{"type":"string"}},"required":[]}},
    {"name":"file_history","description":"List previous versions of a file, or restore one. Omit revision to list; use a listed revision ID to restore.","inputSchema":{"type":"object","properties":{"path":{"type":"string"},"revision":{"type":"string"}},"required":["path"]}},
    {"name":"code_check","description":"Check file syntax by default. A listed project check ID plus run=true executes commands (full-PC only).","inputSchema":{"type":"object","properties":{"path":{"type":"string"},"check":{"type":"string"},"run":{"type":"boolean"},"timeout":{"type":"integer","minimum":1,"maximum":120}},"required":["path"]}},
    {"name": "draft_resume", "description": "Resume the latest saved draft in this conversation without regenerating it. Takes no arguments.",
     "inputSchema": {"type": "object", "properties": {}}},
    {"name": "fs_list", "description": "List a directory.",
     "inputSchema": {"type": "object", "properties": {"path": {"type": "string", "description": "Relative to the working folder (default .), or an absolute PC path when Full-PC access is enabled."}}}},
    {"name": "fs_read", "description": "Read UTF-8 text. offset continues by character; linea is a 1-based starting line, ventana is the line count.",
     "inputSchema": {"type": "object", "properties": {
         "path": {"type": "string", "description": "Relative to the working folder (e.g. notes.txt), or an absolute PC path when Full-PC access is enabled. Must be a file; use fs_list for directories."},
         "max_chars": {"type": "integer", "minimum": 1, "maximum": 7800, "description": "Characters per part; default 6000."},
         "offset": {"type": "integer", "minimum": 0, "description": "Starting character offset; default 0."},
         "linea": {"type": "integer", "minimum": 1, "description": "First line, 1-based."},
         "ventana": {"type": "integer", "minimum": 1, "maximum": 240, "description": "Number of lines; default 100."}},
         "required": ["path"]}},
    {"name": "doc_read", "description": "Extract text, tables and metadata from PDF, Word (.docx), Excel (.xlsx), PowerPoint (.pptx), OpenDocument, EPUB, RTF, HTML, XML and CSV.",
     "inputSchema": {"type": "object", "properties": {
         "path": {"type": "string", "description": "Relative to the working folder (e.g. report.pdf), or an absolute PC path when Full-PC access is enabled."},
         "pages": {"type": "string", "description": "Optional 1-based page/slide/sheet range, e.g. '1-5' or '1,3,6'."},
         "mode": {"type": "string", "enum": ["auto", "markdown", "text", "tables"], "description": "Optional extraction format override."},
         "offset": {"type": "integer", "minimum": 0, "description": "Starting character offset; default 0."},
         "max_chars": {"type": "integer", "minimum": 0, "description": "Max characters to return (0 = unlimited; omit to use MCP Options)."}},
         "required": ["path"]}},
    {"name": "fs_write", "description": "Write UTF-8 text; creates parent directories and replaces existing files.",
     "inputSchema": {"type": "object", "properties": {
         "path": {"type": "string", "description": "Relative to the working folder (e.g. notes.txt), or an absolute PC path when Full-PC access is enabled."},
         "content": {"type": "string", "description": "UTF-8 text."}}, "required": ["path", "content"]}},
    # fs_edit es la via para cambiar algo que ya esta escrito: el reemplazo exige coincidencia
    # unica, asi que el modelo no puede limitarse a vomitar otra version del fichero entero.
    # Lote todo-o-nada: varios cambios en una sola llamada ahorran rondas de prefill, y si uno no
    # cuadra no se escribe nada (así lo hace Unsloth con edits:[{old_string,new_string}]).
    {"name": "fs_edit", "description": "Replace exact blocks in an existing file. Use old_text/new_text or atomic edits=[{old_text,new_text}]. Match once, or set all=true.",
     "inputSchema": {"type": "object", "properties": {
         "path": {"type": "string", "description": "Relative to the working folder (e.g. notes.txt), or an absolute PC path when Full-PC access is enabled."},
         "old_text": {"type": "string", "description": "Exact text to replace."},
         "new_text": {"type": "string", "description": "Replacement; empty to delete."},
         "all": {"type": "boolean", "description": "Replace every match; default false."},
         "edits": {"type": "array", "maxItems": 12, "description": "Atomic list of replacements.",
                   "items": {"type": "object", "properties": {
                       "old_text": {"type": "string"}, "new_text": {"type": "string"},
                       "all": {"type": "boolean"}}, "required": ["old_text", "new_text"]}}},
         "required": ["path"]}},
    {"name": "web_render", "description": "Render HTML; report console errors and scene/camera/instance diagnostics. Not a visual quality guarantee.",
     "inputSchema": {"type": "object", "properties": {
         "path": {"type": "string", "description": "Relative to the working folder (e.g. index.html), or an absolute PC path when Full-PC access is enabled."},
         "espera_ms": {"type": "integer", "minimum": 500, "maximum": 40000,
                       "description": "Wait in milliseconds; default 2200."},
         "pintura": {"type": "boolean", "description": "Sample canvas pixels; slower."},
         "diagnostics": {"type":"boolean","description":"Inspect scene geometry and transforms; default true."}},
         "required": ["path"]}},
    # Copiar/pegar por referencia: lo que mueve texto sin que el modelo lo teclee token a token.
    {"name": "fs_search", "description": "Search files by glob and/or text/regex in path (default '.', or any directory when Full-PC access is enabled). Skips binary files and symlinks; returns bounded path/line matches.",
     "inputSchema": {"type": "object", "properties": {
         "path": {"type": "string", "description": "Directory or file to search; default ."},
         "glob": {"type": "string", "description": "Glob such as **/*.py; default **/*"},
         "contains": {"type": "string", "description": "Literal text or regex to find inside text files."},
         "regex": {"type": "boolean", "description": "Treat contains as a regular expression."},
         "case_sensitive": {"type": "boolean", "description": "Default false."},
         "max_results": {"type": "integer", "minimum": 1, "maximum": 500, "description": "Default 80."},
         "max_file_bytes": {"type": "integer", "minimum": 1024, "maximum": 5000000, "description": "Skip larger files; default 2 MB."}}}},
    {"name": "fs_manage", "description": "Create, delete, move, copy or inspect files/directories. Destructive actions require recursive=true for non-empty directories.",
     "inputSchema": {"type": "object", "properties": {
         "action": {"type": "string", "enum": ["mkdir", "delete", "move", "copy", "stat"]},
         "path": {"type": "string", "description": "Source path."},
         "destination": {"type": "string", "description": "Destination for move/copy."},
         "recursive": {"type": "boolean", "description": "Required for non-empty directory delete/copy."},
         "overwrite": {"type": "boolean", "description": "Replace destination if it exists."}},
         "required": ["action", "path"]}},
    {"name": "fs_copy", "description": "Copy existing text without retyping. modo: nuevo=create, pegar_antes=insert before ancla, pegar_despues=insert after, reemplazar=replace ancla. cortar=true moves. Omit linea/hasta for the whole file.",
     "inputSchema": {"type": "object", "properties": {
         "desde": {"type": "string", "description": "Source path."},
         "destino": {"type": "string", "description": "Destination path."},
         "linea": {"type": "integer", "minimum": 1, "description": "First line, 1-based."},
         "hasta": {"type": "integer", "minimum": 1, "description": "Last line, inclusive."},
         "ancla": {"type": "string", "description": "Destination line or range, e.g. 24 or 24-31."},
         "modo": {"type": "string", "enum": ["nuevo", "pegar_antes", "pegar_despues", "reemplazar"]},
         "cortar": {"type": "boolean", "description": "Move instead of copying."}},
         "required": ["desde", "destino"]}},
    {"name": "shell_run", "description": "Run a Windows cmd (default) or PowerShell command; not bash, so no ls/cat/which. "
        "Returns exit code, stdout and stderr. With limited access only CMD built-ins and python run; use fs_list/fs_read for files.",
     "inputSchema": {"type": "object", "properties": {
         "command": {"type": "string", "description": "Command to run."},
         "shell": {"type": "string", "enum": ["cmd", "powershell"], "default": "cmd"},
         "timeout": {"type": "integer", "minimum": 5, "maximum": 300, "description": "Seconds; omit for user settings."},
         "background": {"type": "boolean", "description": "Start without waiting; use job_wait once with the returned id."}}, "required": ["command"]}},
    {"name": "job_wait", "description": "Wait for a background shell job to finish and return its output once. Prefer this over repeated job_status polling.",
     "inputSchema": {"type": "object", "properties": {"job_id": {"type": "string"}, "timeout": {"type": "integer", "minimum": 1, "maximum": 600, "description": "Seconds; default 60."}}, "required": ["job_id"]}},
    {"name": "job_status", "description": "Return the current status and last output of a background job without waiting.",
     "inputSchema": {"type": "object", "properties": {"job_id": {"type": "string"}}, "required": ["job_id"]}},
    {"name": "job_list", "description": "List background shell jobs and their state.", "inputSchema": {"type": "object", "properties": {}}},
    {"name": "job_stop", "description": "Stop a background shell job and its process tree.",
     "inputSchema": {"type": "object", "properties": {"job_id": {"type": "string"}}, "required": ["job_id"]}},
    {"name": "sys_info", "description": "Exact CPU, OS, RAM, disks and GPU.",
     "inputSchema": {"type": "object", "properties": {}}},
    {"name": "browser", "description": "Control the visible V-Agent browser. open/navigate load a URL; snapshot returns a short text excerpt plus selectors for interactive elements; text reads the page; click/fill use selectors; press sends a key; eval runs JavaScript. The user sees the same window.",
     "inputSchema": {"type": "object", "properties": {
         "action": {"type": "string", "enum": ["open","navigate","snapshot","text","click","fill","press","eval","back","forward","reload","close"]},
         "url": {"type": "string", "description": "http or https URL for open/navigate."},
         "selector": {"type": "string", "description": "CSS selector, usually from snapshot."},
         "text": {"type": "string", "description": "Text for fill."},
         "key": {"type": "string", "description": "Key for press, e.g. Enter."},
         "script": {"type": "string", "description": "JavaScript expression for eval."},
         "max_chars": {"type": "integer", "minimum": 500, "maximum": 20000, "description": "Text limit; snapshot prioritizes selectors."},
         "timeout": {"type": "integer", "minimum": 5, "maximum": 90, "description": "Seconds; default 40."}},
         "required": ["action"]}},
    {"name": "console", "description": "Run in the shared V-Agent console that the user sees. The shell session persists cwd and environment. Actions: run, status, stop, clear. Full-PC only.",
     "inputSchema": {"type": "object", "properties": {
         "action": {"type": "string", "enum": ["run","status","stop","clear"], "default": "run"},
         "command": {"type": "string", "description": "Command; may span lines."},
         "shell": {"type": "string", "enum": ["powershell","cmd"], "default": "powershell"},
         "timeout": {"type": "integer", "minimum": 5, "maximum": 300, "description": "Seconds to wait; default 90."}},
         "required": ["action"]}},
]


JOBS = {}
JOBS_LOCK = threading.RLock()


def _background_argv(command: str, mode: str):
    windows = os.environ.get("SystemRoot", r"C:\Windows")
    environment = os.environ.copy()
    environment.pop('STRATA_PC_ACCESS_KEY', None)
    if mode == "cmd":
        executable = os.path.join(windows, "System32", "cmd.exe")
        environment["STRATA_MCP_COMMAND"] = command
        argv = (f'"{executable}" /d /v:on /s /c "chcp 65001>nul & '
                f'"{executable}" /d /v:off /s /c "!STRATA_MCP_COMMAND!""')
    elif mode == "powershell":
        executable = os.path.join(windows, "System32", "WindowsPowerShell", "v1.0", "powershell.exe")
        nl = chr(10)
        script = ("$ProgressPreference = 'SilentlyContinue'; "
                  "[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false); "
                  "$OutputEncoding = [Console]::OutputEncoding; $ErrorActionPreference = 'Stop';" + nl +
                  "try { & {" + nl + command + nl + "}" + nl +
                  "if (-not $?) { if ($LASTEXITCODE) { exit $LASTEXITCODE }; exit 1 }" + nl +
                  "} catch { [Console]::Error.WriteLine($_.ToString()); exit 1 }")
        encoded = base64.b64encode(script.encode("utf-16-le")).decode("ascii")
        argv = [executable, "-NoLogo", "-NoProfile", "-NonInteractive", "-OutputFormat", "Text", "-EncodedCommand", encoded]
    else:
        raise ValueError("shell must be cmd or powershell")
    return argv, environment

def _start_background(args, policy):
    command = args.get("command")
    if not isinstance(command, str) or not command.strip():
        raise ValueError("command must contain a non-empty command string")
    with JOBS_LOCK:
        if len([job for job in JOBS.values() if job["process"].poll() is None]) >= 12:
            raise ValueError("Too many background jobs running; wait for or stop one first.")
    argv, environment = _background_argv(command, args.get("shell", "cmd"))
    startup = subprocess.STARTUPINFO()
    startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    startup.wShowWindow = subprocess.SW_HIDE
    process = subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, cwd=str(policy.root),
                               env=environment, text=True, encoding="utf-8", errors="replace",
                               bufsize=1, creationflags=subprocess.CREATE_NEW_CONSOLE, startupinfo=startup)
    ident = uuid.uuid4().hex[:10]
    job = {"id": ident, "process": process, "output": [], "chars": 0, "command": command[:500],
           "started": time.time(), "exit": None}
    with JOBS_LOCK:
        JOBS[ident] = job
    def reader():
        assert process.stdout is not None
        for line in process.stdout:
            with JOBS_LOCK:
                if job["chars"] < 200000:
                    job["output"].append(line)
                    job["chars"] += len(line)
        process.wait()
        with JOBS_LOCK:
            job["exit"] = process.returncode
    threading.Thread(target=reader, daemon=True).start()
    return json.dumps({"job_id": ident, "status": "running", "command": command[:500],
                       "hint": "Use job_wait once with this id; do not poll."}, ensure_ascii=False)


def _job_view(job, include_output=True):
    text = "".join(job["output"])
    code = job["process"].poll()
    return {"job_id": job["id"], "status": "running" if code is None else "completed",
            "exit_code": code, "chars": job["chars"], "elapsed_s": round(time.time() - job["started"], 1),
            **({"output": text[-40000:]} if include_output else {})}


def _job(job_id):
    with JOBS_LOCK:
        job = JOBS.get(str(job_id))
    if job is None:
        raise ValueError("job_id does not exist.")
    return job


def job_wait(args):
    job = _job(args.get("job_id"))
    timeout = max(1, min(int(args.get("timeout") or 60), 600))
    try:
        job["process"].wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        pass
    with JOBS_LOCK:
        return json.dumps(_job_view(job), ensure_ascii=False)


def job_status(args):
    job = _job(args.get("job_id"))
    with JOBS_LOCK:
        return json.dumps(_job_view(job, include_output=True), ensure_ascii=False)


def job_list(args):
    with JOBS_LOCK:
        return json.dumps([_job_view(job, include_output=False) for job in JOBS.values()], ensure_ascii=False)


def job_stop(args):
    job = _job(args.get("job_id"))
    if job["process"].poll() is None:
        subprocess.run([os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32", "taskkill.exe"),
                        "/F", "/T", "/PID", str(job["process"].pid)],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=15)
    with JOBS_LOCK:
        return json.dumps(_job_view(job), ensure_ascii=False)


def ok(text):
    cap=options('pc')['max_result_chars']
    if len(text) > cap:
        # Cabeza y cola, como Goose/Crush: lo que suele importar de un comando que falla esta al
        # principio (lo que intento) y al final (el error). Quedarse solo con la cabeza perdia justo
        # la linea del fallo, y el modelo volvía a escribir el fichero entero "por si acaso".
        cabeza = cap - 260
        trozo = text[:cabeza] + "\n[truncated %d characters: continue with offset/linea for that section]\n" % (
            len(text) - cabeza - 200) + text[-200:]
        return {"content": [{"type": "text", "text": trozo}]}
    return {"content": [{"type": "text", "text": text}]}


def command_failure_hint(command, stderr):
    """Local compatibility hint only on a matching failure; never rewrite commands.

    Keep normal schemas/prompts and successful outputs unchanged. Do not read
    credential files or print authentication tokens to diagnose an old HF API.
    """
    if not shutil.which('hf'):
        return ''
    legacy_cli = re.search(r'(?i)\bhuggingface-cli(?:\.exe)?\b', command) and (
        'no se reconoce' in stderr or 'not recognized' in stderr or 'not found' in stderr)
    legacy_module = 'huggingface_hub.__main__' in stderr
    legacy_api = "cannot import name 'HfFolder'" in stderr and 'huggingface_hub' in stderr
    if legacy_cli or legacy_module or legacy_api:
        return '\n[hint] Installed HF CLI: hf. Account (read-only): hf auth whoami. Commands: hf --help.'
    return ''


def shell_run(args, policy=None):
    policy = POLICY if policy is None else policy
    command = args.get("command")
    if not isinstance(command, str) or not command.strip():
        raise ValueError("command must contain a shell command.")
    mode = args.get("shell", "cmd")
    cwd = str(policy.root)
    timeout = max(5, min(int(args.get("timeout") or options("pc")["command_timeout"]), 300))
    windows = os.environ.get("SystemRoot", r"C:\Windows")
    environment = os.environ.copy()
    environment.pop('STRATA_PC_ACCESS_KEY', None)
    if mode == "cmd":
        # cmd.exe does not understand the backslash-escaped quotes produced by
        # subprocess.list2cmdline. Pass its /s /c command line verbatim instead.
        executable = os.path.join(windows, "System32", "cmd.exe")
        # Parse the user's command only AFTER switching code pages; otherwise
        # cmd irreversibly converts Unicode arguments using the old OEM page.
        environment["STRATA_MCP_COMMAND"] = command
        argv = (f'"{executable}" /d /v:on /s /c "chcp 65001>nul & '
                f'"{executable}" /d /v:off /s /c "!STRATA_MCP_COMMAND!""')
    elif mode == "powershell":
        executable = os.path.join(windows, "System32", "WindowsPowerShell", "v1.0", "powershell.exe")
        script = ("$ProgressPreference = 'SilentlyContinue'; "
                  "[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false); "
                  "$OutputEncoding = [Console]::OutputEncoding; $ErrorActionPreference = 'Stop';\n"
                  "try { & {\n" + command + "\n}\n"
                  "if (-not $?) { if ($LASTEXITCODE) { exit $LASTEXITCODE }; exit 1 }\n"
                  "} catch { [Console]::Error.WriteLine($_.ToString()); exit 1 }")
        encoded = base64.b64encode(script.encode("utf-16-le")).decode("ascii")
        argv = [executable, "-NoLogo", "-NoProfile", "-NonInteractive", "-OutputFormat", "Text", "-EncodedCommand", encoded]
    else:
        raise ValueError("shell must be cmd or powershell")
    # A hidden console lets chcp take effect for cmd and its children. Without a
    # console Windows falls back to OEM encoding and loses non-ASCII characters.
    startup = subprocess.STARTUPINFO()
    startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    startup.wShowWindow = subprocess.SW_HIDE
    # Temp files avoid pipe handle inheritance deadlocks when a command spawns a GUI app (e.g. start notepad).
    timed_out = False
    with tempfile.TemporaryFile() as out_file, tempfile.TemporaryFile() as err_file:
        p = subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=out_file, stderr=err_file, cwd=cwd,
                             env=environment, creationflags=subprocess.CREATE_NEW_CONSOLE, startupinfo=startup)
        try:
            p.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            timed_out = True
            subprocess.run([os.path.join(windows, "System32", "taskkill.exe"), "/F", "/T", "/PID", str(p.pid)],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=10,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            p.kill()
            try:
                p.wait(timeout=2)
            except subprocess.TimeoutExpired:
                pass
        out_file.seek(0)
        err_file.seek(0)
        stdout = out_file.read()
        stderr = err_file.read()
    out = stdout.decode("utf-8", "replace").strip()
    err = stderr.decode("utf-8", "replace").strip()
    result = f"exit={p.returncode}\nshell={mode}\ncwd={cwd}\n[stdout]\n" + (out or "(no output)")
    if err:
        result += "\n[stderr]\n" + err
    if timed_out:
        raise RuntimeError(f"Timed out ({timeout}s).\n" + result)
    if p.returncode:
        raise RuntimeError(result + command_failure_hint(command, err))
    return result


def _raya(texto, posicion):
    """Numero de linea (1-based) de una posicion dentro de `texto`."""
    return texto.count("\n", 0, posicion) + 1


def _busca(texto, viejo):
    """([(inicio, fin)], modo) donde encaja `viejo`: exacto, o tolerando el sangrado.

    Lo del sangrado es de aider (replace_part_with_missing_leading_whitespace): el modelo
    reescribe el bloque con otra indentacion y aun asi se puede aplicar, en vez de gastarse
    una ronda pidiendole que lo intente otra vez.
    """
    spans, i = [], texto.find(viejo)
    while i >= 0:
        spans.append((i, i + len(viejo)))
        i = texto.find(viejo, i + 1)
    if spans:
        return spans, "exact"
    lineas = texto.splitlines(keepends=True)
    objetivo = [l.strip() for l in viejo.splitlines()]
    if not objetivo:
        return [], "empty"
    # Se comparan lineas completas sin su sangrado (ni el fin de linea: el modelo casi nunca
    # deja el salto de linea donde lo deja el fichero).
    despojadas = [l.strip() for l in lineas]
    k = len(objetivo)
    for inicio in range(len(despojadas) - k + 1):
        if despojadas[inicio:inicio + k] == objetivo:
            a = sum(len(l) for l in lineas[:inicio])
            cubierto = "".join(lineas[inicio:inicio + k])
            # El span se queda en el texto de las lineas, sin su salto de linea final: si no,
            # un old_text de una linea se comeria el salto y juntaria la linea siguiente.
            fin = a + len(cubierto) - (len(cubierto) - len(cubierto.rstrip("\r\n")))
            spans.append((a, fin))
    return spans, "indent-tolerant"


def _cercanas(texto, viejo):
    """Pistas cuando no encontro nada: lineas parecidas con su numero (el 'Did you mean' de aider)."""
    lineas = texto.splitlines()
    objetivo = [l.strip() for l in viejo.splitlines() if l.strip()][:3]
    pistas = []
    for q in objetivo:
        for n, l in enumerate(lineas, 1):
            si_esta = q in l
            si_no = (not si_esta) and difflib.SequenceMatcher(None, q, l.strip()).ratio() > 0.75
            if si_esta or si_no:
                pistas.append("  line %d: %s" % (n, l.strip()[:90]))
                break
    if not pistas:
        return ""
    return ("\nSimilar text:\n%s\nRead this area with fs_read, then retry fs_edit with the "
            "exact original text, including indentation." % "\n".join(pistas[:3]))


def _errores_nuevos(antes, despues):
    """Los errores de la version nueva que no estaban ya en la anterior (umbral de SWE-agent)."""
    return [e for e in despues.get("errores", []) if e not in set(antes.get("errores", []))]


def aviso_escritura(path, contenido):
    """Aviso cuando lo escrito llega cortado, sin bloquear la escritura.

    Visto en vivo el 2026-11-03: al modelo le pidieron una llamada TRUNCADA a proposito y el
    motor la completó él (cadena sin cerrar incluida), así que llegó como llamada válida y el
    agente escribió 14 caracteres en un .html. El fichero se escribe igual -eso no lo decide el
    harness sin avisar- pero el texto de vuelta le dice que está incompleto, para que no narre
    un éxito sobre un documento a medias.
    """
    suf = os.path.splitext(str(path))[1].lower()
    if suf not in (".html", ".htm", ".js", ".mjs", ".cjs", ".py", ".json"):
        return ""
    avisos = []
    if suf in (".html", ".htm") and "</html>" not in str(contenido).lower():
        avisos.append("No closing </html> tag; this may be an HTML fragment. Check completeness only if a full document was requested.")
    if not avisos:
        return ""
    return "\n[File note] " + "; ".join(avisos)


def recibo_diff(anterior, nuevo, contexto=2, max_chars=1100):
    """Recibo del cambio en diff unificado, con los numeros de linea de cada bloque.

    Copiado de como lo hace Unsloth Studio (`_edit_file_receipt`): en vez de obligar al modelo a
    releerse el fichero para confirmar que su edicion aterrizo -que cuesta prefill y otra ronda-,
    se le devuelve el diff. Corto y con `n=2` de contexto para no inflar el contexto.
    """
    import difflib
    lineas = list(difflib.unified_diff(anterior.splitlines(), nuevo.splitlines(),
                                       fromfile="before", tofile="after", lineterm="", n=contexto))
    if not lineas:
        return "\nNo change: file is unchanged."
    cuerpo = "\n".join(lineas[2:])
    if len(cuerpo) > max_chars:
        cuerpo = cuerpo[:max_chars] + "\n... (diff truncated)"
    return "\nChange diff:\n" + cuerpo


def pista_de_linea(errores):
    """De un error de consola con pila, decir que linea es y con que ventana mirarla.

    Es lo que convierte el informe en una edicion dirigida: el modelo sabe el numero, pide ese
    corte con fs_read y cambia solo ese bloque con fs_edit.
    """
    pistas = []
    for e in (errores or [])[:3]:
        m = re.search(r"([\w.\-]+\.html\.strata-candidata\.html|[\w.\-]+\.html):(\d+)", str(e))
        if not m:
            continue
        n = int(m.group(2))
        pistas.append("line %d (read fs_read(path, linea=%d, ventana=24), then edit that block with "
                      "fs_edit; old_text excludes the line number)" % (n, max(1, n - 9)))
    if not pistas:
        return ""
    return "\nInspect: " + "; ".join(dict.fromkeys(pistas)) + "."


def comprueba_ejecucion(path):
    """Tras escribir o editar una pagina, se abre de verdad y se trae lo que salio.

    Es la pieza que falta para poder 'editar solo lo errado': sin ejecutarla, el modelo solo puede
    volver a escribir el fichero entero a ver si ahora suena bien. Con la consola del navegador en
    la mano y el numero de linea del fallo, va con fs_read(linea=...) y fs_edit al punto.

    Espera CORTA a proposito (STRATA_AGENT_WRITE_RENDER_MS, 1500 ms): esto va en el resultado de
    cada escritura, y los errores que importan -import que falla, SyntaxError, variable sin definir
    en el modulo- salen en el primer segundo. Medido: sin teto fijo cada escritura costaba 45-78 s
    con una escena de ~20k voxels en SwiftShader. Las escenas completas se comprueban con
    pc__web_render, donde el modelo pone la espera que haga falta. Se apaga con
    STRATA_AGENT_WRITE_RENDER=0.
    """
    suf = os.path.splitext(str(path))[1].lower()
    if suf not in (".html", ".htm"):
        return ""
    if os.environ.get("STRATA_AGENT_WRITE_RENDER", "1") == "0":
        return ""
    espera = int(os.environ.get("STRATA_AGENT_WRITE_RENDER_MS", "1500"))
    # 3D pages (Three.js / WebGL / canvas) need a few more seconds for the module to load, and they
    # get the scene diagnostics (camera, instances, moving parts penetrating static voxels) in the
    # write result itself: small models rarely call pc__web_render on their own. Still capped.
    try:
        fuente = pathlib.Path(path).read_text(encoding="utf-8", errors="replace")[:400000]
    except OSError:
        fuente = ""
    escena = bool(re.search(r"\bthree\b|three\.module|webgl|<canvas|babylon", fuente, re.I))
    if escena:
        espera = max(espera, int(os.environ.get("STRATA_AGENT_WRITE_RENDER_3D_MS", "4500")))
    try:
        import render_check
        informe = render_check.resumen(path, espera_ms=espera,diagnostics=escena)
    except Exception as error:
        return "\n(browser check skipped: %s)" % str(error)[:90]
    if informe.get("error"):
        # No es la pagina rota: es el entorno que no llego a verla terminar. Decirlo como error
        # mandaria al modelo a arreglar algo que no esta mal.
        return ("\n(Check did not finish within %d ms: %s. This does not prove the page is broken. "
                "Use pc__web_render with a larger espera_ms for a full check.)"
                % (espera, informe["error"]))
    texto = informe.get("resumen") or ""
    if informe.get("errores"):
        texto += pista_de_linea(informe["errores"])
        texto += ("\nDo not rewrite the whole file. Edit the affected block with fs_edit "
                  "(exact old_text without line numbers), use atomic edits=[...], or "
                  "move existing text with fs_copy by line number without retyping it.")
    return "\n" + texto


def ejecuta_contenido(contenido, original):
    """Ejecutar ESTE contenido en el navegador, en una copia al lado del original.

    La copia va en la misma carpeta y con la misma extension para que las rutas relativas y el CDN
    se comporten igual que en el fichero de verdad. Devuelve el informe de render_check.
    """
    import render_check
    sufijo = os.path.splitext(str(original))[1] or ".html"
    tmp = pathlib.Path(str(original) + ".strata-candidata" + sufijo)
    try:
        with open(tmp, "w", encoding="utf-8", newline="") as f:
            f.write(contenido)
        return render_check.resumen(str(tmp),diagnostics=False)
    finally:
        try:
            tmp.unlink()
        except OSError:
            pass


def _clave_error(e):
    """El error reducido a su mensaje, sin fichero ni numero de linea.

    Dos cosas hacian imposible comparar tal cual: (1) la copia candidata se prueba como
    `pagina.strata-candidata.html` y el navegador escribe ese nombre en la cabecera y en la pila,
    y (2) en cuanto el cambio añade una linea, la MISMA excepcion sube de posicion. Comparar las
    cadenas completas convertia un error preexistente en "nuevo" y rechazaba cambios inocentes.
    Se guarda solo la primera linea (el mensaje de la excepcion), que es lo que identifica el fallo.
    """
    primero = str(e).splitlines()[0] if str(e).strip() else ""
    primero = re.sub(r"[\w.\-]*\.strata-candidata\.html", " ", primero)
    primero = re.sub(r"[\w.\-]+\.(html|htm|js|mjs)", " ", primero)
    return " ".join(primero.lower().split())


def errores_nuevos(informe, anterior):
    """Solo los errores de consola que la pagina no daba antes del cambio (regla de SWE-agent)."""
    if not informe or not (informe.get("errores") or []):
        return []
    previos = {_clave_error(e) for e in ((anterior or {}).get("errores") or [])}
    return [e for e in informe["errores"] if _clave_error(e) not in previos]


def _rango(valor, por_defecto=None):
    """'12' -> (12,12); '12-14' -> (12,14); nada -> por_defecto."""
    if valor is None or valor == "":
        return por_defecto
    texto = str(valor).strip()
    if "-" in texto:
        a, b = texto.split("-", 1)
        return int(a), int(b)
    n = int(texto)
    return n, n


def _corta_escribe(path, texto, prefijo, workspace=None):
    """Escribir entero, atomico (temporal + replace + fsync), como fs_write/fs_edit."""
    if workspace is not None:
        VERSIONS.capture(path, workspace)
    parent = os.path.dirname(os.path.abspath(path))
    os.makedirs(parent, exist_ok=True)
    pending = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", newline="", dir=parent,
                                         prefix=prefijo, suffix=".tmp", delete=False) as f:
            pending = f.name
            f.write(texto)
            f.flush()
            os.fsync(f.fileno())
        os.replace(pending, path)
        pending = None
    finally:
        if pending is not None:
            os.unlink(pending)


def fs_copy(args, full_access, policy=None):
    policy = POLICY if policy is None else policy
    """Copiar/pegar por referencia: mueve texto de un fichero a otro SIN que el modelo lo teclee.

    Motivo medido: con ~56 tokens/s de decodificacion, "arreglar una linea" volviendo a escribir
    un HTML de 20 KB cuesta minutos y miles de tokens de contexto - y era lo que producia las 56
    versiones. Aqui el modelo dice de donde y a donde (lineas), y el texto viaja por disco.
    """
    destino_s, origen_s = args.get("destino"), args.get("desde")
    if not isinstance(destino_s, str) or not destino_s.strip():
        raise ValueError("destino must contain a file path")
    if not isinstance(origen_s, str) or not origen_s.strip():
        raise ValueError("desde must contain a source file path")
    destino = policy.path(destino_s, full_access)
    origen = policy.path(origen_s, full_access)
    if not os.path.exists(origen):
        raise ValueError("source file does not exist: %s" % origen)
    if os.path.isdir(origen):
        raise ValueError("%s is a directory, not a text file; use fs_manage to copy or move directories." % origen)
    if os.path.isdir(destino):
        raise ValueError("%s is a directory; pass a destination file path to fs_copy or use fs_manage." % destino)
    modo = str(args.get("modo") or "").strip().lower() or None
    with open(origen, "r", encoding="utf-8-sig", errors="strict") as f:
        lineas_origen = f.read().splitlines(keepends=True)
    total_o = len(lineas_origen)
    a, b = _rango(args.get("linea"), (1, total_o)) if args.get("linea") not in (None, "") else (1, total_o)
    if args.get("hasta") is not None and args.get("hasta") != "":
        b = int(args["hasta"])
    if not (1 <= a <= total_o) or not (a <= b <= total_o):
        raise ValueError("line range %d-%d is out of bounds for %s (%d lines)" % (a, b, os.path.basename(origen), total_o))
    trozo = "".join(lineas_origen[a - 1:b])
    si_mismo = os.path.abspath(str(origen)) == os.path.abspath(str(destino))
    if not os.path.exists(destino) and modo not in (None, "nuevo"):
        raise ValueError("%s does not exist; use modo='nuevo' (or fs_write) to create it." % destino)
    texto = "" if not os.path.exists(destino) else open(destino, encoding="utf-8-sig", errors="strict").read()
    lineas_destino = texto.splitlines(keepends=True) if texto else []
    if modo in (None, "nuevo"):
        if texto.strip() and modo is None and not si_mismo and len(lineas_destino) > 3:
            raise ValueError("%s already exists with %d lines; specify modo: reemplazar, pegar_antes, or "
                             "pegar_despues (with ancla), or nuevo to overwrite it." % (os.path.basename(destino),
                                                                                  len(lineas_destino)))
        candidato = trozo if modo == "nuevo" or not texto else "".join(lineas_destino) + trozo
    elif modo in ("pegar_antes", "pegar_despues"):
        if args.get("ancla") in (None, ""):
            raise ValueError("ancla is required: destination line number to paste at (e.g. 24)")
        c = int(_rango(args.get("ancla"))[0])
        if not (1 <= c <= max(1, len(lineas_destino))):
            raise ValueError("ancla %d is out of bounds for destination (%d lines)" % (c, len(lineas_destino)))
        i = c - 1 if modo == "pegar_antes" else c
        candidato = "".join(lineas_destino[:i]) + trozo + "".join(lineas_destino[i:])
    elif modo == "reemplazar":
        if args.get("ancla") in (None, ""):
            raise ValueError("ancla is required: destination line or range to replace (e.g. 24 or 24-31)")
        c, d = _rango(args.get("ancla"))
        if not (1 <= c <= len(lineas_destino)) or not (c <= d <= len(lineas_destino)):
            raise ValueError("ancla %s is out of bounds for destination (%d lines)" % (args.get("ancla"), len(lineas_destino)))
        candidato = "".join(lineas_destino[:c - 1]) + trozo + "".join(lineas_destino[d:])
    else:
        raise ValueError("invalid modo; use nuevo, pegar_antes, pegar_despues, or reemplazar")
    if args.get("cortar"):
        if si_mismo:
            resto = lineas_origen[:a - 1] + lineas_origen[b:]
            c = int(_rango(args.get("ancla"))[0]) if args.get("ancla") not in (None, "") else len(resto)
            if modo == "reemplazar":
                raise ValueError("cannot replace and cut within the same file at the same time; "
                                 "do it in two calls or without cortar=true")
            desplazado = c - (b - a + 1) if c > b else c
            i = desplazado - 1 if modo == "pegar_antes" else desplazado
            i = max(0, min(i, len(resto)))
            candidato = "".join(resto[:i]) + trozo + "".join(resto[i:])
        else:
            _corta_escribe(origen, "".join(lineas_origen[:a - 1] + lineas_origen[b:]), ".strata-cut-",policy.root)
    try:_corta_escribe(destino, candidato, ".strata-copy-",policy.root)
    except Exception:
        if args.get('cortar') and not si_mismo:_corta_escribe(origen,''.join(lineas_origen),'.strata-rollback-',policy.root)
        raise
    delta = candidato.count("\n") - texto.count("\n")
    n = b - a + 1
    accion = ("moved" if args.get("cortar") else "copied")
    informe = ("%d %s %s from %s (%s) to %s: %+d line%s, %d chars"
               % (n, "line" if n == 1 else "lines", accion,
                  os.path.basename(str(origen)),
                  "%d-%d" % (a, b), os.path.basename(str(destino)), delta,
                  "" if delta in (-1, 1) else "s", len(candidato)))
    salida = "%s%s" % ("pasted: " if modo != "reemplazar" else "replaced: ", informe)
    if args.get("cortar"):
        salida += " (cut from source%s)" % (", removed %d lines from %s" % (b - a + 1,
                                                                                  os.path.basename(str(origen)))
                                                 if not si_mismo else "")
    if not texto:
        salida += "\nDestination file created."
    _clear_resolved_drafts(policy, destino)
    recibo = recibo_diff(texto, candidato) if texto else "\nreceipt: new file (%d lines)." % (
        candidato.count(chr(10)) + 1)
    return salida + recibo + comprueba_ejecucion(destino) + syntax_report(destino)



# The date note V-Agent appends to the user's last message (agent.date_line). It is never file content:
# a model that copies it to the end of a file gets it removed (current and earlier wording).
DATE_NOTE = re.compile(r"\s*\[(?:System note, not part of the user's message: current date and time|Fecha y hora actual:) "
                       r"\d{4}-\d{2}-\d{2} \d{2}:\d{2} \([^)]*\)\]\s*$")

def syntax_report(path):
    # Every format verify.py can parse is reported on write, not only on an explicit code_check.
    import verify
    if pathlib.Path(path).suffix.lower() not in verify.COMPROBABLES:return ''
    report=verify.verificar_archivo(str(path))
    if report.get('ok') is True:return '\nSyntax checked; program behavior was not tested.'
    if report.get('ok') is None:return '\nSyntax not checked: '+ ' | '.join(report.get('avisos') or [])[:600]
    return '\nSyntax check failed; file is saved. Fix only the failing block with fs_edit: '+ ' | '.join(report.get('errores') or report.get('avisos') or [])[:1200]


def _local_json(path, body=None, timeout=15):
    port = os.environ.get('STRATA_HARNESS_PORT', '19380')
    origin = 'http://127.0.0.1:' + str(port)
    data = json.dumps(body, ensure_ascii=False).encode('utf8') if body is not None else None
    headers = {'Origin': origin}
    if data is not None:
        headers['Content-Type'] = 'application/json'
    request = urllib.request.Request(origin + path, data=data, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode('utf8'))
    except urllib.error.HTTPError as error:
        try:
            payload = json.loads(error.read().decode('utf8'))
        except Exception:
            payload = {}
        raise ValueError(payload.get('error') or ('HTTP ' + str(error.code)))
    except urllib.error.URLError as error:
        if '/console' in path:
            hint = 'Use pc__shell_run to run commands directly.'
            target = 'Visible V-Agent console'
        else:
            hint = 'Use autobrowser__* for headless browser automation or web__http_request to fetch URLs.'
            target = 'Visible V-Agent browser'
        raise ValueError(f'{target} is unavailable at 127.0.0.1:{port} ({error.reason}). {hint}')


_TRACKING_PARAMS = frozenset({
    'fbclid', 'gclid', 'msclkid', 'mc_eid', 'cvid', 'rdr', 'rdrig',
    'ved', 'ei', 'sa', 'opi', 'sca_esv', 'pq', 'sc', 'sk', 'sp', 'lq', 'form',
})


def _clean_snapshot_href(raw):
    value = str(raw or '').strip()
    if not value:
        return ''
    try:
        from urllib.parse import urlparse, parse_qs, parse_qsl, urlencode, urlunparse
        import base64
        parsed = urlparse(value)
        if parsed.hostname and parsed.hostname.endswith('bing.com') and parsed.path.startswith('/ck/a'):
            u_vals = parse_qs(parsed.query).get('u') or []
            if u_vals and u_vals[0].startswith('a1') and len(u_vals[0]) > 2:
                b64 = u_vals[0][2:].replace('-', '+').replace('_', '/')
                b64 += '=' * ((-len(b64)) % 4)
                decoded = base64.b64decode(b64).decode('utf-8', 'ignore')
                if decoded.lower().startswith(('http://', 'https://')):
                    return _clean_snapshot_href(decoded)
            return f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
        kept = [(k, v) for k, v in parse_qsl(parsed.query, keep_blank_values=True)
                if k not in _TRACKING_PARAMS and not k.startswith('utm_')]
        cleaned = urlunparse(parsed._replace(query=urlencode(kept, doseq=True)))
        return cleaned[:180]
    except Exception:
        return value[:180]


def _format_browser_snapshot(result, max_chars):
    if not isinstance(result, dict):
        return json.dumps(result, ensure_ascii=False)
    if result.get('ok') is False:
        return 'Browser error: ' + str(result.get('error') or 'unknown error')
    lines = []
    title = str(result.get('title') or '').strip()
    url = _clean_snapshot_href(result.get('url') or '') or str(result.get('url') or '').strip()
    if title:
        lines.append('title: ' + title)
    if url:
        lines.append('url: ' + url)
    items = result.get('items') if isinstance(result.get('items'), list) else []
    item_lines = []
    for item in items[:60]:
        label = item.get('text') or item.get('name') or item.get('type') or item.get('tag') or ''
        extra = []
        if item.get('type'):
            extra.append(str(item['type'])[:20])
        href = _clean_snapshot_href(item.get('href'))
        if href:
            extra.append(href[:70])
        if item.get('disabled'):
            extra.append('disabled')
        line = '- ' + str(item.get('selector') or '') + ' · ' + str(label)[:70] + ((' · ' + ' · '.join(extra)) if extra else '')
        if sum(len(value) + 1 for value in item_lines) + len(line) > 5000:
            break
        item_lines.append(line)
    text = str(result.get('text') or '')
    budget = 7600 - sum(len(value) + 1 for value in item_lines) - 250
    text_cap = max(500, min(max_chars, budget))
    if len(text) > text_cap:
        text = text[:text_cap] + '\n[text truncated; use action=text to read the page]'
    if text:
        lines.append('')
        lines.append(text)
    if item_lines:
        lines.append('')
        lines.append('Interactive elements:')
        lines.extend(item_lines)
        if len(items) > len(item_lines):
            lines.append('[more elements omitted; run snapshot again or use eval]')
    return '\n'.join(lines)


def _browser_tool(args):
    action = args.get('action')
    allowed = {'open','navigate','snapshot','text','click','fill','press','eval','back','forward','reload','close'}
    if action not in allowed:
        raise ValueError('Unsupported browser action.')
    payload = {key: args[key] for key in ('url','selector','text','key','script','max_chars')
               if args.get(key) is not None}
    timeout = max(5, min(int(args.get('timeout') or 40), 90))
    data = _local_json('/api/harness/browser',
                       {'action': action, 'args': payload, 'timeout': max(1, timeout - 5)},
                       timeout=timeout + 5)
    result = data.get('result')
    if action in ('snapshot', 'text'):
        max_chars = max(500, min(int(args.get('max_chars') or 12000), 20000))
        return _format_browser_snapshot(result, max_chars)
    return json.dumps(result, ensure_ascii=False)


def _console_tool(args, full_access, policy):
    action = args.get('action') or 'run'
    if action == 'run':
        if not full_access:
            raise ValueError('Shared console requires Full-PC access.')
        command = args.get('command')
        if not isinstance(command, str) or not command.strip():
            raise ValueError('command must contain a non-empty command string')
        shell = args.get('shell') or 'powershell'
        if shell not in ('powershell', 'cmd'):
            raise ValueError('shell must be powershell or cmd')
        timeout = max(5, min(int(args.get('timeout') or 90), 300))
        state = _local_json('/api/harness/console',
                            {'action': 'run', 'command': command, 'shell': shell, 'cwd': str(policy.root)},
                            timeout=15)
        deadline = time.monotonic() + timeout
        timed_out = False
        while state.get('running') and time.monotonic() < deadline:
            time.sleep(0.2)
            state = _local_json('/api/harness/console', None, timeout=10)
        if state.get('running'):
            timed_out = True
            try:
                state = _local_json('/api/harness/console', {'action': 'stop'}, timeout=15)
            except Exception:
                pass
        output = state.get('run_text') or ''
        header = 'shell=' + str(state.get('shell')) + ' cwd=' + str(state.get('cwd')) + ' exit=' + str(state.get('exit_code'))
        if timed_out:
            header += ' (timed out; session stopped)'
        return header + '\n[shared console]\n' + (output or '(no output)')
    if action == 'status':
        state = _local_json('/api/harness/console', None, timeout=10)
        return json.dumps({key: state.get(key) for key in ('id','running','exit_code','shell','cwd','session')}, ensure_ascii=False)
    if action in ('stop', 'clear'):
        state = _local_json('/api/harness/console', {'action': action}, timeout=15)
        return json.dumps({key: state.get(key) for key in ('id','running','exit_code','shell','cwd')}, ensure_ascii=False)
    raise ValueError('Unsupported console action.')


def _draft_target_name(snapshot):
    raw = (snapshot.get("args") or {}).get("path") or snapshot.get("file_path") or ""
    name = pathlib.Path(str(raw).replace("\\", "/")).name
    return re.sub(r"^[0-9a-f]{32}-", "", name, flags=re.I).lower()


def _restored_target_name(restored, fallback_path=""):
    """Derive a clean target filename for a restored or recuperados draft."""
    explicit = ""
    if isinstance(restored, dict):
        explicit = str(restored.get("target_path") or "").strip()
    if explicit:
        return explicit
    raw = str((restored.get("path") if isinstance(restored, dict) else "") or fallback_path or "").replace("\\", "/")
    name = pathlib.Path(raw).name if raw else ""
    cleaned = re.sub(r"^[0-9a-f]{32}-", "", name, flags=re.I).strip()
    return cleaned or "output file"


def _numbered_tail(texto, max_chars=1500, max_lines=32):
    """Format the trailing lines of text with 1-based line numbers within a character budget."""
    if not texto:
        return 1, 0, "(empty)"
    lines = texto.splitlines()
    total = len(lines)
    width = max(4, len(str(total)))
    picked = []
    used = 0
    for idx in range(total, max(0, total - max_lines), -1):
        row = "%*d\t%s" % (width, idx, lines[idx - 1])
        extra = len(row) + (1 if picked else 0)
        if picked and used + extra > max_chars:
            break
        if not picked and len(row) > max_chars:
            keep = max(40, max_chars - width - 8)
            row = "%*d\t[...] %s" % (width, idx, lines[idx - 1][-keep:])
            picked.append((idx, row))
            break
        picked.append((idx, row))
        used += extra
    picked.reverse()
    start_line = picked[0][0] if picked else total
    return start_line, total, "\n".join(row for _, row in picked)


def _draft_recovery_view(source_rel, target_name, texto, restored_from=False):
    """Summarize a large draft (size, lines, head, numbered tail, fs_copy hint) under 3400 chars."""
    total_chars = len(texto)
    total_lines = texto.count("\n") + 1 if texto else 0
    header = (
        f"[Draft auto-restored to {source_rel} (target: {target_name}). Complete and write the final target file.]"
        if restored_from
        else f"[Draft file: {source_rel} (target: {target_name})]"
    )
    guide = (
        f"\n[Size: {total_chars} chars, {total_lines} lines. To finish fast without reading every chunk: "
        f"call fs_copy(desde={json.dumps(source_rel)}, destino={json.dumps(target_name)}, modo=\"nuevo\"), "
        f"then inspect/complete the cut ending on {json.dumps(target_name)} with fs_edit.]"
    )
    head = texto[:360].rstrip()
    if len(texto) > 360:
        head += "\n..."
    start_line, line_count, tail = _numbered_tail(texto, max_chars=1600, max_lines=32)
    footer = (
        f"\n[Tail lines {start_line}-{line_count} of {line_count}:]\n{tail}"
        f"\n[Read specific slice if needed: fs_read(path={json.dumps(source_rel)}, linea=N, ventana=60) or offset=N max_chars=3000]"
    )
    out = f"{header}{guide}\n[Head:]\n{head}{footer}"
    if len(out) <= 3400:
        return out
    head = texto[:220].rstrip() + ("\n..." if len(texto) > 220 else "")
    _, line_count, tail = _numbered_tail(texto, max_chars=1100, max_lines=22)
    return f"{header}{guide}\n[Head:]\n{head}\n[Tail lines of {line_count}:]\n{tail}"[:3400]


def _clear_resolved_drafts(policy, written_path):
    """Discard older incomplete drafts once the target filename is successfully written."""
    try:
        rel = os.path.relpath(os.path.abspath(written_path), str(policy.root)).replace("\\", "/")
    except ValueError:
        return
    if rel.startswith(("drafts/", "recuperados/")) or rel.startswith("../"):
        return
    target_name = pathlib.Path(written_path).name.lower()
    if not target_name:
        return
    try:
        folder = policy.path("drafts")
        snapshots = list(folder.glob("*.json")) if folder.is_dir() else []
    except (OSError, ValueError):
        return
    for snap_path in snapshots:
        if not re.fullmatch(r"[0-9a-f]{32}", snap_path.stem):
            continue
        try:
            snapshot = json.loads(snap_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if snapshot.get("name") in ("pc__fs_write", "mcp__draft") and _draft_target_name(snapshot) == target_name:
            for copy in folder.glob(snap_path.stem + "-*"):
                try:
                    copy.unlink(missing_ok=True)
                except OSError:
                    pass
            try:
                snap_path.unlink(missing_ok=True)
            except OSError:
                pass


def call(name, args, *, full_access=False, policy=None):
    policy = POLICY if policy is None else policy
    policy.check_tool(name, args, full_access)
    if name == 'browser':
        return _browser_tool(args)
    if name == 'console':
        return _console_tool(args, full_access, policy)
    if name == "draft_resume":
        from draft_recovery import resume_draft
        try:
            restored = resume_draft(policy)
        except ValueError as error:
            return json.dumps({'ok': False, 'error': str(error)}, ensure_ascii=False)
        if not restored:
            return json.dumps({'ok': False, 'error': 'No interrupted or pending draft was found to resume.'}, ensure_ascii=False)
        payload = dict(restored)
        target_name = _restored_target_name(payload)
        payload["target_path"] = target_name
        try:
            restored_file = policy.path(payload["path"], full_access)
            with open(restored_file, "r", encoding="utf-8-sig", errors="replace") as f:
                texto_borrador = f.read()
        except (OSError, ValueError):
            texto_borrador = ""
        if texto_borrador:
            start_line, total_lines, tail = _numbered_tail(texto_borrador, max_chars=1200, max_lines=24)
            payload["chars"] = len(texto_borrador)
            payload["lines"] = total_lines
            payload["tail_lines"] = f"{start_line}-{total_lines}"
            payload["tail_preview"] = tail
        payload["recommended_action"] = (
            f"Call pc__fs_copy(desde={payload['path']!r}, destino={target_name!r}, modo='nuevo'), "
            f"then inspect/complete the ending on {target_name!r} with pc__fs_edit."
        )
        return json.dumps({'ok': True, **payload}, ensure_ascii=False)
    if name == "project_map":
        from context_policy import project_map
        return project_map(policy,args.get('path') or '.',full_access)
    if name == "file_history":
        path=policy.path(args.get('path'),full_access)
        return json.dumps(VERSIONS.restore(path,policy.root,args['revision']) if args.get('revision') else VERSIONS.describe(path,policy.root),ensure_ascii=False)
    if name == "code_check":
        import verify
        path=policy.path(args.get('path'),full_access)
        import diagnostics
        project_check=args.get('check') not in (None,'','syntax')
        if path.is_dir() or project_check:
            result=diagnostics.inspect(path,run=bool(args.get('run')) and project_check,check=args.get('check'),full_access=full_access,timeout=args.get('timeout',60),root_limit=None if full_access else policy.root)
        else:
            result=verify.verificar_archivo(str(path))
            if not result.get('checked'):result['project_checks']=diagnostics.inspect(path,root_limit=None if full_access else policy.root)
        from verification_evidence import evidence
        result=evidence(result,'project' if path.is_dir() or project_check else 'syntax')
        return json.dumps(result,ensure_ascii=False)
    if name == "fs_list":
        path = policy.path(args.get("path") or ".", full_access)
        if os.path.isfile(path):
            raise ValueError(f"{path} is a file, not a directory; use fs_read to read its contents.")
        rows = []
        # Internal recovery data at the workspace root is not the user's: listing it led models to write there.
        hide = not full_access and pathlib.Path(path).resolve() == pathlib.Path(policy.root).resolve()
        with os.scandir(path) as it:
            entries = sorted((e for e in it if not (hide and (e.name == "drafts" or e.name.startswith(".val-isolated-")))),
                             key=lambda x: x.name.lower())
            for e in entries[:200]:
                try:
                    size = e.stat().st_size if e.is_file() else 0
                except OSError:
                    size = 0
                rows.append(f"{'[D]' if e.is_dir() else '   '} {e.name}\t{size}")
        if len(entries) > 200:
            rows.append(f"[Showing 200 of {len(entries)} entries]")
        return "\n".join(rows) or "(empty)"
    if name == "fs_read":
        raw_arg = str(args.get("path") or "").replace("\\", "/").lstrip("/")
        prefix_note = ""
        draft_restored_rel = ""
        draft_target_hint = ""
        if not full_access:
            draft_match = re.match(r"^drafts/([0-9a-f]{32})(?:[.-]|$)", raw_arg, re.I)
            rec_match = re.match(r"^recuperados/([0-9a-f]{32})-([^/]+)$", raw_arg, re.I)
            candidate_path = policy.path(args["path"], full_access)
            if draft_match:
                from draft_recovery import resume_draft
                try:
                    restored = resume_draft(policy, draft_match.group(1).lower())
                except (ValueError, OSError):
                    restored = None
                if restored:
                    path = policy.path(restored["path"], full_access)
                    draft_restored_rel = str(restored["path"]).replace("\\", "/")
                    draft_target_hint = _restored_target_name(restored, raw_arg)
                    prefix_note = f"[Draft auto-restored to {restored['path']} (target: {draft_target_hint}). Read complete, edit, and write the final target file.]\n"
                else:
                    path = candidate_path
            else:
                path = candidate_path
                if rec_match:
                    draft_restored_rel = raw_arg
                    draft_target_hint = rec_match.group(2)
        else:
            path = policy.path(args["path"], full_access)
        if os.path.isdir(path):
            raise ValueError(f"{path} is a directory, not a file; use fs_list to list its contents.")
        try:
            with open(path, "r", encoding="utf-8-sig", errors="strict") as f:
                texto_completo = f.read()
        except UnicodeDecodeError:
            from doc_extractor import is_document_path
            if is_document_path(str(path)):
                raise ValueError(f"{path} is a formatted/binary document ({os.path.getsize(path)} bytes); use doc_read instead of fs_read.")
            raise ValueError(f"{path} is a binary or non-UTF-8 file ({os.path.getsize(path)} bytes); inspect it with python/shell instead of fs_read.")
        if (
            draft_restored_rel
            and args.get("linea") is None
            and args.get("ventana") is None
            and args.get("offset") is None
            and args.get("max_chars") is None
            and len(texto_completo) > 3000
        ):
            return _draft_recovery_view(
                draft_restored_rel,
                draft_target_hint or "output file",
                texto_completo,
                restored_from=bool(prefix_note),
            )
        if args.get("linea") is not None or args.get("ventana") is not None:
            if args.get("linea") is not None and int(args["linea"]) < 1:
                raise ValueError("linea is 1-based and must be >= 1.")
            if args.get("ventana") is not None and int(args["ventana"]) < 1:
                raise ValueError("ventana must be >= 1.")
            # Vista por lineas numeradas (la ventana de 100 lineas de SWE-agent): el modelo copia el
            # trozo tal cual para fs_edit y ademas sabe donde esta, que es lo que falta para poder
            # editar UN punto en vez de reescribir el fichero entero.
            lineas = texto_completo.splitlines()
            total = len(lineas)
            inicio = max(1, min(int(args["linea"]) if args.get("linea") is not None else 1, max(1, total)))
            n = max(1, min(int(args.get("ventana") or 100), 240))
            corte = lineas[inicio - 1:inicio - 1 + n]
            ancho = max(4, len(str(total)))
            cap = int(options('pc').get('max_result_chars') or 12000)
            limit = max(300, min(cap - 260, 3200) if draft_restored_rel else cap - 260)
            rows = []
            for k, line in enumerate(corte, inicio):
                row = "%*d\t%s" % (ancho, k, line)
                if sum(len(x) for x in rows) + len(rows) + len(row) > limit:
                    if not rows:
                        # A single long line cannot be continued by line number.
                        # Point to a character offset in the same normalized text.
                        prefix = "%*d\t" % (ancho, k)
                        take = max(1, limit - len(prefix))
                        offset = sum(len(x) for x in texto_completo.splitlines(keepends=True)[:inicio - 1]) + take
                        return prefix + line[:take] + f"\n[Long line; continue: fs_read offset={offset} max_chars={limit}]"
                    break
                rows.append(row)
            corte = corte[:len(rows)]
            cuerpo = "\n".join(rows)
            siguiente = inicio + len(corte)
            guia = ("\n[lines %d-%d of %d. To continue: fs_read(path, linea=%d). To edit, copy the "
                    "line text (without its line number) into old_text of fs_edit.]"
                    % (inicio, inicio + len(corte) - 1, total, siguiente) if siguiente <= total else
                    "\n[end of file: %d lines]" % total)
            return prefix_note + (cuerpo or "(empty)") + guia
        if args.get("max_chars") is not None and int(args["max_chars"]) < 1:
            raise ValueError("max_chars must be >= 1.")
        if args.get("offset") is not None and int(args["offset"]) < 0:
            raise ValueError("offset must be >= 0.")
        cap = int(options('pc').get('max_result_chars') or 12000)
        n = max(1, min(int(args.get("max_chars") or 3000), max(300, cap - 200)))
        offset = max(0, int(args.get("offset") or 0))
        content = texto_completo[offset:offset + n]
        more = offset + len(content) < len(texto_completo)
        return prefix_note + content + (f"\n[Continue: fs_read offset={offset + len(content)} max_chars={n}]" if more else "")
    if name == "doc_read":
        path = policy.path(args["path"], full_access)
        from doc_extractor import extract_file
        return extract_file(
            path,
            pages=args.get("pages"),
            mode=args.get("mode"),
            offset=args.get("offset") or 0,
            max_chars=args.get("max_chars"),
        )
    if name == "fs_write":
        # Validate before opening the destination: a malformed model call must
        # never truncate an existing file. Replace only after a complete write.
        if not isinstance(args.get("path"), str) or not args["path"].strip():
            raise ValueError("path must be a non-empty file path")
        if not isinstance(args.get("content"), str):
            raise ValueError("content must be text")
        args = {**args, "content": DATE_NOTE.sub("", args["content"])}
        path = policy.path(args["path"], full_access)
        if os.path.isdir(path):
            raise ValueError(f"{path} is an existing directory, not a file; pass a file path to fs_write.")
        existia = os.path.exists(path)
        VERSIONS.capture(path,policy.root)
        parent = os.path.dirname(os.path.abspath(path))
        os.makedirs(parent, exist_ok=True)
        pending = None
        try:
            with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", newline="", dir=parent,
                                             prefix=".strata-write-", suffix=".tmp", delete=False) as f:
                pending = f.name
                f.write(args["content"])
                f.flush()
                os.fsync(f.fileno())
            os.replace(pending, path)
            pending = None
        finally:
            if pending is not None:
                os.unlink(pending)
        _clear_resolved_drafts(policy, path)
        return f"written: {path} ({len(args['content'])} chars)" + (
            "\nThe file already existed and was replaced in full. For small follow-up changes, "
            "use fs_edit (exact, unique old_text) or fs_copy (move lines without retyping) instead of "
            "rewriting the whole file." if existia else "") + (
            aviso_escritura(path, args["content"]) + comprueba_ejecucion(path) + syntax_report(path))
    if name == "fs_copy":
        return fs_copy(args, full_access, policy)
    if name == "fs_edit":
        if not isinstance(args.get("path"), str) or not args["path"].strip():
            raise ValueError("path must be a non-empty file path")
        lote = args.get("edits")
        if lote is None:
            lote = [{"old_text": args.get("old_text"), "new_text": args.get("new_text"),
                     "all": args.get("all")}]
        if not isinstance(lote, list) or not lote:
            raise ValueError('edits must be a non-empty list of {"old_text","new_text"}')
        if len(lote) > 12:
            raise ValueError("too many edits in a single batch (maximum 12)")
        path = policy.path(args["path"], full_access)
        if os.path.isdir(path):
            raise ValueError(f"{path} is a directory, not a file; pass a file path to fs_edit.")
        if not os.path.exists(path):
            raise ValueError("file does not exist: %s; to create a file use fs_write" % path)
        with open(path, "rb") as f:
            original_bytes = f.read()
        has_bom = original_bytes.startswith(b'\xef\xbb\xbf')
        original_text = original_bytes.decode('utf-8-sig', errors='strict')
        # Compare and edit consistently, but retain the file's encoding marker
        # and its existing newline style when writing it back.
        crlf = '\r\n' in original_text and '\n' not in original_text.replace('\r\n','') and '\r' not in original_text.replace('\r\n','')
        texto = original_text.replace('\r\n','\n') if crlf else original_text
        # Lote todo-o-nada, como `EDIT_FILE_TOOL` de Unsloth: se calculan TODAS las sustituciones
        # sobre el texto que va quedando y NO se escribe nada si alguna falla. Asi el modelo puede
        # arreglar tres sitios en una sola llamada (una ronda menos de prefill) y, si se equivoca
        # en una, no se queda con el fichero a medias.
        candidato, detalles = texto, []
        for i, e in enumerate(lote, 1):
            etiqueta = "edit %d of %d" % (i, len(lote)) if len(lote) > 1 else "old_text"
            if not isinstance(e, dict):
                raise ValueError("%s: each edit must be an object with old_text and new_text" % etiqueta)
            viejo, nuevo = e.get("old_text"), e.get("new_text")
            if not isinstance(viejo, str) or not viejo.strip():
                raise ValueError("%s: old_text must contain the exact text block to replace" % etiqueta)
            if not isinstance(nuevo, str):
                raise ValueError("%s: new_text must be a string (use empty string to delete)" % etiqueta)
            spans, modo = _busca(candidato, viejo)
            if not spans:
                raise ValueError("NOT APPLIED (%s): old_text was not found in %s (%d lines).%s"
                                 % (etiqueta, os.path.basename(path), candidato.count(chr(10)) + 1,
                                    _cercanas(candidato, viejo)))
            if len(spans) > 1 and not e.get("all"):
                rayas = ", ".join(str(_raya(candidato, x)) for x, _ in spans[:8])
                raise ValueError("NOT APPLIED (%s): old_text appears %d times (lines %s). Include more "
                                 "surrounding context so it is unique, or pass all=true." % (etiqueta, len(spans), rayas))
            cursor, partes, aplicadas = 0, [], 0
            for a, b in spans:
                if a < cursor:
                    continue                  # overlapping match: already covered
                partes.append(candidato[cursor:a])
                partes.append(nuevo)
                cursor = b
                aplicadas += 1
            partes.append(candidato[cursor:])
            candidato = "".join(partes)
            detalles.append((aplicadas, modo, _raya(texto, spans[0][0])))
        aplicadas = sum(d[0] for d in detalles)
        modo = detalles[0][1] if len(detalles) == 1 else "batch"
        primera_linea = min(d[2] for d in detalles)
        aviso = ""
        extension = os.path.splitext(str(path))[1].lower()
        if extension in (".html", ".htm", ".js", ".mjs", ".cjs", ".py", ".json"):
            try:
                import verify
                antes = verify.verificar_contenido(texto, path)
                despues = verify.verificar_contenido(candidato, path)
                nuevos = _errores_nuevos(antes, despues)
                if nuevos:
                    # SWE-agent: if the edit introduces errors, reject it and pinpoint where to fix.
                    raise ValueError("NOT APPLIED: the change introduces errors not present in the original file: "
                                     + " | ".join(str(n)[:180] for n in nuevos[:4])
                                     + "\nYour edit is around line %d; inspect that region with "
                                       "fs_read(path, linea=%d, ventana=24) and fix only that block."
                                       % (primera_linea, max(1, primera_linea - 9)))
                aviso = " | verified: no new errors"
            except ImportError:
                aviso = " | (check skipped: missing agent/verify.py)"
        prueba = ""
        if extension in (".html", ".htm") and os.environ.get("STRATA_AGENT_EDIT_BROWSER", "0") == "1":
            try:
                informe = ejecuta_contenido(candidato, path)
            except Exception as error:
                informe = None
                prueba = "\n(new version execution skipped: %s)" % str(error)[:90]
            if informe is not None:
                if informe.get("error"):
                    prueba = "\n(could not execute new version: %s)" % informe["error"]
                else:
                    rompe = [e for e in (informe.get("errores") or [])
                             if "SyntaxError" in str(e) or "Unexpected" in str(e)]
                    if rompe:
                        raise ValueError("NOT APPLIED: with your change the page does not compile (SyntaxError):\n%s\n"
                                         "%s\nThe file is unchanged; fix that block with fs_edit on the exact text."
                                         % ("\n".join(str(r)[:220] for r in rompe[:2]),
                                         pista_de_linea(rompe)))
                    nuevos = []
                    if informe.get("errores"):
                        try:
                            import render_check
                            nuevos = errores_nuevos(informe, render_check.resumen(path))
                        except Exception:
                            nuevos = []
                    prueba = "\n" + (informe.get("resumen") or "")
                    prueba += "\n(executed BEFORE applying: %s)" % (
                        "no console errors" if not informe.get("errores") else
                        ("%d runtime error(s); %d are new with this change. Applied anyway: "
                         "fix the new one with fs_edit at the indicated line."
                         % (len(informe["errores"]), len(nuevos))))
                    if nuevos:
                        prueba += "\n" + pista_de_linea(nuevos)
        parent = os.path.dirname(os.path.abspath(path))
        pending = None
        try:
            with tempfile.NamedTemporaryFile(mode="wb", dir=parent,
                                             prefix=".strata-edit-", suffix=".tmp", delete=False) as f:
                pending = f.name
                content = candidato.replace('\r\n','\n').replace('\n','\r\n') if crlf else candidato
                f.write((b'\xef\xbb\xbf' if has_bom else b'') + content.encode('utf-8'))
                f.flush()
                os.fsync(f.fileno())
            with open(path,'rb') as current_file:
                if current_file.read()!=original_bytes:raise ValueError('File changed during editing. Read it again before retrying.')
            VERSIONS.capture(path,policy.root)
            os.replace(pending, path)
            pending = None
        finally:
            if pending is not None:
                os.unlink(pending)
        _clear_resolved_drafts(policy, path)
        delta = candidato.count("\n") - texto.count("\n")
        return ("edited: %s (%d replacement(s)%s, matched via %s, %+d lines, %d chars)%s%s%s"
                % (path, aplicadas, "" if len(detalles) == 1 else " across %d edits" % len(detalles),
                   " and ".join(sorted({d[1] for d in detalles})), delta, len(candidato), aviso,
                   recibo_diff(texto, candidato), prueba or comprueba_ejecucion(path)))
    if name == "web_render":
        if not isinstance(args.get("path"), str) or not args["path"].strip():
            raise ValueError("path must contain a file path")
        path = policy.path(args["path"], full_access)
        if not os.path.exists(path):
            raise ValueError("%s does not exist; create the page first with fs_write" % path)
        suf = os.path.splitext(str(path))[1].lower()
        if suf not in (".html", ".htm"):
            raise ValueError("web_render opens .html pages (got %s)" % (suf or "no extension"))
        try:
            import render_check
        except ImportError as error:
            raise ValueError("test environment is unavailable: %s" % str(error)[:120])
        informe = render_check.resumen(path,
                                       espera_ms=int(args.get("espera_ms") or 2200),
                                       pintura=bool(args.get("pintura")),diagnostics=args.get('diagnostics',True) is not False)
        texto = informe.get("resumen") or json.dumps(informe, ensure_ascii=False)[:600]
        if informe.get("error"):
            # NO es un fallo de la pagina: es el entorno, que no llego a verla terminar. Una escena
            # de ~20k voxels en SwiftShader (sin GPU) tarda mas que cualquier error de consola, y
            # reportar esto como "tu pagina esta rota" mandaria al modelo a arreglar lo que no esta.
            return ("Check did not finish in time (%s). This does not prove the page is broken. "
                    "The browser did not finish loading it. Insufficient evidence "
                    "to confirm rendering; use the GPU-enabled "
                    "preview or retry with a larger espera_ms." % informe["error"])
        if not informe.get("ok"):
            raise ValueError("Runtime or geometry errors found. Fix only the affected "
                             "block with fs_edit (exact, unique old_text), then check again:\n" + texto)
        return texto
    if name == "fs_search":
        import fnmatch
        base = policy.path(args.get("path") or ".", full_access)
        pattern = str(args.get("glob") or "**/*")
        needle = args.get("contains")
        regex = bool(args.get("regex"))
        flags = 0 if args.get("case_sensitive") else re.IGNORECASE
        matcher = re.compile(str(needle), flags) if regex and needle is not None else None
        limit = max(1, min(int(args.get("max_results") or 80), 500))
        max_file = max(1024, min(int(args.get("max_file_bytes") or 2_000_000), 5_000_000))
        files, matches, truncated = [], [], False
        # "**/" also matches zero folders (glob semantics), so **/*.py includes files at the top level.
        patterns, rest = {pattern}, pattern
        while rest.startswith(("**/", "**\\")):
            rest = rest[3:]
            if rest:
                patterns.add(rest)
        def wanted(relative, name):
            return any(fnmatch.fnmatch(relative, p) or fnmatch.fnmatch(name, p) for p in patterns)
        candidates = [base] if base.is_file() else base.rglob("*")
        for candidate in candidates:
            if len(files) + len(matches) >= limit:
                truncated = True
                break
            try:
                if candidate.is_symlink() or not candidate.is_file():
                    continue
                relative = str(candidate.relative_to(base)) if base.is_dir() else str(candidate)
                if base.is_dir() and not wanted(relative, candidate.name):
                    continue
                if needle is None:
                    files.append({"path": relative, "bytes": candidate.stat().st_size})
                    continue
                if candidate.stat().st_size > max_file:
                    continue
                raw = candidate.read_bytes()
                if b"\x00" in raw[:8192]:
                    continue
                text = raw.decode("utf-8", errors="replace")
                for number, line in enumerate(text.splitlines(), 1):
                    hit = matcher.search(line) if matcher else (str(needle) in line if args.get("case_sensitive") else str(needle).lower() in line.lower())
                    if hit:
                        matches.append({"path": relative, "line": number, "text": line[:400]})
                        if len(files) + len(matches) >= limit:
                            truncated = True
                            break
            except (OSError, ValueError):
                continue
        return json.dumps({"root": str(base), "pattern": pattern, "files": files, "matches": matches, "truncated": truncated}, ensure_ascii=False)
    if name == "fs_manage":
        import shutil
        action = str(args.get("action") or "")
        source = policy.path(args.get("path"), full_access)
        if action == "mkdir":
            source.mkdir(parents=True, exist_ok=True)
            return "created: " + str(source)
        if source == policy.root:
            raise ValueError("Cannot modify the workspace root.")
        if action == "stat":
            info = source.stat()
            return json.dumps({"path": str(source), "is_dir": source.is_dir(), "bytes": info.st_size, "mtime": info.st_mtime, "mode": oct(info.st_mode)}, ensure_ascii=False)
        if action == "delete":
            if not source.exists() and not source.is_symlink():
                raise ValueError("Path does not exist: " + str(source))
            if source.is_dir() and not source.is_symlink():
                if any(source.iterdir()) and not bool(args.get("recursive")):
                    raise ValueError("Directory is not empty; pass recursive=true to delete it.")
                if bool(args.get("recursive")):
                    shutil.rmtree(source)
                else:
                    source.rmdir()
            else:
                source.unlink()
            return "deleted: " + str(source)
        if action in ("move", "copy"):
            destination = policy.path(args.get("destination"), full_access)
            # Check the source before touching anything: a mistaken move must never cost the destination.
            if not source.exists():
                raise ValueError("Source does not exist: %s. Nothing was changed; list the folder with fs_list to see the real names." % args.get("path"))
            if source.resolve() == destination.resolve():
                raise ValueError("Source and destination are the same; nothing was changed.")
            if source.is_dir() and destination.resolve().is_relative_to(source.resolve()):
                raise ValueError("A folder cannot be copied or moved into itself; nothing was changed.")
            if action == "copy" and source.is_dir() and not bool(args.get("recursive")):
                raise ValueError("Directory copy requires recursive=true.")
            if destination.exists() and not bool(args.get("overwrite")):
                raise ValueError("Destination exists; pass overwrite=true to replace it.")
            destination.parent.mkdir(parents=True, exist_ok=True)
            backup = None
            if destination.is_dir() and not destination.is_symlink():
                # Keep the old folder aside until the new one is complete, so a failure restores it.
                backup = destination.with_name(destination.name + ".val-replace")
                if backup.exists():
                    shutil.rmtree(backup)
                destination.rename(backup)
            try:
                if action == "move":
                    if source.is_file() and destination.is_file():
                        os.replace(source, destination)  # atomic swap of one file for another
                    else:
                        shutil.move(str(source), str(destination))
                elif source.is_dir():
                    shutil.copytree(source, destination, symlinks=False)
                else:
                    staged = destination.with_name("." + destination.name + ".val-copy")
                    shutil.copy2(source, staged)
                    os.replace(staged, destination)  # the old file is replaced only once the copy is complete
            except Exception:
                if backup is not None and not destination.exists():
                    backup.rename(destination)
                raise
            if backup is not None:
                shutil.rmtree(backup, ignore_errors=True)
            return ("moved: " if action == "move" else "copied: ") + str(source) + " -> " + str(destination)
        raise ValueError("Invalid fs_manage action.")
    if name == "shell_run":
        if not full_access:
            from sandbox_exec import run
            return run(policy.root,args.get('command'),args.get('shell','cmd'),args.get('timeout') or options('pc')['command_timeout'],args.get('background',False))
        if args.get("background"):
            return _start_background(args, policy)
        return shell_run(args, policy)
    if name == "job_wait":
        return job_wait(args)
    if name == "job_status":
        return job_status(args)
    if name == "job_list":
        return job_list(args)
    if name == "job_stop":
        return job_stop(args)
    if name == "sys_info":
        import platform
        cpu = platform.processor()
        try:
            import winreg
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"HARDWARE\DESCRIPTION\System\CentralProcessor\0") as key:
                cpu = winreg.QueryValueEx(key, "ProcessorNameString")[0].strip()
        except (ImportError, OSError):
            pass
        lines = [f"OS: {platform.platform()}", f"CPU: {cpu} ({os.cpu_count()} threads)"]
        try:
            import psutil
            vm = psutil.virtual_memory()
            lines.append(f"RAM: total {vm.total/2**30:.1f} GiB, in use {vm.used/2**30:.1f} GiB ({vm.percent}%), "
                         f"available {vm.available/2**30:.1f} GiB")
            for d in psutil.disk_partitions():
                if d.fstype:
                    try:
                        u = psutil.disk_usage(d.mountpoint)
                        lines.append(f"Disk {d.device}: total {u.total/2**30:.0f} GiB, free {u.free/2**30:.0f} GiB")
                    except OSError:
                        pass
        except Exception:
            pass
        try:
            g = subprocess.run(["nvidia-smi", "--query-gpu=name,memory.used,memory.total,utilization.gpu",
                                "--format=csv,noheader"], capture_output=True, text=True, timeout=5, creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
            if g.stdout.strip():
                lines.append("GPU: " + g.stdout.strip())
        except Exception:
            pass
        return "\n".join(lines)
    raise ValueError("unknown tool: " + name)


def execute_request(params):
    try:
        args = dict(params.get("arguments") or {})
        key = args.pop('_pc_access_key', '')
        expected = os.environ.get('STRATA_PC_ACCESS_KEY', '')
        full_access = bool(expected and isinstance(key, str) and secrets.compare_digest(key, expected))
        ticket = args.pop('_pc_workspace', None)
        policy = POLICY
        if ticket is not None:
            if not expected or not isinstance(ticket, dict) or not isinstance(ticket.get('signature'), str):
                raise AccessDenied('Unauthorized conversation workspace.')
            chat_id = ticket.get('id')
            if not secrets.compare_digest(ticket['signature'], workspace_signature(expected, chat_id)):
                raise AccessDenied('Unauthorized conversation workspace.')
            from projects import PROJECTS
            policy = PROJECTS.workspace(POLICY,chat_id)
        return ok(call(params.get('name'), args, full_access=full_access, policy=policy))
    except Exception as error:
        result = ok(str(error))
        result['isError'] = True
        return result


def main():
    from stdio_worker import serve
    serve(__file__, TOOLS, 'pc', '1.4', timeout=310, protocol=PROTO,persistent=True)


if __name__ == '__main__':
    if '--mcp-worker' in sys.argv:
        from stdio_worker import serve_worker
        serve_worker(execute_request)
    else:
        main()
