"""Elevated one-shot command helper for V-Agent.

Started by admin_mcp.py through ShellExecuteW("runas"), so Windows shows UAC once.
It listens on a private named pipe with an ephemeral authkey and executes commands
with the elevated token. It never listens on TCP and stops when the pipe closes.
"""
from __future__ import annotations

import argparse
import base64
import ctypes
import os
import subprocess
import time
from multiprocessing.connection import Listener


def is_admin() -> bool:
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def execute(command: str, shell: str, timeout: int, cwd: str | None):
    timeout = max(1, min(int(timeout), 3600))
    windows = os.environ.get("SystemRoot", r"C:\Windows")
    if shell == "cmd":
        executable = os.path.join(windows, "System32", "cmd.exe")
        argv = [executable, "/d", "/s", "/c", command]
    else:
        executable = os.path.join(windows, "System32", "WindowsPowerShell", "v1.0", "powershell.exe")
        prelude = ("$ProgressPreference = 'SilentlyContinue'; "
                   "[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false); "
                   "$OutputEncoding = [Console]::OutputEncoding; $ErrorActionPreference = 'Stop';" + chr(10))
        script = prelude + "try { & {" + chr(10) + command + chr(10) + "}" + chr(10) + \
                 "if (-not $?) { if ($LASTEXITCODE) { exit $LASTEXITCODE }; exit 1 }" + chr(10) + \
                 "} catch { [Console]::Error.WriteLine($_.ToString()); exit 1 }"
        encoded = base64.b64encode(script.encode("utf-16-le")).decode("ascii")
        argv = [executable, "-NoLogo", "-NoProfile", "-NonInteractive", "-OutputFormat", "Text", "-EncodedCommand", encoded]
    started = time.monotonic()
    try:
        result = subprocess.run(argv, cwd=cwd or None, capture_output=True, text=True,
                                encoding="utf-8", errors="replace", timeout=timeout,
                                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        return {
            "ok": result.returncode == 0,
            "exit_code": result.returncode,
            "stdout": (result.stdout or "")[-200_000:],
            "stderr": (result.stderr or "")[-50_000:],
            "elapsed_s": round(time.monotonic() - started, 2),
            "shell": shell,
        }
    except subprocess.TimeoutExpired:
        return {"ok": False, "exit_code": None, "stdout": "", "stderr": "timeout", "elapsed_s": timeout, "shell": shell}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--pipe", required=True)
    parser.add_argument("--authkey", required=True)
    args = parser.parse_args()
    address = r"\\.\pipe" + "\\" + args.pipe
    listener = Listener(address, family="AF_PIPE", authkey=args.authkey.encode("utf-8"))
    try:
        connection = listener.accept()
        try:
            while True:
                try:
                    request = connection.recv()
                except EOFError:
                    break
                if not isinstance(request, dict):
                    continue
                action = request.get("action")
                if action == "stop":
                    break
                if action == "status":
                    reply = {"ok": True, "admin": is_admin(), "pid": os.getpid(),
                             "user": os.environ.get("USERNAME", ""), "helper": True}
                elif action == "run":
                    reply = execute(str(request.get("command") or ""), str(request.get("shell") or "powershell"),
                                    int(request.get("timeout") or 120), request.get("cwd"))
                    reply["admin"] = is_admin()
                else:
                    reply = {"ok": False, "error": "acción no válida"}
                connection.send(reply)
        finally:
            connection.close()
    finally:
        listener.close()


if __name__ == "__main__":
    main()
