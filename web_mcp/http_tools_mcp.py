"""Real HTTP tools for the standard/full agent modes.

This server is deliberately separate from the DuckDuckGo reader: Light mode keeps
the anonymous search/visit pair, while Standard/Fully may send headers, cookies and
bodies, download files and call APIs. URLs are public-only unless allow_private=True.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Literal
from urllib.parse import urlparse, urljoin

import requests
import trafilatura
from bs4 import BeautifulSoup
from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations
from runtime_paths import DATA_ROOT

mcp = FastMCP("VAL HTTP")
READ = ToolAnnotations(readOnlyHint=True, destructiveHint=False, openWorldHint=True)
WRITE = ToolAnnotations(readOnlyHint=False, destructiveHint=False, openWorldHint=True)

METHODS = {"GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"}
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"


def _url(value: str, allow_private: bool) -> str:
    parsed = urlparse(str(value or "").strip())
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise ValueError("Valid http/https URL is required.")
    if parsed.username or parsed.password:
        raise ValueError("Credentials inside the URL are not allowed.")
    if not allow_private:
        import ipaddress
        import socket
        try:
            addresses = socket.getaddrinfo(parsed.hostname, parsed.port or (443 if parsed.scheme == "https" else 80))
        except OSError as error:
            raise ValueError("Could not resolve host: " + str(error)) from None
        if not addresses or any(not ipaddress.ip_address(item[4][0]).is_global for item in addresses):
            raise ValueError("Only public URLs are allowed; pass allow_private=true for localhost/LAN.")
    return parsed.geturl()


def _redirect_guard(allow_private):
    def check(response,*args,**kwargs):
        location=response.headers.get('Location')
        if location and response.is_redirect:_url(urljoin(response.url,location),allow_private)
        return response
    return check


def _fallback_name(url: str, default: str = "download.bin") -> str:
    raw_name = Path(urlparse(url).path).name or default
    clean = "".join(ch if ch.isalnum() or ch in "._-" else "_" for ch in raw_name)[:160].strip("._")
    return clean or default


def _is_text_response(raw: bytes, content_type: str) -> bool:
    ct = (content_type or "").lower()
    if ct.startswith("text/") or any(token in ct for token in ("json", "xml", "javascript", "x-www-form-urlencoded")):
        return True
    if ct or not raw:
        return False
    sample = raw[:4096]
    if any(b < 9 or (13 < b < 32) for b in sample):
        return False
    try:
        sample.decode("utf-8")
        return True
    except UnicodeDecodeError:
        return False


def _target(value: str | None, fallback: str, root: str | None = None) -> Path:
    root = Path(root) if root else DATA_ROOT / "downloads"
    root.mkdir(parents=True, exist_ok=True)
    if value:
        path = Path(str(value)).expanduser()
        if not path.is_absolute():
            path = root / path
    else:
        path = root / fallback
    path = path.resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _server_gate_hint(status: int, final_url: str, content_type: str, body_text: str) -> dict | None:
    lower_url = (final_url or "").lower()
    head = (body_text or "")[:6000].lower()
    full_len = len(body_text or "")
    if full_len < 4000 and any(p in head for p in (
        "no search results found",
        "only supports queries in the english language",
        "did not match any documents",
        "no results found for",
    )):
        return {"empty_results": True}
    reason = None
    gate_kind = "hard"
    if status == 418 or "home-error/418" in lower_url:
        reason = "Server returned anti-bot HTTP 418."
    elif "/sorry/" in lower_url or "sorry/index" in lower_url or ((full_len < 4000 or "google." in lower_url) and ("unusual traffic" in head or "detected unusual" in head)):
        reason = "Server flagged automated traffic (/sorry/ unusual traffic gate)."
    elif "challenge-platform" in lower_url or "challenge-platform" in head or "cf-challenge" in head or (full_len < 25000 and ("checking your browser" in head or "verifying your browser" in head or "verifying you are human" in head or "performing security verification" in head or "enable javascript and cookies to continue" in head or ("just a moment" in head and ("cloudflare" in head or "ray id" in head or "verify" in head or full_len < 15000)))):
        reason = "Server presented a Cloudflare / JavaScript challenge gate."
    elif full_len < 2500 and (("wait a moment" in head and any(k in head for k in ("bot activity", "please wait", "before proceeding", "checking"))) or ("enable javascript" in head and any(k in head for k in ("proceed", "continue", "challenge", "browser", "cookies")))):
        reason = "Server presented an anti-bot interstitial wait/JS gate instead of content."
        gate_kind = "interstitial"
    elif "altcha" in head or "javascript is required to complete this challenge" in head or (full_len < 2500 and ("verify you are human" in head or "robot or human" in head or "pardon our interruption" in head)) or ("captcha" in head and full_len < 40000):
        reason = "Server returned a CAPTCHA or JavaScript challenge that HTTP clients cannot complete."
    elif "google." in lower_url and "/search" in lower_url and ("/httpservice/retry/enablejs" in head or ("google search" in head and full_len < 120000 and "<body" in head)):
        reason = "Google Search returned a JS-only shell without static results."
    elif status in (403, 429) and any(k in head for k in ("cloudflare", "cf-ray", "datadome", "perimeterx", "captcha", "access denied", "challenge", "bot", "robot", "automated")):
        reason = f"Server blocked automated HTTP access (HTTP {status})."
    if not reason:
        return None
    suggestion = (
        "Server returned a temporary wait/JS interstitial instead of content; suggest the user open it in a visible browser."
        if gate_kind == "interstitial"
        else "This site blocked automated HTTP access on the server side; suggest the user open it in a visible browser or use an enabled API/search alternative."
    )
    return {
        "server_blocked": True,
        "gate_kind": gate_kind,
        "blocked_reason": reason,
        "alternatives": [
            "duckduckgo__web_search for programmatic web search",
            "pc__browser for interactive search/browsing in the visible browser",
            "Public JSON/REST APIs (e.g. Wikipedia/GitHub APIs) via web__http_request",
        ],
        "user_suggestion": suggestion,
    }


def _decode_text(raw: bytes, content_type: str, encoding: str | None) -> str:
    text = raw.decode(encoding or "utf-8", errors="replace")
    ct = (content_type or "").lower()
    if "html" not in ct and not raw.lstrip()[:64].lower().startswith((b"<!doctype html", b"<html")):
        return text
    extracted = trafilatura.extract(raw, output_format="markdown", include_links=True, include_tables=True)
    if extracted:
        return extracted
    soup = BeautifulSoup(text, "html.parser")
    for tag in soup(["script", "style", "noscript", "svg", "template", "nav", "footer"]):
        tag.decompose()
    return soup.get_text("\n", strip=True)


def _build_headers(headers: dict | None, default_accept: str = "*/*") -> dict[str, str]:
    request_headers = {"User-Agent": UA, "Accept": default_accept}
    if isinstance(headers, dict):
        for key, value in headers.items():
            if isinstance(key, str) and isinstance(value, str) and not any(c in key or c in value for c in "\r\n"):
                request_headers[key] = value
    return request_headers


@mcp.tool(annotations=WRITE)
def http_request(url: str, method: str = "GET", headers: dict | None = None,
                 body: str | dict | list | None = None, body_base64: str | None = None,
                 cookies: dict | None = None, timeout: int = 60,
                 max_bytes: int = 10_000_000, allow_redirects: bool = True,
                 allow_private: bool = False,
                 format: Literal["auto", "text", "markdown", "readability", "json", "base64"] = "auto",
                 extract: Literal["readability", "markdown", "text"] | None = None,
                 save_path: str | None = None, download_dir: str | None = None) -> str:
    """Send a real HTTP request. Returns status, headers, size and extracted/raw text, or a saved path. Truncates cleanly at max_bytes when reading. format=auto|text|markdown|readability|json|base64; extract=readability."""
    method = str(method or "GET").upper()
    if method not in METHODS:
        raise ValueError("Unsupported HTTP method.")
    fmt = str(format or "auto").strip().lower()
    if fmt not in ("auto", "text", "markdown", "readability", "json", "base64"):
        raise ValueError("Unsupported format; use auto, text, markdown, readability, json or base64.")
    ext = str(extract or "").strip().lower()
    if ext and ext not in ("readability", "markdown", "text"):
        raise ValueError("Unsupported extract mode; use readability, markdown or text.")
    timeout = max(1, min(int(timeout), 300))
    max_bytes = max(1024, min(int(max_bytes), 100_000_000))
    request_headers = _build_headers(headers)
    payload: bytes | None
    if body_base64:
        payload = base64.b64decode(body_base64, validate=True)
    elif isinstance(body, (dict, list)):
        payload = json.dumps(body, ensure_ascii=False).encode("utf-8")
        if not any(k.lower() == "content-type" for k in request_headers):
            request_headers["Content-Type"] = "application/json"
    elif body is not None:
        payload = str(body).encode("utf-8")
    else:
        payload = None
    target = _url(url, allow_private)
    session = requests.Session()
    session.trust_env = True
    session.hooks['response'].append(_redirect_guard(allow_private))
    try:
        with session.request(method, target, headers=request_headers, data=payload,
                             cookies=cookies if isinstance(cookies, dict) else None,
                             timeout=(min(10, timeout), timeout), stream=True,
                             allow_redirects=bool(allow_redirects)) as response:
            content_type = response.headers.get("Content-Type", "")
            chunks = bytearray()
            byte_truncated = False
            for chunk in response.iter_content(65536):
                if not chunk:
                    continue
                chunks.extend(chunk)
                if len(chunks) > max_bytes:
                    byte_truncated = True
                    break
            raw = bytes(chunks[:max_bytes])
            saved = None
            text_like = _is_text_response(raw, content_type)
            if save_path:
                if byte_truncated:
                    raise ValueError(f"Response exceeded {max_bytes} bytes before save; use download or increase max_bytes.")
                destination = _target(save_path, _fallback_name(response.url, "response.bin"), download_dir)
                destination.write_bytes(raw)
                saved = str(destination)
            elif fmt == "auto" and not ext and not text_like:
                destination = _target(None, _fallback_name(response.url, "response.bin"), download_dir)
                destination.write_bytes(raw)
                saved = str(destination)
            text = ""
            if not saved:
                if fmt == "base64":
                    text = base64.b64encode(raw).decode("ascii")
                elif "json" in content_type.lower() and fmt in ("auto", "json") and not ext:
                    text = raw.decode(response.encoding or "utf-8", errors="replace")
                elif text_like or ext or fmt in ("readability", "markdown"):
                    if ext in ("readability", "markdown") or fmt in ("auto", "markdown", "readability"):
                        text = _decode_text(raw, content_type, response.encoding)
                        if not text and byte_truncated:
                            text = raw.decode(response.encoding or "utf-8", errors="replace")
                    else:
                        text = raw.decode(response.encoding or "utf-8", errors="replace")
            payload_out = {
                "ok": 200 <= response.status_code < 400,
                "status": response.status_code,
                "url": response.url,
                "content_type": content_type,
                "bytes": len(raw),
                "saved_path": saved,
                "sha256": hashlib.sha256(raw).hexdigest() if saved else None,
                "text": text[:200_000],
                "truncated": byte_truncated or len(text) > 200_000,
                "headers": {key: response.headers.get(key) for key in
                            ("content-type", "content-length", "location", "last-modified", "etag")
                            if response.headers.get(key)},
            }
            if not saved:
                gate = _server_gate_hint(response.status_code, response.url, content_type,
                                         text or raw.decode(response.encoding or "utf-8", errors="replace"))
                if gate:
                    payload_out.update(gate)
            return json.dumps(payload_out, ensure_ascii=False)
    finally:
        session.close()


@mcp.tool(annotations=WRITE)
def download(url: str, path: str | None = None, headers: dict | None = None,
             timeout: int = 300, max_bytes: int = 536_870_912, allow_private: bool = False) -> str:
    """Download a URL to disk (data/downloads by default) and return path, bytes and sha256."""
    target = _url(url, allow_private)
    timeout = max(1, min(int(timeout), 1800))
    max_bytes = max(1024, min(int(max_bytes), 2_000_000_000))
    destination = _target(path, _fallback_name(target))
    digest = hashlib.sha256()
    total = 0
    request_headers = _build_headers(headers)
    session = requests.Session()
    session.trust_env = True
    session.hooks['response'].append(_redirect_guard(allow_private))
    temporary = None
    try:
        with session.get(target, headers=request_headers, timeout=(min(15, timeout), timeout), stream=True) as response:
            response.raise_for_status()
            with tempfile.NamedTemporaryFile(mode="wb",dir=destination.parent,prefix="."+destination.name+".",suffix=".part",delete=False) as output:
                temporary=Path(output.name)
                for chunk in response.iter_content(1024 * 1024):
                    if not chunk:
                        continue
                    total += len(chunk)
                    if total > max_bytes:
                        raise ValueError(f"Download exceeded {max_bytes} bytes and was cancelled.")
                    digest.update(chunk)
                    output.write(chunk)
                output.flush()
                os.fsync(output.fileno())
            os.replace(temporary,destination)
            temporary=None
        return json.dumps({"ok": True, "path": str(destination), "bytes": total,
                           "sha256": digest.hexdigest(), "content_type": response.headers.get("Content-Type", "")},
                          ensure_ascii=False)
    except Exception:
        try:
            if temporary is not None:temporary.unlink(missing_ok=True)
        except OSError:
            pass
        raise
    finally:
        session.close()


if __name__ == "__main__":
    mcp.run()
