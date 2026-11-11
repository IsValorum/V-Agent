"""DuckDuckGo text search and public page reading for llama.cpp's native UI."""
import ipaddress
import json
import socket
import re
import hashlib
import threading
from collections import OrderedDict
from urllib.parse import urljoin, urlparse

import requests
import trafilatura
from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations
from mcp_options import options
from busqueda_local import search, relevant_sections

mcp = FastMCP('DuckDuckGo')
read_only = ToolAnnotations(readOnlyHint=True, destructiveHint=False, openWorldHint=True)

# Immutable page snapshots keep continuation offsets stable if the site changes.
PAGE_PART_CHARS = 6000
MAX_PAGE_BYTES = 8 * 1024 * 1024
_pages = OrderedDict()
_pages_lock = threading.Lock()

def validate_public_url(url):
    parsed = urlparse(url)
    if parsed.scheme not in ('http', 'https') or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError('Se requiere una URL publica http/https sin credenciales.')
    addresses = socket.getaddrinfo(parsed.hostname, parsed.port or (443 if parsed.scheme == 'https' else 80))
    if not addresses or any(not ipaddress.ip_address(a[4][0]).is_global for a in addresses):
        raise ValueError('Solo se admiten paginas de internet publicas.')

BROWSER_HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
    'Accept-Language': 'es-ES,es;q=0.9,en;q=0.8',
    'Sec-Fetch-Dest': 'document',
    'Sec-Fetch-Mode': 'navigate',
    'Sec-Fetch-Site': 'none',
}

def hf_public_profile(url):
    """Public profile counts, never CLI authentication or local credentials."""
    parsed = urlparse(url)
    handle = parsed.path.strip('/')
    if parsed.netloc.lower() != 'huggingface.co' or parsed.scheme != 'https' or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,95}', handle):
        return ''
    endpoint = f'https://huggingface.co/api/users/{handle}/overview'
    try:
        with requests.Session() as public:
            public.trust_env = False
            with public.get(endpoint, timeout=(4, 6), stream=True, allow_redirects=False) as response:
                if response.status_code != 200:
                    return ''
                raw = response.raw.read(65537, decode_content=True)
            if len(raw) > 65536:
                return ''
            data = json.loads(raw)
        if not isinstance(data, dict) or str(data.get('user', '')).casefold() != handle.casefold():
            return ''
        fields = {'numFollowers': 'seguidores', 'numFollowing': 'usuarios seguidos',
                  'numFollowingOrgs': 'organizaciones seguidas', 'numModels': 'modelos',
                  'numDatasets': 'datasets', 'numSpaces': 'Spaces'}
        counts = [f'{label}: {data[key]}' for key, label in fields.items()
                  if type(data.get(key)) is int and data[key] >= 0]
        return f"Perfil público: {data['user']}\n" + '; '.join(counts) + f'\nFuente: {endpoint}' if counts else ''
    except (requests.RequestException, OSError, ValueError):
        return ''


def read_public_page(url, find_in_page=None):
    with requests.Session() as session:
        settings=options('duckduckgo')
        session.headers.update(BROWSER_HEADERS)
        language=settings['language']
        if language!='auto': session.headers['Accept-Language']=language
        else: session.headers.pop('Accept-Language',None)
        current = url
        for _ in range(10):
            validate_public_url(current)
            with session.get(current, timeout=(settings['timeout'], settings['timeout']), stream=True, allow_redirects=False) as response:
                if response.is_redirect:
                    current = urljoin(current, response.headers['Location'])
                    continue
                response.raise_for_status()
                content_type = response.headers.get('Content-Type', '').lower()
                if not any(t in content_type for t in ('text/', 'html', 'xml', 'json')):
                    raise ValueError('Solo se leen paginas de texto/HTML; no binarios ni PDF.')

                chunks = []
                received = 0
                for chunk in response.iter_content(65536):
                    received += len(chunk)
                    if received > MAX_PAGE_BYTES:
                        raise ValueError('Page exceeds the 8 MiB reading limit.')
                    chunks.append(chunk)

                raw = b''.join(chunks)
                if 'html' in content_type:
                    text = trafilatura.extract(raw, url=url, output_format='markdown',
                                               include_links=settings['include_links'], include_tables=settings['include_tables'])
                    if not text:
                        from bs4 import BeautifulSoup
                        page = BeautifulSoup(raw, 'html.parser')
                        for tag in page(['script', 'style', 'nav', 'footer']):
                            tag.decompose()
                        text = page.get_text('\n', strip=True)
                else:
                    text = raw.decode(response.encoding or 'utf-8', errors='replace')

                focused = relevant_sections(str(text or ''), find_in_page)
                profile = hf_public_profile(current)
                if profile:
                    return profile if not find_in_page else profile + '\n\nTexto de la página (no son totales del perfil):\n' + focused
                return focused
        raise ValueError('Demasiadas redirecciones.')

@mcp.tool(annotations=read_only)
def web_search(query: str | None = None, url: str | None = None,
               region: str | None = None, timelimit: str | None = None,
               find_in_page: str | None = None, offset: int = 0,
               page_id: str | None = None) -> str:
    """Search titles, links and snippets. Defaults are user-configured. region: wt-wt (global), us-en, es-es...
    timelimit: d/w/m/y. Use web_visit to read URLs.
    """
    if url:
        return web_visit(url, find_in_page, offset, page_id)
    if not isinstance(query, str) or not query.strip():
        raise ValueError('query debe contener una busqueda.')
    if timelimit not in (None, '', 'd', 'w', 'm', 'y'):
        raise ValueError('timelimit: d, w, m, y u omitir.')
    settings=options('duckduckgo')
    target_region=region or settings['region']
    # DDGS uses a combined country-language locale. A chosen language selects
    # its supported locale when the selected country has another language.
    language=settings['language']
    if not region and language!='auto' and target_region.rsplit('-',1)[-1]!=language:
        target_region={'en':'us-en','es':'es-es','pt':'br-pt','fr':'fr-fr','de':'de-de','ja':'jp-jp'}[language]
    results = search(query, count=settings['count'], region=target_region,
                     timelimit=timelimit if timelimit is not None else settings['timelimit'],
                     strict_errors=True,safesearch=settings['safesearch'],
                     timeout=settings['timeout'],filter_ads=settings['filter_ads'])
    # Never turn an error/no results into a fictitious search hit.
    results = [r for r in results if r.get('title') and urlparse(r.get('link', '')).scheme in ('http', 'https')
               and urlparse(r.get('link', '')).hostname]
    return json.dumps(results, ensure_ascii=False, separators=(',', ':'))

@mcp.tool(annotations=read_only)
def web_visit(url: str, find_in_page: str | None = None, offset: int = 0,
              page_id: str | None = None) -> str:
    """Read a public URL. Returns content, page_id, next_offset and has_more.
    Continue only as needed: same url/page_id, offset=next_offset. find_in_page focuses keywords.
    """
    if offset < 0:
        raise ValueError('offset debe ser mayor o igual que cero.')
    if page_id:
        with _pages_lock:
            snapshot = _pages.get(page_id)
            if snapshot is not None:
                _pages.move_to_end(page_id)
        if snapshot is None:
            raise ValueError('page_id no disponible. Reinicia con offset=0 y sin page_id.')
        saved_url, saved_focus, text = snapshot
        if saved_url != url or (find_in_page is not None and find_in_page != saved_focus):
            raise ValueError('page_id pertenece a otra URL o find_in_page. Reinicia sin page_id.')
    else:
        text = read_public_page(url, find_in_page)
        if not text.strip():
            raise ValueError('La pagina no devolvio texto legible.')
        page_id = hashlib.sha256(json.dumps([url, find_in_page, text],
                                           ensure_ascii=False).encode('utf-8')).hexdigest()
        with _pages_lock:
            _pages[page_id] = (url, find_in_page, text)
            _pages.move_to_end(page_id)
            while len(_pages) > 8:
                _pages.popitem(last=False)
    if offset > len(text):
        raise ValueError(f'offset supera el largo de la pagina: {len(text)} caracteres.')
    # Keep the complete JSON (including continuation metadata) below the agent's
    # 12000-character model-result budget, even with heavily escaped text.
    end = min(offset + options('duckduckgo')['visit_tokens'] * 4, len(text))
    while True:
        result = json.dumps({
            'url': url, 'page_id': page_id, 'offset': offset,
            'next_offset': end if end < len(text) else None,
            'has_more': end < len(text), 'total_characters': len(text), 'token_budget_approximate': True,
            'content': text[offset:end],
        }, ensure_ascii=False, separators=(',', ':'))
        if len(result) <= min(11500,options('duckduckgo')['max_result_chars']):
            return result
        if end <= offset:
            raise ValueError('URL demasiado larga para devolver una parte legible.')
        end = offset + (end - offset) // 2

if __name__ == '__main__':
    mcp.run(transport='stdio')
