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
STATE = {"process": None, "port": None, "cdp": None, "target": None, "pages": {}}
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
        self.request_urls: dict[str, str] = {}
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
                    method = message["method"]
                    params = message.get("params") or {}
                    if method == "Network.requestWillBeSent":
                        req_id = params.get("requestId")
                        req_url = (params.get("request") or {}).get("url")
                        if req_id and req_url:
                            self.request_urls[str(req_id)] = str(req_url)
                            if len(self.request_urls) > 400:
                                self.request_urls.pop(next(iter(self.request_urls)))
                    self.events.append((time.time(), method, params))
                    if len(self.events) > 300:
                        self.events = self.events[-300:]
        except Exception:
            if not self.closed:
                for slot in list(self.pending.values()):
                    slot["event"].set()
            return

    def send(self, method: str, params: dict | None = None, timeout: float = 30):
        if self.closed:
            raise CdpError("Browser tab is closed.")
        slot = {"event": threading.Event(), "result": None}
        with self.lock:
            self.next_id += 1
            ident = self.next_id
            self.pending[ident] = slot
        try:
            self.ws.send(json.dumps({"id": ident, "method": method, "params": params or {}}, ensure_ascii=False))
            if not slot["event"].wait(timeout):
                raise CdpError("Browser did not respond to " + method + ".")
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
        Path(os.environ.get("PROGRAMFILES(X86)", r"C:\Program Files (x86)")) / "Microsoft/Edge/Application/msedge.exe",
        Path(os.environ.get("PROGRAMFILES", r"C:\Program Files")) / "Microsoft/Edge/Application/msedge.exe",
        os.environ.get("VAL_EDGE_PATH", ""),  # Respect an explicit legacy configuration.
    ]
    for value in candidates:
        if value and Path(value).is_file():
            return Path(value)
    raise CdpError("No supported browser executable was found (bundled shell, Brave or Edge). Reinstall V-Agent or set VAL_BROWSER_PATH.")


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
    target_id = target.get("id")
    pages = STATE.setdefault("pages", {})
    cached = pages.get(target_id) if target_id else None
    if cached and not cached.closed:
        cached.target = target
        STATE["cdp"] = cached
        STATE["target"] = target
        return cached
    page = CdpPage(target["webSocketDebuggerUrl"], target)
    for method in ("Page.enable", "Runtime.enable", "Network.enable", "Log.enable"):
        try:
            page.send(method, {}, timeout=10)
        except CdpError:
            pass
    if target_id:
        pages[target_id] = page
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
                raise CdpError("Browser exited during startup.")
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
        raise CdpError("Browser did not open the debugging port.")


def _page() -> CdpPage:
    cdp = STATE.get("cdp")
    if cdp and not cdp.closed:
        target_id = (STATE.get("target") or {}).get("id")
        try:
            live_ids = {p.get("id") for p in _list_pages() if p.get("id")}
        except Exception:
            live_ids = set()
        if not target_id or not live_ids or target_id in live_ids:
            return cdp
        cdp.close()
        STATE.setdefault("pages", {}).pop(target_id, None)
        STATE["cdp"] = None
    pages = _list_pages()
    if pages:
        return _connect_target(pages[0])
    return _start()


def _navigate(url: str, wait: bool = True):
    parsed = urllib.parse.urlparse(str(url or "").strip())
    if parsed.scheme not in ("http", "https"):
        raise ValueError("Only http/https URLs are allowed.")
    target = parsed.geturl()
    page = _page()
    nav = page.send("Page.navigate", {"url": target}, timeout=30)
    err = nav.get("errorText") if isinstance(nav, dict) else None
    if err and err != "net::ERR_ABORTED":
        raise CdpError(f"Navigation failed ({err}) for {target}")
    if wait:
        deadline = time.monotonic() + 30
        interactive_since = None
        while time.monotonic() < deadline:
            try:
                state = page.evaluate("document.readyState")
                if state == "complete":
                    time.sleep(0.25)
                    break
                if state == "interactive":
                    if interactive_since is None:
                        interactive_since = time.monotonic()
                    elif time.monotonic() - interactive_since >= 4.0:
                        break
            except CdpError:
                pass
            time.sleep(0.2)
    return page


_FIND_EL_JS = """const findEl = (sel, root = document) => {
  if (!root || !sel) return null;
  let hit = null;
  try { hit = root.querySelector(sel); } catch { return null; }
  if (hit) return hit;
  for (const el of root.querySelectorAll('*')) {
    if (el.shadowRoot) {
      hit = findEl(sel, el.shadowRoot);
      if (hit) return hit;
    }
    if (el.tagName === 'IFRAME' || el.tagName === 'FRAME') {
      try { if (el.contentDocument) { hit = findEl(sel, el.contentDocument); if (hit) return hit; } } catch {}
    }
  }
  return null;
};"""


def _snapshot_js(max_chars: int, max_items: int = 50) -> str:
    return """(() => {
      const clean = value => String(value == null ? '' : value).replace(/\\s+/g, ' ').trim();
      const visible = el => {
        const style = (el.ownerDocument.defaultView || window).getComputedStyle(el), rect = el.getBoundingClientRect();
        return style.display !== 'none' && style.visibility !== 'hidden' && rect.width > 0 && rect.height > 0;
      };
      const collectRoots = (root, out = []) => {
        if (!root) return out;
        out.push(root);
        for (const el of root.querySelectorAll('*')) {
          if (el.shadowRoot) collectRoots(el.shadowRoot, out);
          if (el.tagName === 'IFRAME' || el.tagName === 'FRAME') {
            try { if (el.contentDocument) collectRoots(el.contentDocument, out); } catch {}
          }
        }
        return out;
      };
      const cleanHref = raw => {
        if (!raw) return '';
        try {
          const u = new URL(raw);
          if (u.hostname.endsWith('bing.com') && u.pathname.startsWith('/ck/a')) {
            const p = u.searchParams.get('u') || '';
            if (p.startsWith('a1') && p.length > 2) {
              const b64 = p.slice(2).replace(/-/g, '+').replace(/_/g, '/');
              const pad = b64 + '==='.slice((b64.length + 3) % 4);
              const bytes = Uint8Array.from(atob(pad), c => c.charCodeAt(0));
              const dec = new TextDecoder().decode(bytes);
              if (/^https?:\\/\\//i.test(dec)) return cleanHref(dec);
            }
            return u.origin + u.pathname;
          }
          for (const k of ['fbclid','gclid','msclkid','mc_eid','cvid','rdr','rdrig','pq','sc','sk','sp','lq','form','ved','ei','sa','opi','sca_esv']) {
            u.searchParams.delete(k);
          }
          for (const k of [...u.searchParams.keys()]) {
            if (k.startsWith('utm_')) u.searchParams.delete(k);
          }
          return u.toString().slice(0, 180);
        } catch {
          return String(raw).slice(0, 180);
        }
      };
      const roots = collectRoots(document);
      for (const r of roots) r.querySelectorAll('[data-val-ref]').forEach(el => el.removeAttribute('data-val-ref'));
      const cap = """ + str(int(max_items)) + """;
      const token = 'val' + Date.now().toString(36), items = [], seen = new Set();
      let more = 0;
      const selector = 'a[href],button,input,select,textarea,[role=button],[role=link],[role=textbox],[contenteditable=true],[onclick]';
      const nodes = [];
      for (const r of roots) for (const el of r.querySelectorAll(selector)) nodes.push(el);
      for (const el of nodes) {
        if (!visible(el)) continue;
        const tag = el.tagName.toLowerCase();
        const type = clean(el.getAttribute('type') || el.getAttribute('role') || '');
        const text = clean(el.getAttribute('aria-label') || el.getAttribute('title') || el.innerText || el.getAttribute('placeholder') || '').slice(0, 120);
        const name = clean(el.getAttribute('name') || '');
        const href = el.href ? cleanHref(String(el.href)) : '';
        if (tag === 'a' && !text && !name) continue;
        const sig = tag === 'a' ? (tag + '|' + text + '|' + href) : '';
        if (sig && seen.has(sig)) continue;
        if (sig) seen.add(sig);
        if (items.length >= cap) { more += 1; continue; }
        const ref = token + '-' + (items.length + 1);
        el.setAttribute('data-val-ref', ref);
        const item = {selector: '[data-val-ref="' + ref + '"]', tag};
        if (type) item.type = type;
        if (text) item.text = text;
        if (name) item.name = name;
        if (href) item.href = href;
        if (el.disabled) item.disabled = true;
        if (el.checked) item.checked = true;
        items.push(item);
      }
      const collectPageText = () => {
        const cap = """ + str(int(max_chars)) + """;
        const base = document.body ? (document.body.innerText || '') : '';
        if (roots.length <= 1) return base.slice(0, cap);
        const parts = [], seenText = new Set();
        const addChunk = raw => {
          const s = String(raw || '').trim();
          if (s && !seenText.has(s)) { seenText.add(s); parts.push(s); }
        };
        addChunk(base);
        for (const r of roots.slice(1)) {
          if (r.host && r.host.shadowRoot === r) {
            for (const child of r.childNodes) {
              if (child.nodeType === 1 && !['SCRIPT','STYLE','TEMPLATE'].includes(child.tagName)) {
                addChunk(child.innerText || child.textContent);
              } else if (child.nodeType === 3) {
                addChunk(child.nodeValue);
              }
            }
          } else if (r.body) {
            addChunk(r.body.innerText);
          }
        }
        return parts.join('\\n').slice(0, cap);
      };
      const out = {ok: true, title: document.title, url: cleanHref(location.href) || location.href,
        text: collectPageText(), items};
      if (more) out.more_items = more;
      return out;
    })()"""


def _wait_selector(page: CdpPage, selector: str, timeout: float = 15):
    deadline = time.monotonic() + timeout
    expr = f"(() => {{ {_FIND_EL_JS} return !!findEl({json.dumps(selector)}); }})()"
    while time.monotonic() < deadline:
        try:
            if page.evaluate(expr):
                return True
        except CdpError:
            pass
        time.sleep(0.25)
    return False


def _result(value):
    return json.dumps(value, ensure_ascii=False)


def _active_tab_meta() -> tuple[int, int]:
    pages = _list_pages()
    active_id = (STATE.get("target") or {}).get("id")
    idx = next((i for i, item in enumerate(pages) if item.get("id") == active_id), 0 if pages else -1)
    return idx, len(pages)


def _server_gate_hint(url: str, title: str, text: str = "", link_count: int | None = None, body_len: int | None = None) -> dict | None:
    low_url = str(url or "").lower()
    low_title = str(title or "").lower()
    low_head = str(text or "")[:3000].lower()
    full_len = int(body_len) if body_len is not None else len(text or "")
    has_results = (link_count is not None and int(link_count) >= 3) or full_len >= 2200
    if not has_results and any(p in low_head for p in (
        "no search results found",
        "only supports queries in the english language",
        "did not match any documents",
        "no results found for",
    )):
        return {"empty_results": True}
    reason = None
    gate_kind = "hard"
    if "home-error/418" in low_url or "protection. privacy. peace of mind" in low_title:
        reason = "Site returned an anti-bot HTTP 418/CAPTCHA gate."
    elif "/sorry/" in low_url or "sorry/index" in low_url or ((not has_results or "google." in low_url) and ("unusual traffic" in low_head or "detected unusual" in low_head or "unusual traffic" in low_title)):
        reason = "Site flagged automated traffic (/sorry/ unusual traffic gate)."
    elif "challenge-platform" in low_url or "challenge-platform" in low_head or "cf-challenge" in low_head or (not has_results and ("checking your browser" in low_head or "verifying your browser" in low_head or "verifying you are human" in low_head or "performing security verification" in low_head or "enable javascript and cookies to continue" in low_head or ("just a moment" in (low_title + " " + low_head) and ("cloudflare" in low_head or "verify" in low_head or "ray id" in low_head or not low_head.strip())))):
        reason = "Site presented a Cloudflare / JavaScript challenge gate."
    elif not has_results and (("wait a moment" in (low_title + " " + low_head) and any(k in low_head for k in ("bot activity", "please wait", "before proceeding", "checking"))) or ("enable javascript" in low_head and any(k in low_head for k in ("proceed", "continue", "challenge", "browser", "cookies")))):
        reason = "Site presented an anti-bot interstitial wait/JS gate instead of content."
        gate_kind = "interstitial"
    elif "captcha" in low_title or "altcha" in low_head or (not has_results and ("verify you are human" in low_head or "robot or human" in low_title + " " + low_head or "pardon our interruption" in low_title + " " + low_head or ("un último paso" in low_head and "desafío" in low_head))) or ("captcha" in low_head and full_len < 40000):
        reason = "Site presented a server-side CAPTCHA / human-verification challenge."
    elif not has_results and "sorry! something has gone wrong" in low_head and ("bot" in (low_title + " " + low_head) or "automated" in low_head):
        reason = "Site blocked automated headless access on the server side."
    if not reason:
        return None
    suggestion = (
        "Site returned a temporary wait/JS interstitial instead of content; suggest the user open it in the visible browser or verify manually."
        if gate_kind == "interstitial"
        else "Site blocked automated headless access on the server side; suggest the user open or verify it directly in the visible browser."
    )
    return {
        "server_blocked": True,
        "gate_kind": gate_kind,
        "blocked_reason": reason,
        "alternatives": [
            "pc__browser (visible browser with your session)",
            "duckduckgo__web_search (text web search)",
            "Public JSON/REST APIs via web__http_request",
        ],
        "user_suggestion": suggestion,
    }


def _gate_body_info(page: CdpPage) -> tuple[str, int | None, int | None]:
    try:
        value = page.evaluate("""(() => {
  const txt = (document.body ? document.body.innerText : '') || '';
  const links = Array.from(document.querySelectorAll('a[href]')).filter(a => {
    const t = (a.innerText || '').trim();
    const r = a.getBoundingClientRect();
    return t.length > 0 && r.width > 0 && r.height > 0;
  }).length;
  return {head: txt.slice(0, 2000), len: txt.length, links};
})()""")
        if isinstance(value, dict):
            head = str(value.get("head") or "")
            raw_len = value.get("len")
            raw_links = value.get("links")
            return head, (int(raw_len) if isinstance(raw_len, (int, float)) else len(head)), (int(raw_links) if isinstance(raw_links, (int, float)) else None)
        if isinstance(value, str):
            return value, len(value), None
        return "", None, None
    except CdpError:
        return "", None, None


def _with_gate_hint(payload: dict, body_head: str = "", link_count: int | None = None, body_len: int | None = None) -> dict:
    hint = _server_gate_hint(payload.get("url", ""), payload.get("title", ""), payload.get("text") or body_head, link_count=link_count, body_len=body_len)
    if hint:
        payload.update(hint)
    return payload


@mcp.tool(annotations=WRITE)
def open(url: str, new_tab: bool = False) -> str:
    """Open a URL in the autonomous browser; new_tab=true opens and activates a new tab (returns active_index)."""
    if new_tab:
        port = _start().target and STATE["port"]
        target = _http_json(f"http://127.0.0.1:{port}/json/new?url=" + urllib.parse.quote(url, safe=""), method="PUT")
        _connect_target(target)
    page = _navigate(url)
    active_idx, tab_count = _active_tab_meta()
    out = {
        "ok": True,
        "url": page.evaluate("location.href"),
        "title": page.evaluate("document.title"),
        "active_index": active_idx,
        "tab_count": tab_count,
    }
    if new_tab:
        out["new_tab"] = True
        out["switched"] = True
    head, blen, links = _gate_body_info(page)
    return _result(_with_gate_hint(out, head, link_count=links, body_len=blen))


@mcp.tool(annotations=WRITE)
def navigate(url: str) -> str:
    """Navigate the current autonomous browser tab to an http/https URL."""
    page = _navigate(url)
    head, blen, links = _gate_body_info(page)
    return _result(_with_gate_hint({"ok": True, "url": page.evaluate("location.href"), "title": page.evaluate("document.title")}, head, link_count=links, body_len=blen))


@mcp.tool(annotations=READ)
def snapshot(max_chars: int = 12000, max_items: int = 50) -> str:
    """Return page title, URL, text excerpt and compact interactive selectors (capped by max_items and budget)."""
    chars_cap = max(500, min(int(max_chars), 20000))
    items_cap = max(1, min(int(max_items), 150))
    data = _page().evaluate(_snapshot_js(chars_cap, items_cap))
    if isinstance(data, dict) and isinstance(data.get("items"), list):
        items = data["items"]
        total_links = sum(1 for item in items if isinstance(item, dict) and item.get("tag") == "a")
        omitted = int(data.get("more_items") or 0)
        while len(items) > 5 and len(json.dumps(items, ensure_ascii=False)) > 6000:
            items.pop()
            omitted += 1
        if omitted:
            data["more_items"] = omitted
        data = _with_gate_hint(data, link_count=total_links)
    return _result(data)


@mcp.tool(annotations=READ)
def text(max_chars: int = 12000) -> str:
    """Read visible page text."""
    cap = max(500, min(int(max_chars), 20000))
    page = _page()
    extracted = page.evaluate("""(() => {
      const parts = [];
      const seenDocs = new Set();
      const walk = (root) => {
        if (!root || seenDocs.has(root)) return;
        seenDocs.add(root);
        if (root.body && root.body.innerText) parts.push(root.body.innerText);
        for (const el of root.querySelectorAll('*')) {
          if (el.shadowRoot && el.shadowRoot.textContent) {
            const st = String(el.shadowRoot.textContent || '').trim();
            if (st) parts.push(st);
          }
          if (el.tagName === 'IFRAME' || el.tagName === 'FRAME') {
            try { if (el.contentDocument) walk(el.contentDocument); } catch {}
          }
        }
      };
      walk(document);
      return parts.join('\\n').slice(0, """ + str(cap) + """);
    })()""")
    head, blen, links = _gate_body_info(page)
    return _result(_with_gate_hint({
        "url": page.evaluate("location.href"),
        "title": page.evaluate("document.title"),
        "text": extracted if isinstance(extracted, str) else head,
    }, head, link_count=links, body_len=blen))


def _await_load(page: CdpPage, before_url: str, before_ids: set[str], timeout: float = 1.2) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        after_pages = _list_pages()
        new_pages = [item for item in after_pages if item.get("id") and item.get("id") not in before_ids]
        if new_pages:
            target = new_pages[-1]
            new_page = _connect_target(target)
            load_deadline = time.monotonic() + 5.0
            while time.monotonic() < load_deadline:
                try:
                    if new_page.evaluate("document.readyState") in ("interactive", "complete"):
                        break
                except CdpError:
                    pass
                time.sleep(0.15)
            try:
                cur_url = new_page.evaluate("location.href") or target.get("url") or ""
                cur_title = new_page.evaluate("document.title") or target.get("title") or ""
            except CdpError:
                cur_url = target.get("url") or ""
                cur_title = target.get("title") or ""
            pages_now = _list_pages()
            idx = next((i for i, p in enumerate(pages_now) if p.get("id") == target.get("id")), 0)
            nav = {"new_tab": True, "tab_index": idx, "active_index": idx, "tab_count": len(pages_now), "url": cur_url, "title": cur_title}
            head, blen, links = _gate_body_info(new_page)
            return _with_gate_hint(nav, head, link_count=links, body_len=blen)
        try:
            cur_url = page.evaluate("location.href") or ""
        except CdpError:
            cur_url = ""
        if cur_url and cur_url != before_url:
            load_deadline = time.monotonic() + 3.0
            interactive_since = None
            while time.monotonic() < load_deadline:
                try:
                    st = page.evaluate("document.readyState")
                    if st == "complete":
                        time.sleep(0.15)
                        break
                    if st == "interactive":
                        if interactive_since is None:
                            interactive_since = time.monotonic()
                        elif time.monotonic() - interactive_since >= 1.5:
                            break
                except CdpError:
                    pass
                time.sleep(0.15)
            try:
                cur_url = page.evaluate("location.href") or cur_url
                cur_title = page.evaluate("document.title") or ""
            except CdpError:
                cur_title = ""
            head, blen, links = _gate_body_info(page)
            return _with_gate_hint({"navigated": True, "url": cur_url, "title": cur_title}, head, link_count=links, body_len=blen)
        time.sleep(0.15)
    return {}


@mcp.tool(annotations=WRITE)
def click(selector: str) -> str:
    """Click an element by CSS selector."""
    page = _page()
    before_ids = {item.get("id") for item in _list_pages() if item.get("id")}
    try:
        before_url = page.evaluate("location.href") or ""
    except CdpError:
        before_url = ""
    value = page.evaluate("""(() => { %s const el=findEl(%s); if(!el) return {ok:false,error:'selector not found'}; el.scrollIntoView({block:'center',inline:'center'}); el.focus({preventScroll:true}); el.click(); return {ok:true,tag:el.tagName.toLowerCase(),text:(el.innerText||'').slice(0,120)}; })()""" % (_FIND_EL_JS, json.dumps(selector)))
    if isinstance(value, dict) and value.get("ok"):
        value.update(_await_load(page, before_url, before_ids, timeout=1.2))
    return _result(value)


def _fill_file_input(page: CdpPage, selector: str, text: str) -> dict:
    raw = str(text or "").strip()
    if not raw:
        raise ValueError("File path is required for <input type=\"file\">.")
    candidates = [p.strip() for p in raw.splitlines() if p.strip()] if "\n" in raw else [raw]
    resolved: list[str] = []
    for item in candidates:
        candidate = Path(item).expanduser()
        if not candidate.is_file():
            return {"ok": False, "error": f"File not found: {item}"}
        resolved.append(str(candidate.resolve()))
    probe = page.send("Runtime.evaluate", {
        "expression": "(() => { %s return findEl(%s); })()" % (_FIND_EL_JS, json.dumps(selector)),
        "returnByValue": False,
        "userGesture": True,
    }, timeout=15)
    if probe.get("exceptionDetails"):
        raise CdpError(str(probe["exceptionDetails"].get("text") or probe["exceptionDetails"]))
    obj_id = (probe.get("result") or {}).get("objectId")
    if not obj_id:
        return {"ok": False, "error": "selector not found"}
    page.send("DOM.enable", {}, timeout=10)
    page.send("DOM.setFileInputFiles", {"files": resolved, "objectId": obj_id}, timeout=15)
    page.send("Runtime.callFunctionOn", {
        "objectId": obj_id,
        "functionDeclaration": "function(){this.dispatchEvent(new Event('input',{bubbles:true}));this.dispatchEvent(new Event('change',{bubbles:true}));}",
        "returnByValue": True,
    }, timeout=10)
    return {"ok": True, "files": resolved, "value": resolved[0] if len(resolved) == 1 else resolved}


@mcp.tool(annotations=WRITE)
def fill(selector: str, text: str) -> str:
    """Fill an input, textarea, select, contenteditable or file (<input type="file">) element."""
    page = _page()
    probe = page.evaluate("""(() => { %s const el=findEl(%s); if(!el) return {found:false}; return {found:true,tag:el.tagName,type:(el.type||'').toLowerCase()}; })()""" % (_FIND_EL_JS, json.dumps(selector)))
    if isinstance(probe, dict) and probe.get("found") and probe.get("tag") == "INPUT" and probe.get("type") == "file":
        return _result(_fill_file_input(page, selector, text))
    value = page.evaluate("""(() => { %s const el=findEl(%s); if(!el) return {ok:false,error:'selector not found'}; el.focus({preventScroll:true});
      if(el.isContentEditable){el.textContent=%s;el.dispatchEvent(new InputEvent('input',{bubbles:true,inputType:'insertText',data:%s}));}
      else {const w=el.ownerDocument.defaultView||window;const proto=el instanceof w.HTMLTextAreaElement?w.HTMLTextAreaElement.prototype:el instanceof w.HTMLSelectElement?w.HTMLSelectElement.prototype:w.HTMLInputElement.prototype;
        const setter=Object.getOwnPropertyDescriptor(proto,'value')?.set;if(setter)setter.call(el,%s);else el.value=%s;
        el.dispatchEvent(new Event('input',{bubbles:true}));}
      el.dispatchEvent(new Event('change',{bubbles:true})); return {ok:true,value:String(el.value==null?el.textContent:el.value).slice(0,200)}; })()""" % (_FIND_EL_JS, json.dumps(selector), json.dumps(text), json.dumps(text), json.dumps(text), json.dumps(text)))
    return _result(value)


@mcp.tool(annotations=WRITE)
def press(key: str = "Enter", selector: str | None = None) -> str:
    """Send a key to the page or to a selector. Enter submits its form (handles autocomplete popups that eat the first Enter)."""
    selector = selector or "body"
    page = _page()
    before_ids = {item.get("id") for item in _list_pages() if item.get("id")}
    try:
        before_url = page.evaluate("location.href") or ""
    except CdpError:
        before_url = ""
    key_js = """((sel, k, doSubmit) => {
      """ + _FIND_EL_JS + """
      const el = findEl(sel) || document.body;
      el.focus({preventScroll: true});
      const keyCodes = {Enter:13, Escape:27, Tab:9, Backspace:8, ArrowUp:38, ArrowDown:40, ArrowLeft:37, ArrowRight:39};
      const code = k.length === 1 && /[a-z]/i.test(k) ? 'Key' + k.toUpperCase() : k;
      const keyCode = keyCodes[k] ?? (k.length === 1 ? k.toUpperCase().charCodeAt(0) : 0);
      const o = {key: k, code, keyCode, which: keyCode, bubbles: true, cancelable: true};
      el.dispatchEvent(new KeyboardEvent('keydown', o));
      el.dispatchEvent(new KeyboardEvent('keypress', o));
      el.dispatchEvent(new KeyboardEvent('keyup', o));
      let submitted = false;
      if (k === 'Enter' && doSubmit) {
        const f = el.form || el.closest('form');
        if (f) { try { f.requestSubmit(); submitted = true; } catch {} }
        else {
          const btn = document.querySelector('button[type=submit], input[type=submit]');
          if (btn) { try { btn.click(); submitted = true; } catch {} }
        }
      }
      return {ok: true, pressed: k, submitted};
    })"""
    value = page.evaluate(f"({key_js})({json.dumps(selector)}, {json.dumps(key)}, false)")
    nav = {}
    if isinstance(value, dict) and value.get("ok"):
        if key == "Enter":
            nav = _await_load(page, before_url, before_ids, timeout=0.55)
            if not nav:
                # If an autocomplete dropdown swallowed the first Enter, wait briefly and submit/press again.
                time.sleep(0.08)
                retry = page.evaluate(f"({key_js})({json.dumps(selector)}, 'Enter', true)")
                if isinstance(retry, dict) and retry.get("submitted"):
                    value["submitted"] = True
                nav = _await_load(page, before_url, before_ids, timeout=1.0)
        else:
            nav = _await_load(page, before_url, before_ids, timeout=0.25)
        if nav:
            value.update(nav)
            if key == "Enter" and (nav.get("navigated") or nav.get("new_tab")):
                value["submitted"] = True
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
def cookies(include_values: bool = False, domain: str | None = None) -> str:
    """Summarize cookies of the autonomous browser profile by domain/count; set include_values=true to read values."""
    value = _page().send("Network.getAllCookies")
    items = value.get("cookies") or []
    if domain:
        needle = domain.strip().lower()
        items = [item for item in items if needle in str(item.get("domain") or "").lower()]
    domains: dict[str, int] = {}
    compact = []
    for item in items:
        dom = str(item.get("domain") or "")
        domains[dom] = domains.get(dom, 0) + 1
        entry = {
            "name": item.get("name"),
            "domain": dom,
            "path": item.get("path"),
            "secure": bool(item.get("secure")),
            "httpOnly": bool(item.get("httpOnly")),
            "session": bool(item.get("session")),
        }
        if include_values:
            entry["value"] = item.get("value")
        else:
            entry["value_len"] = len(str(item.get("value") or ""))
        compact.append(entry)
    return _result({"ok": True, "count": len(compact), "domains": domains, "cookies": compact[:80], "truncated": len(compact) > 80})


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
            req_id = params.get("requestId")
            items.append({"type": "failed", "error": params.get("errorText"), "url": page.request_urls.get(str(req_id or "")) or req_id})
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
        raise ValueError("Only http/https URLs are allowed.")
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
        new_items = [item for item in after if item.name not in before and not item.name.endswith((".crdownload", ".tmp"))]
        if new_items:
            source = max(new_items, key=lambda item: item.stat().st_mtime)
            if destination and source != destination:
                import shutil
                if destination.exists():
                    destination.unlink()
                shutil.move(str(source), str(destination))
                source = destination
            data = source.read_bytes()
            return _result({"ok": True, "path": str(source), "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()})
        time.sleep(0.5)
    raise CdpError("Download did not finish in time.")


@mcp.tool(annotations=WRITE)
def tabs(action: str = "list", url: str | None = None, index: int | None = None, switch: bool = True) -> str:
    """Manage autonomous browser tabs: list, new (returns active_index; set switch=false to keep current tab), switch, close."""
    port = STATE["port"]
    pages = _list_pages()
    active_id = (STATE.get("target") or {}).get("id")
    if action == "list":
        rows = [{"index": i, "active": item.get("id") == active_id, "url": item.get("url"), "title": item.get("title"), "id": item.get("id")} for i, item in enumerate(pages)]
        active_idx, _ = _active_tab_meta()
        return _result({"ok": True, "active_index": active_idx, "count": len(rows), "tabs": rows})
    if action == "new":
        if url:
            parsed = urllib.parse.urlparse(str(url).strip())
            if parsed.scheme not in ("http", "https"):
                raise ValueError("Only http/https URLs are allowed.")
        prev_target = STATE.get("target")
        _start()
        port = STATE["port"]
        target = _http_json(f"http://127.0.0.1:{port}/json/new?url=about:blank", method="PUT")
        page = _connect_target(target)
        try:
            if url:
                page = _navigate(url)
            cur_url = page.evaluate("location.href")
        finally:
            if not switch and prev_target and any(p.get("id") == prev_target.get("id") for p in _list_pages()):
                _connect_target(prev_target)
        active_idx, tab_count = _active_tab_meta()
        new_idx = next((i for i, p in enumerate(_list_pages()) if p.get("id") == target.get("id")), tab_count - 1)
        return _result({"ok": True, "url": cur_url, "new_tab_index": new_idx, "active_index": active_idx, "tab_count": tab_count, "switched": bool(switch)})
    if action == "switch":
        if index is None or not 0 <= int(index) < len(pages):
            raise ValueError("Invalid tab index.")
        _connect_target(pages[int(index)])
        return _result({"ok": True, "active_index": int(index), "tab_count": len(pages), "url": pages[int(index)].get("url")})
    if action == "close":
        if index is None or not 0 <= int(index) < len(pages):
            raise ValueError("Invalid tab index.")
        target = pages[int(index)]
        closed_id = target.get("id")
        cached = STATE.setdefault("pages", {}).pop(closed_id, None) if closed_id else None
        if cached:
            if STATE.get("cdp") is cached:
                STATE["cdp"] = None
            cached.close()
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/json/close/" + str(closed_id), timeout=5) as response:
            response.read(1024)
        remaining = _list_pages()
        if not remaining:
            STATE["cdp"] = None
            STATE["target"] = None
        elif closed_id == active_id or not STATE.get("cdp") or STATE["cdp"].closed:
            _connect_target(remaining[0])
        active_idx, tab_count = _active_tab_meta()
        return _result({"ok": True, "remaining": len(remaining), "active_index": active_idx, "tab_count": tab_count})
    raise ValueError("Invalid tab action.")


@mcp.tool(annotations=WRITE)
def close() -> str:
    """Close the autonomous Edge browser and its isolated profile process."""
    _close_browser()
    return _result({"ok": True, "closed": True})


def _close_browser():
    with LOCK:
        page = STATE.get("cdp")
        STATE["cdp"] = None
        STATE["target"] = None
        STATE["port"] = None
        for cached in list(STATE.setdefault("pages", {}).values()):
            try:
                cached.close()
            except Exception:
                pass
        STATE["pages"].clear()
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
