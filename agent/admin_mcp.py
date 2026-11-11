"""One-session administrator bridge for the Complete mode.

The helper is a separate elevated copy of the core (admin_helper.py). UAC appears
once when the mode starts; afterwards admin_run executes arbitrary PowerShell/CMD
with the elevated token until admin_stop or application exit. The transport is a
private named pipe with a random authkey, not TCP.
"""
from __future__ import annotations

import atexit
import ctypes
import json
import os
import secrets
import subprocess
import sys
import threading
import time
import uuid

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations
from runtime_paths import DATA_ROOT, SOURCE_ROOT

mcp = FastMCP("V-Agent Admin")
WRITE = ToolAnnotations(readOnlyHint=False, destructiveHint=True, openWorldHint=False)
READ = ToolAnnotations(readOnlyHint=True, destructiveHint=False, openWorldHint=False)
LOCK = threading.RLock()
STATE = {"client": None, "process": None, "pipe": None, "key": None, "status": None}


def _helper_argv(pipe: str, key: str) -> list[str]:
    if getattr(sys, "frozen", False):
        base = [sys.executable, "--role", "admin-helper", "--"]
    else:
        base = [sys.executable, str(SOURCE_ROOT / "backend.py"), "--role", "admin-helper", "--"]
    return base + ["--pipe", pipe, "--authkey", key]


def _address(pipe: str) -> str:
    return r"\\.\pipe" + "\\" + pipe


def _reset():
    client = STATE.get("client")
    if client is not None:
        try:
            client.close()
        except Exception:
            pass
    STATE.update({"client": None, "pipe": None, "key": None, "status": None})


def _start() -> dict:
    from multiprocessing.connection import Client
    with LOCK:
        if STATE.get("client") is not None:
            return STATE.get("status") or {"ok": True, "admin": True}
        _reset()
        pipe = "val-admin-" + uuid.uuid4().hex
        key = secrets.token_hex(24)
        argv = _helper_argv(pipe, key)
        if os.environ.get("VAL_ADMIN_NO_ELEVATE") == "1":
            process = subprocess.Popen(argv, cwd=str(DATA_ROOT) if DATA_ROOT.exists() else None, stdin=subprocess.DEVNULL,
                                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            STATE["process"] = process
        else:
            params = subprocess.list2cmdline(argv[1:])
            result = ctypes.windll.shell32.ShellExecuteW(None, "runas", argv[0], params, str(DATA_ROOT) if DATA_ROOT.exists() else None, 1)
            if result <= 32:
                raise RuntimeError("Windows canceló o no pudo abrir la elevación (UAC).")
        STATE["pipe"] = pipe
        STATE["key"] = key
        deadline = time.monotonic() + 90
        last_error = None
        while time.monotonic() < deadline:
            try:
                client = Client(_address(pipe), family="AF_PIPE", authkey=key.encode("utf-8"))
                STATE["client"] = client
                reply = _request({"action": "status"}, timeout=10)
                STATE["status"] = reply
                return reply
            except (OSError, EOFError, ValueError) as error:
                last_error = error
                time.sleep(0.35)
        _reset()
        raise RuntimeError("El helper elevado no respondió a tiempo: " + str(last_error))


def _request(payload: dict, timeout: float = 120, auto_start: bool = True) -> dict:
    with LOCK:
        client = STATE.get("client")
    if client is None and auto_start:
        _start()
        client = STATE.get("client")
    if client is None:
        raise RuntimeError("Administrador no iniciado.")
    try:
        client.send(payload)
        if not client.poll(timeout):
            raise TimeoutError("El helper elevado no respondió a tiempo.")
        reply = client.recv()
        if not isinstance(reply, dict):
            raise RuntimeError("Respuesta del helper no válida.")
        return reply
    except (EOFError, OSError) as error:
        _reset()
        raise RuntimeError("El helper elevado se cerró: " + str(error)) from None


def _status_text(reply) -> str:
    return json.dumps(reply, ensure_ascii=False)


@mcp.tool(annotations=WRITE)
def start() -> str:
    """Start the elevated one-session helper. Windows shows UAC once."""
    return _status_text(_start())


@mcp.tool(annotations=READ)
def status() -> str:
    """Report whether the elevated helper is active and whether commands are truly elevated."""
    with LOCK:
        if STATE.get("client") is None:return _status_text({"ok":True,"active":False,"admin":False})
    try:
        reply = _request({"action": "status"}, timeout=8, auto_start=False)
        return _status_text(reply)
    except Exception as error:
        return _status_text({"ok": False, "active": False, "error": str(error)})


@mcp.tool(annotations=WRITE)
def run(command: str, shell: str = "powershell", timeout: int = 120, cwd: str | None = None) -> str:
    """Run a PowerShell or CMD command with the elevated Windows token. Output is capped."""
    if shell not in ("powershell", "cmd"):
        raise ValueError("shell debe ser powershell o cmd.")
    if not isinstance(command, str) or not command.strip():
        raise ValueError("command no puede estar vacío.")
    reply = _request({"action": "run", "command": command, "shell": shell,
                      "timeout": max(1, min(int(timeout), 3600)), "cwd": cwd})
    return _status_text(reply)


@mcp.tool(annotations=WRITE)
def stop() -> str:
    """Stop the elevated helper and close its private pipe."""
    with LOCK:
        client = STATE.get("client")
        process = STATE.get("process")
        STATE["process"] = None
    if client is not None:
        try:
            client.send({"action": "stop"})
            client.close()
        except Exception:
            pass
    if process is not None and process.poll() is None:
        try:
            process.terminate()
        except Exception:
            pass
    _reset()
    return _status_text({"ok": True, "active": False})


atexit.register(stop)

if __name__ == "__main__":
    mcp.run()
