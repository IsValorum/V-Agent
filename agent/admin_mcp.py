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
START_LOCK = threading.Lock()
STATE = {"client": None, "listener": None, "process": None, "pipe": None, "key": None, "status": None}


def _helper_argv(pipe: str, key: str) -> list[str]:
    if getattr(sys, "frozen", False):
        base = [sys.executable, "--role", "admin-helper", "--"]
    else:
        base = [sys.executable, str(SOURCE_ROOT / "backend.py"), "--role", "admin-helper", "--"]
    return base + ["--pipe", pipe, "--authkey", key]


def _address(pipe: str) -> str:
    return r"\\.\pipe" + "\\" + pipe


def _reset():
    with LOCK:
        client = STATE.get("client")
        listener = STATE.get("listener")
        STATE.update({"client": None, "listener": None, "pipe": None, "key": None, "status": None})
    for handle in (client, listener):
        if handle is not None:
            try:
                handle.close()
            except Exception:
                pass


def _start() -> dict:
    from multiprocessing.connection import Listener
    with START_LOCK:
        with LOCK:
            if STATE.get("client") is not None:
                return STATE.get("status") or {"ok": True, "admin": True}
        _reset()
        pipe = "val-admin-" + uuid.uuid4().hex
        key = secrets.token_hex(24)
        argv = _helper_argv(pipe, key)
        listener = Listener(_address(pipe), family="AF_PIPE", authkey=key.encode("utf-8"))
        accepted = []
        accept_error = []

        def _accept():
            try:
                accepted.append(listener.accept())
            except Exception as exc:
                accept_error.append(exc)

        waiter = threading.Thread(target=_accept, daemon=True, name="val-admin-accept")
        waiter.start()
        try:
            if os.environ.get("VAL_ADMIN_NO_ELEVATE") == "1":
                process = subprocess.Popen(argv, cwd=str(DATA_ROOT) if DATA_ROOT.exists() else None, stdin=subprocess.DEVNULL,
                                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
                with LOCK:
                    STATE["process"] = process
            else:
                params = subprocess.list2cmdline(argv[1:])
                hwnd = None
                try:
                    hwnd = ctypes.windll.user32.GetForegroundWindow() or None
                except Exception:
                    hwnd = None
                # SW_HIDE (0) prevents opening an empty console window for the elevated helper process.
                result = ctypes.windll.shell32.ShellExecuteW(hwnd, "runas", argv[0], params, str(DATA_ROOT) if DATA_ROOT.exists() else None, 0)
                if result <= 32:
                    raise RuntimeError("Windows cancelled or could not open the UAC elevation prompt.")
            waiter.join(timeout=45)
            if not accepted:
                detail = str(accept_error[0]) if accept_error else "timed out waiting for elevated helper connection"
                raise RuntimeError("The elevated helper did not connect in time: " + detail)
            with LOCK:
                STATE["listener"] = listener
                STATE["client"] = accepted[0]
                STATE["pipe"] = pipe
                STATE["key"] = key
            reply = _request({"action": "status"}, timeout=10, auto_start=False)
            with LOCK:
                STATE["status"] = reply
            return reply
        except Exception:
            try:
                listener.close()
            except Exception:
                pass
            _reset()
            raise


def _request(payload: dict, timeout: float = 120, auto_start: bool = True) -> dict:
    with LOCK:
        client = STATE.get("client")
    if client is None and auto_start:
        _start()
        with LOCK:
            client = STATE.get("client")
    if client is None:
        raise RuntimeError("Administrator helper is not started.")
    try:
        client.send(payload)
        if not client.poll(timeout):
            raise TimeoutError("The elevated helper did not respond in time.")
        reply = client.recv()
        if not isinstance(reply, dict):
            raise RuntimeError("Invalid response from the elevated helper.")
        return reply
    except (EOFError, OSError) as error:
        _reset()
        raise RuntimeError("The elevated helper closed unexpectedly: " + str(error)) from None


def _status_text(reply) -> str:
    return json.dumps(reply, ensure_ascii=False)


@mcp.tool(annotations=WRITE)
def start() -> str:
    """Start the elevated one-session helper. Windows shows UAC once."""
    return _status_text(_start())


@mcp.tool(annotations=READ)
def status() -> str:
    """Report whether the elevated helper is active or on standby (ready to auto-start on admin__run or admin__start)."""
    with LOCK:
        if STATE.get("client") is None:
            return _status_text({
                "ok": True,
                "active": False,
                "admin": False,
                "standby": True,
                "note": "The elevated Administrator helper is on standby (not started yet). Call admin__run (or admin__start) when you need to execute an elevated command; Windows will prompt UAC once and run with full Administrator privileges."
            })
    try:
        reply = _request({"action": "status"}, timeout=8, auto_start=False)
        return _status_text(reply)
    except Exception as error:
        return _status_text({"ok": False, "active": False, "error": str(error)})


@mcp.tool(annotations=WRITE)
def run(command: str, shell: str = "powershell", timeout: int = 120, cwd: str | None = None) -> str:
    """Run a PowerShell or CMD command with the elevated Windows token (auto-starts the UAC helper on first call if on standby). Output is capped."""
    if shell not in ("powershell", "cmd"):
        raise ValueError("shell must be 'powershell' or 'cmd'.")
    if not isinstance(command, str) or not command.strip():
        raise ValueError("command cannot be empty.")
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
    if process is not None:
        try:
            if process.poll() is None:
                process.terminate()
            process.wait(timeout=3)
        except Exception:
            pass
    _reset()
    return _status_text({"ok": True, "active": False})


atexit.register(stop)

if __name__ == "__main__":
    mcp.run()
