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
        raise ValueError("URL http/https requerida.")
    if parsed.username or parsed.password:
        raise ValueError("No se admiten credenciales dentro de la URL.")
    if not allow_private:
        import ipaddress
        import socket
        try:
            addresses = socket.getaddrinfo(parsed.hostname, parsed.port or (443 if parsed.scheme == "https" else 80))
        except OSError as error:
            raise ValueError("No se pudo resolver el host: " + str(error)) from None
        if not addresses or any(not ipaddress.ip_address(item[4][0]).is_global for item in addresses):
            raise ValueError("Solo URLs públicas; usa allow_private=true para localhost/LAN.")
    return parsed.geturl()


def _redirect_guard(allow_private):
    def check(response,*args,**kwargs):
        location=response.headers.get('Location')
        if location and response.is_redirect:_url(urljoin(response.url,location),allow_private)
        return response
    return check


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


def _decode_text(raw: bytes, content_type: str, encoding: str | None) -> str:
    text = raw.decode(encoding or "utf-8", errors="replace")
    if "html" not in content_type:
        return text
    extracted = trafilatura.extract(raw, output_format="markdown", include_links=True, include_tables=True)
    if extracted:
        return extracted
    soup = BeautifulSoup(text, "html.parser")
    for tag in soup(["script", "style", "nav", "footer"]):
        tag.decompose()
    return soup.get_text("\n", strip=True)


@mcp.tool(annotations=WRITE)
def http_request(url: str, method: str = "GET", headers: dict | None = None,
                 body: str | None = None, body_base64: str | None = None,
                 cookies: dict | None = None, timeout: int = 60,
                 max_bytes: int = 10_000_000, allow_redirects: bool = True,
                 allow_private: bool = False, format: str = "auto",
                 save_path: str | None = None, download_dir: str | None = None) -> str:
    """Send a real HTTP request. Returns status, headers, type, size and text/markdown, or a saved file path. format=auto|text|markdown|json|base64."""
    method = str(method or "GET").upper()
    if method not in METHODS:
        raise ValueError("Método HTTP no admitido.")
    timeout = max(1, min(int(timeout), 300))
    max_bytes = max(1024, min(int(max_bytes), 100_000_000))
    payload: bytes | None
    if body_base64:
        payload = base64.b64decode(body_base64, validate=True)
    elif body is not None:
        payload = str(body).encode("utf-8")
    else:
        payload = None
    request_headers = {"User-Agent": UA, "Accept": "*/*"}
    if isinstance(headers, dict):
        for key, value in headers.items():
            if isinstance(key, str) and isinstance(value, str) and not any(c in key for c in "\r\n"):
                request_headers[key] = value
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
            for chunk in response.iter_content(65536):
                chunks.extend(chunk)
                if len(chunks) > max_bytes:
                    raise ValueError(f"Respuesta mayor de {max_bytes} bytes; usa download o aumenta max_bytes.")
            raw = bytes(chunks)
            saved = None
            if save_path or (format == "auto" and not (
                    content_type.startswith("text/") or "json" in content_type
                    or "xml" in content_type or "javascript" in content_type)):
                name = Path(urlparse(response.url).path).name or "response.bin"
                destination = _target(save_path, name, download_dir)
                destination.write_bytes(raw)
                saved = str(destination)
            text = ""
            if not saved:
                if format == "base64":
                    text = base64.b64encode(raw).decode("ascii")
                elif "json" in content_type and format in ("auto", "json"):
                    text = raw.decode(response.encoding or "utf-8", errors="replace")
                elif content_type.startswith("text/") or "xml" in content_type or "javascript" in content_type:
                    text = _decode_text(raw, content_type, response.encoding) if format in ("auto", "markdown") else raw.decode(response.encoding or "utf-8", errors="replace")
            return json.dumps({
                "ok": 200 <= response.status_code < 400,
                "status": response.status_code,
                "url": response.url,
                "content_type": content_type,
                "bytes": len(raw),
                "saved_path": saved,
                "sha256": hashlib.sha256(raw).hexdigest() if saved else None,
                "text": text[:200_000],
                "truncated": len(text) > 200_000,
                "headers": {key: response.headers.get(key) for key in
                            ("content-type", "content-length", "location", "last-modified", "etag")
                            if response.headers.get(key)},
            }, ensure_ascii=False)
    finally:
        session.close()


@mcp.tool(annotations=WRITE)
def download(url: str, path: str | None = None, timeout: int = 300,
             max_bytes: int = 536_870_912, allow_private: bool = False) -> str:
    """Download a URL to disk (data/downloads by default) and return path, bytes and sha256."""
    target = _url(url, allow_private)
    timeout = max(1, min(int(timeout), 1800))
    max_bytes = max(1024, min(int(max_bytes), 2_000_000_000))
    destination = _target(path, Path(urlparse(target).path).name or "download.bin")
    digest = hashlib.sha256()
    total = 0
    session = requests.Session()
    session.trust_env = True
    session.hooks['response'].append(_redirect_guard(allow_private))
    temporary = None
    try:
        with session.get(target, headers={"User-Agent": UA}, timeout=(min(15, timeout), timeout), stream=True) as response:
            response.raise_for_status()
            with tempfile.NamedTemporaryFile(mode="wb",dir=destination.parent,prefix="."+destination.name+".",suffix=".part",delete=False) as output:
                temporary=Path(output.name)
                for chunk in response.iter_content(1024 * 1024):
                    if not chunk:
                        continue
                    total += len(chunk)
                    if total > max_bytes:
                        raise ValueError(f"Descarga mayor de {max_bytes} bytes; se canceló.")
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
