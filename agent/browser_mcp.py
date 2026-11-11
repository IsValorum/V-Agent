"""Autonomous Edge/CDP browser for the standard and full agent modes.

The user-visible WebView2 dock stays in pc__browser. This server owns a separate
headless Edge instance with its own profile, so the agent can navigate, extract,
take screenshots, read network/console, manage tabs, cookies and downloads without
stealing the user's window. Windows ships Edge; no Chromium bundle is required.
"""
from __future__ import annotations

import atexit
import base64
import json
import os
import socket
import subprocess
import threading
import time
import urllib.parse
import urllib.request
from pathlib import Path

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations
from runtime_paths import DATA_ROOT, SOURCE_ROOT

mcp = FastMCP("V-Agent Browser")
READ = ToolAnnotations(readOnlyHint=True, destructiveHint=False, openWorldHint=True)
WRITE = ToolAnnotations(readOnlyHint=False, destructiveHint=False, openWorldHint=True)
STATE = {"process": None, "port": None, "cdp": None, "target": None}
LOCK = threading.RLock()


class CdpError(RuntimeError):
    pass


class CdpPage:
    def __init__(self, ws_url: str, target: dict):
        from websockets.sync.client import connect
        self.ws_url = ws_url
        self.target = target
        self.ws = connect(ws_url, open_timeout=10, close_timeout=3, max_size=None, proxy=None)
        self.next_id = 0
        self.pending: dict[int, dict] = {}
        self.events: list[tuple[float, str, dict]] = []
        self.lock = threading.RLock()
        self.closed = False
        self.reader = threading.Thread(target=self._read, daemon=True)
        self.reader.start()

    def _read(self):
        try:
            while not self.closed:
                raw = self.ws.recv()
                if raw is None:
                    continue
                message = json.loads(raw)
                if "id" in message:
                    slot = self.pending.get(int(message["id"]))
                    if slot:
                        slot["result"] = message
                        slot["event"].set()
                elif message.get("method"):
                    self.events.append((time.time(), message["method"], message.get("params") or {}))
                    if len(self.events) > 300:
                        self.events = self.events[-300:]
        except Exception:
            if not self.closed:
                for slot in list(self.pending.values()):
                    slot["event"].set()
            return

    def send(self, method: str, params: dict | None = None, timeout: float = 30):
        if self.closed:
            raise CdpError("La pestaña del navegador se cerró.")
        slot = {"event": threading.Event(), "result": None}
        with self.lock:
            self.next_id += 1
            ident = self.next_id
            self.pending[ident] = slot
        try:
            self.ws.send(json.dumps({"id": ident, "method": method, "params": params or {}}, ensure_ascii=False))
            if not slot["event"].wait(timeout):
                raise CdpError("El navegador no respondió a " + method + ".")
            response = slot["result"] or {}
            if "error" in response:
                raise CdpError(str(response["error"].get("message") or response["error"]))
            return response.get("result") or {}
        finally:
            with self.lock:
                self.pending.pop(ident, None)

    def close(self):
        self.closed = True
        try:
            self.ws.close()
        except Exception:
            pass

    def evaluate(self, expression: str, await_promise: bool = False):
        result = self.send("Runtime.evaluate", {
            "expression": expression,
            "returnByValue": True,
            "awaitPromise": bool(await_promise),
            "userGesture": True,
        }, timeout=30)
        if result.get("exceptionDetails"):
            raise CdpError(str(result["exceptionDetails"].get("text") or result["exceptionDetails"]))
        return result.get("result", {}).get("value")


def _edge_path() -> Path:
    candidates = [
        os.environ.get("VAL_BROWSER_PATH", ""),
        SOURCE_ROOT / "browser" / "chrome-headless-shell-win64" / "chrome-headless-shell.exe",
        Path(os.environ.get("PROGRAMFILES", r"C:\Program Files")) / "BraveSoftware/Brave-Browser/Application/brave.exe",
        Path(os.environ.get("PROGRAMFILES(X86)", r"C:\Program Files (x86)")) / "BraveSoftware/Brave-Browser/Application/brave.exe",
        Path(os.environ.get("LOCALAPPDATA", "")) / "BraveSoftware/Brave-Browser/Application/brave.exe",
        os.environ.get("VAL_EDGE_PATH", ""),  # Respect an explicit legacy configuration.
    ]
    for value in candidates:
        if value and Path(value).is_file():
            return Path(value)
    raise CdpError("No se encontró el navegador integrado ni Brave. Reinstala V-Agent o define VAL_BROWSER_PATH.")


def _port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


def _http_json(url: str, method: str = "GET", timeout: float = 5):
    request = urllib.request.Request(url, method=method)
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read(2_000_000).decode("utf8", "replace"))


def _list_pages() -> list[dict]:
    port = STATE["port"]
    if not port:
        return []
    try:
        return [item for item in _http_json(f"http://127.0.0.1:{port}/json/list") if item.get("type") == "page"]
    except (OSError, ValueError):
        return []


def _connect_target(target: dict) -> CdpPage:
    old = STATE.get("cdp")
    if old:
        old.close()
    page = CdpPage(target["webSocketDebuggerUrl"], target)
    for method in ("Page.enable", "Runtime.enable", "Network.enable", "Log.enable"):
        try:
            page.send(method, {}, timeout=10)
        except CdpError:
            pass
    STATE["cdp"] = page
    STATE["target"] = target
    return page


def _start() -> CdpPage:
    with LOCK:
        process = STATE.get("process")
        if process and process.poll() is None and STATE.get("cdp"):
            return STATE["cdp"]
        _close_browser()
        edge = _edge_path()
        port = _port()
        profile = DATA_ROOT / "cache" / "autobrowser"
        profile.mkdir(parents=True, exist_ok=True)
        headless = "--headless" if edge.name.lower().startswith("chrome-headless-shell") else "--headless=new"
        argv = [
            str(edge), headless, f"--remote-debugging-port={port}",
            f"--user-data-dir={profile}", "--no-first-run", "--no-default-browser-check",
            "--disable-extensions", "--disable-sync", "--disable-component-update",
            "--disable-background-networking", "--window-size=1440,900", "about:blank",
        ]
        STATE["process"] = subprocess.Popen(
            argv, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        STATE["port"] = port
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            if STATE["process"].poll() is not None:
                raise CdpError("Edge se cerró al iniciar.")
            try:
                pages = _list_pages()
                if pages:
                    target = pages[0]
                    if "webSocketDebuggerUrl" not in target:
                        target = _http_json(f"http://127.0.0.1:{port}/json/list")[0]
                    return _connect_target(target)
            except (OSError, ValueError, IndexError):
                pass
            time.sleep(0.25)
        raise CdpError("Edge no abrió el puerto de depuración.")


def _page() -> CdpPage:
    cdp = STATE.get("cdp")
    if cdp and not cdp.closed:
        return cdp
    pages = _list_pages()
    if pages:
        return _connect_target(pages[0])
    return _start()


def _navigate(url: str, wait: bool = True):
    parsed = urllib.parse.urlparse(str(url or "").strip())
    if parsed.scheme not in ("http", "https"):
        raise ValueError("Solo se permiten URLs http/https.")
    target = parsed.geturl()
    page = _page()
    page.send("Page.navigate", {"url": target}, timeout=30)
    if wait:
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            try:
                state = page.evaluate("document.readyState")
                if state in ("interactive", "complete"):
                    break
            except CdpError:
                pass
            time.sleep(0.2)
    return page


def _snapshot_js(max_chars: int) -> str:
    return """(() => {
      const clean = value => String(value == null ? '' : value).replace(/\\s+/g, ' ').trim();
      const visible = el => {
        const style = getComputedStyle(el), rect = el.getBoundingClientRect();
        return style.display !== 'none' && style.visibility !== 'hidden' && rect.width > 0 && rect.height > 0;
      };
      document.querySelectorAll('[data-val-ref]').forEach(el => el.removeAttribute('data-val-ref'));
      const token = 'val' + Date.now().toString(36), items = [];
      const nodes = document.querySelectorAll('a[href],button,input,select,textarea,[role=button],[role=link],[role=textbox],[contenteditable=true],[onclick]');
      for (const el of nodes) {
        if (items.length >= 120) break;
        if (!visible(el)) continue;
        const ref = token + '-' + (items.length + 1);
        el.setAttribute('data-val-ref', ref);
        items.push({selector: '[data-val-ref="' + ref + '"]', tag: el.tagName.toLowerCase(),
          type: el.getAttribute('type') || el.getAttribute('role') || '',
          text: clean(el.getAttribute('aria-label') || el.getAttribute('title') || el.innerText || el.getAttribute('placeholder') || '').slice(0, 140),
          name: clean(el.getAttribute('name') || ''), href: el.href ? String(el.href).slice(0, 300) : '',
          disabled: !!el.disabled, checked: !!el.checked});
      }
      return {ok: true, title: document.title, url: location.href,
        text: (document.body ? document.body.innerText : '').slice(0, """ + str(int(max_chars)) + """), items};
    })()"""


def _wait_selector(page: CdpPage, selector: str, timeout: float = 15):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            if page.evaluate("!!document.querySelector(" + json.dumps(selector) + ")"):
                return True
        except CdpError:
            pass
        time.sleep(0.25)
    return False


def _result(value):
    return json.dumps(value, ensure_ascii=False)


@mcp.tool(annotations=WRITE)
def open(url: str, new_tab: bool = False) -> str:
    """Open a URL in the autonomous Edge browser (optionally in a new tab)."""
    if new_tab:
        port = _start().target and STATE["port"]
        target = _http_json(f"http://127.0.0.1:{port}/json/new?url=" + urllib.parse.quote(url, safe=""), method="PUT")
        _connect_target(target)
    page = _navigate(url)
    return _result({"ok": True, "url": page.evaluate("location.href"), "title": page.evaluate("document.title")})


@mcp.tool(annotations=WRITE)
def navigate(url: str) -> str:
    """Navigate the current autonomous browser tab to an http/https URL."""
    page = _navigate(url)
    return _result({"ok": True, "url": page.evaluate("location.href"), "title": page.evaluate("document.title")})


@mcp.tool(annotations=READ)
def snapshot(max_chars: int = 12000) -> str:
    """Return page title, URL, text excerpt and up to 120 interactive selectors."""
    return _result(_page().evaluate(_snapshot_js(max(500, min(int(max_chars), 20000)))))


@mcp.tool(annotations=READ)
def text(max_chars: int = 12000) -> str:
    """Read visible page text."""
    return _result({"url": _page().evaluate("location.href"), "title": _page().evaluate("document.title"),
                    "text": _page().evaluate("(document.body ? document.body.innerText : '').slice(0," + str(max(500, min(int(max_chars), 20000))) + ")")})


@mcp.tool(annotations=WRITE)
def click(selector: str) -> str:
    """Click an element by CSS selector."""
    value = _page().evaluate("""(() => { const el=document.querySelector(%s); if(!el) return {ok:false,error:'no encontrado'}; el.scrollIntoView({block:'center',inline:'center'}); el.focus({preventScroll:true}); el.click(); return {ok:true,tag:el.tagName.toLowerCase(),text:(el.innerText||'').slice(0,120)}; })()""" % json.dumps(selector))
    return _result(value)


@mcp.tool(annotations=WRITE)
def fill(selector: str, text: str) -> str:
    """Fill an input, textarea, select or contenteditable element."""
    value = _page().evaluate("""(() => { const el=document.querySelector(%s); if(!el) return {ok:false,error:'no encontrado'}; el.focus({preventScroll:true});
      if(el.isContentEditable){el.textContent=%s;el.dispatchEvent(new InputEvent('input',{bubbles:true,inputType:'insertText',data:%s}));}
      else {const proto=el instanceof HTMLTextAreaElement?HTMLTextAreaElement.prototype:el instanceof HTMLSelectElement?HTMLSelectElement.prototype:HTMLInputElement.prototype;
        const setter=Object.getOwnPropertyDescriptor(proto,'value')?.set;if(setter)setter.call(el,%s);else el.value=%s;
        el.dispatchEvent(new Event('input',{bubbles:true}));}
      el.dispatchEvent(new Event('change',{bubbles:true})); return {ok:true,value:String(el.value==null?el.textContent:el.value).slice(0,200)}; })()""" % (json.dumps(selector), json.dumps(text), json.dumps(text), json.dumps(text), json.dumps(text)))
    return _result(value)


@mcp.tool(annotations=WRITE)
def press(key: str = "Enter", selector: str | None = None) -> str:
    """Send a key to the page or to a selector. Enter submits its form when possible."""
    selector = selector or "body"
    value = _page().evaluate("""(() => { const el=document.querySelector(%s)||document.body; el.focus({preventScroll:true});
      const k=%s, code=k==='Enter'?'Enter':'Key'+k.toUpperCase(), keyCode=k==='Enter'?13:k.length===1?k.toUpperCase().charCodeAt(0):0;
      const o={key:k,code,keyCode,which:keyCode,bubbles:true,cancelable:true};
      el.dispatchEvent(new KeyboardEvent('keydown',o));el.dispatchEvent(new KeyboardEvent('keypress',o));el.dispatchEvent(new KeyboardEvent('keyup',o));
      let submitted=false;if(k==='Enter'){const f=el.form||el.closest('form');if(f){try{f.requestSubmit();submitted=true}catch{}}}
      return {ok:true,pressed:k,submitted}; })()""" % (json.dumps(selector), json.dumps(key)))
    return _result(value)


@mcp.tool(annotations=WRITE)
def evaluate(script: str, await_promise: bool = False) -> str:
    """Evaluate JavaScript in the page and return its JSON value. Use for advanced extraction."""
    return _result({"ok": True, "value": _page().evaluate(script, bool(await_promise))})


@mcp.tool(annotations=READ)
def wait(milliseconds: int = 0, selector: str | None = None, timeout: int = 15) -> str:
    """Wait for a selector or a number of milliseconds."""
    page = _page()
    if selector:
        return _result({"ok": _wait_selector(page, selector, max(1, min(int(timeout), 120))), "selector": selector})
    time.sleep(max(0, min(int(milliseconds), 120000)) / 1000)
    return _result({"ok": True, "waited_ms": max(0, min(int(milliseconds), 120000))})


@mcp.tool(annotations=READ)
def screenshot(full_page: bool = False) -> str:
    """Capture a PNG screenshot and save it under data/downloads. Returns its path."""
    page = _page()
    data = page.send("Page.captureScreenshot", {"format": "png", "captureBeyondViewport": bool(full_page)}, timeout=30)
    raw = base64.b64decode(data.get("data") or "")
    folder = DATA_ROOT / "downloads"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / ("browser-" + time.strftime("%Y%m%d-%H%M%S") + ".png")
    path.write_bytes(raw)
    return _result({"ok": True, "path": str(path), "bytes": len(raw), "full_page": bool(full_page)})


@mcp.tool(annotations=READ)
def cookies() -> str:
    """List cookies of the autonomous browser profile."""
    value = _page().send("Network.getAllCookies")
    items = value.get("cookies") or []
    return _result([{k: item.get(k) for k in ("name", "value", "domain", "path", "secure", "httpOnly", "session", "expires")} for item in items])


@mcp.tool(annotations=READ)
def network(clear: bool = False) -> str:
    """Return recent network requests/responses/errors captured by the browser."""
    page = _page()
    items = []
    for _, method, params in list(page.events):
        if method == "Network.responseReceived":
            response = params.get("response") or {}
            items.append({"type": "response", "url": response.get("url"), "status": response.get("status"), "mime": response.get("mimeType")})
        elif method == "Network.loadingFailed":
            items.append({"type": "failed", "error": params.get("errorText"), "url": params.get("requestId")})
    if clear:
        page.events = [item for item in page.events if not item[1].startswith("Network.")]
    return _result(items[-150:])


@mcp.tool(annotations=READ)
def browser_console(clear: bool = False) -> str:
    """Return recent console messages from the page."""
    page = _page()
    items = []
    for _, method, params in list(page.events):
        if method == "Runtime.consoleAPICalled":
            items.append({"level": params.get("type"), "text": " ".join(str(arg.get("value", arg.get("description", ""))) for arg in params.get("args") or [])[:1000]})
        elif method == "Log.entryAdded":
            entry = params.get("entry") or {}
            items.append({"level": entry.get("level"), "text": str(entry.get("text") or "")[:1000], "url": entry.get("url")})
    if clear:
        page.events = [item for item in page.events if not (item[1] == "Runtime.consoleAPICalled" or item[1].startswith("Log."))]
    return _result(items[-150:])


@mcp.tool(annotations=WRITE)
def browser_download(url: str, path: str | None = None, timeout: int = 120) -> str:
    """Download a URL through Edge and return the saved path, bytes and sha256."""
    import hashlib
    parsed = urllib.parse.urlparse(str(url or "").strip())
    if parsed.scheme not in ("http", "https"):
        raise ValueError("Solo se permiten URLs http/https.")
    folder = DATA_ROOT / "downloads"
    folder.mkdir(parents=True, exist_ok=True)
    if path:
        destination = Path(str(path)).expanduser()
        destination = destination if destination.is_absolute() else folder / destination
        destination.parent.mkdir(parents=True, exist_ok=True)
    else:
        destination = None
    page = _page()
    page.send("Browser.setDownloadBehavior", {"behavior": "allow", "downloadPath": str(folder), "eventsEnabled": True})
    before = {item.name for item in folder.glob("*")}
    _navigate(url)
    deadline = time.monotonic() + max(5, min(int(timeout), 600))
    while time.monotonic() < deadline:
        after = [item for item in folder.glob("*") if item.is_file()]
        new_items = [item for item in after if item.name not in before and not item.name.endswith(".crdownload")]
        if new_items:
            source = max(new_items, key=lambda item: item.stat().st_mtime)
            if destination and source != destination:
                if destination.exists():
                    destination.unlink()
                source.replace(destination)
                source = destination
            data = source.read_bytes()
            return _result({"ok": True, "path": str(source), "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()})
        time.sleep(0.5)
    raise CdpError("La descarga no terminó a tiempo.")


@mcp.tool(annotations=WRITE)
def tabs(action: str = "list", url: str | None = None, index: int | None = None) -> str:
    """Manage autonomous browser tabs: list, new, switch, close."""
    port = STATE["port"]
    pages = _list_pages()
    if action == "list":
        return _result([{"index": i, "url": item.get("url"), "title": item.get("title"), "id": item.get("id")} for i, item in enumerate(pages)])
    if action == "new":
        _start()
        port = STATE["port"]
        target = _http_json(f"http://127.0.0.1:{port}/json/new?url=" + urllib.parse.quote(url or "about:blank", safe=""), method="PUT")
        page = _connect_target(target)
        if url:
            page = _navigate(url)
        return _result({"ok": True, "url": page.evaluate("location.href")})
    if action == "switch":
        if index is None or not 0 <= int(index) < len(pages):
            raise ValueError("Índice de pestaña no válido.")
        _connect_target(pages[int(index)])
        return _result({"ok": True, "url": pages[int(index)].get("url")})
    if action == "close":
        if index is None or not 0 <= int(index) < len(pages):
            raise ValueError("Índice de pestaña no válido.")
        target = pages[int(index)]
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/json/close/" + str(target.get("id")), timeout=5) as response:
            response.read(1024)
        remaining = _list_pages()
        if remaining:
            _connect_target(remaining[0])
        return _result({"ok": True, "remaining": len(remaining)})
    raise ValueError("Acción de pestañas no válida.")


@mcp.tool(annotations=WRITE)
def close() -> str:
    """Close the autonomous Edge browser and its isolated profile process."""
    _close_browser()
    return _result({"ok": True, "closed": True})


def _close_browser():
    with LOCK:
        page = STATE.get("cdp")
        STATE["cdp"] = None
        if page:
            page.close()
        process = STATE.get("process")
        STATE["process"] = None
        if process and process.poll() is None:
            try:
                subprocess.run(["taskkill", "/F", "/T", "/PID", str(process.pid)], capture_output=True, timeout=15,
                               creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            except Exception:
                try:
                    process.terminate()
                except Exception:
                    pass


atexit.register(_close_browser)

if __name__ == "__main__":
    mcp.run()
