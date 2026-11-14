"""DuckDuckGo text search and public page reading for llama.cpp's native UI."""
import ipaddress
import json
import socket
import re
import hashlib
import pathlib
import sys
import threading
from collections import OrderedDict
from urllib.parse import urljoin, urlparse

_AGENT_DIR = pathlib.Path(__file__).resolve().parent.parent / 'agent'
if str(_AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(_AGENT_DIR))

import requests
import trafilatura
from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations
from mcp_options import options
from doc_extractor import SUPPORTED_EXTENSIONS as _DOC_EXTS, extract_bytes as _extract_doc_bytes, infer_extension as _infer_doc_ext
from busqueda_local import search, relevant_sections

mcp = FastMCP('DuckDuckGo')
read_only = ToolAnnotations(readOnlyHint=True, destructiveHint=False, openWorldHint=True)

# Immutable page snapshots keep continuation offsets stable if the site changes.
PAGE_PART_CHARS = 6000
MAX_PAGE_BYTES = 8 * 1024 * 1024
MAX_DOC_BYTES = 24 * 1024 * 1024
_pages = OrderedDict()
_pages_lock = threading.Lock()

def validate_public_url(url):
    parsed = urlparse(url)
    if parsed.scheme not in ('http', 'https') or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError('A public http/https URL without credentials is required.')
    addresses = socket.getaddrinfo(parsed.hostname, parsed.port or (443 if parsed.scheme == 'https' else 80))
    if not addresses or any(not ipaddress.ip_address(a[4][0]).is_global for a in addresses):
        raise ValueError('Only public internet pages are allowed.')

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
        fields = {'numFollowers': 'followers', 'numFollowing': 'following',
                  'numFollowingOrgs': 'following orgs', 'numModels': 'models',
                  'numDatasets': 'datasets', 'numSpaces': 'Spaces'}
        counts = [f'{label}: {data[key]}' for key, label in fields.items()
                  if type(data.get(key)) is int and data[key] >= 0]
        return f"Public profile: {data['user']}\n" + '; '.join(counts) + f'\nSource: {endpoint}' if counts else ''
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
                url_path = urlparse(current).path
                doc_ext = _infer_doc_ext(url_path, content_type)
                is_binary_doc = doc_ext in ('.pdf', '.docx', '.xlsx', '.xlsm', '.pptx', '.odt', '.ods', '.odp', '.epub', '.rtf')
                is_text_like = not content_type or any(t in content_type for t in ('text/', 'html', 'xml', 'json', 'javascript'))
                if not is_binary_doc and not is_text_like and doc_ext not in _DOC_EXTS:
                    raise ValueError('Only text/HTML pages or supported documents (PDF, DOCX, XLSX, PPTX, ODF, EPUB, RTF) can be read.')

                max_bytes = MAX_DOC_BYTES if is_binary_doc else MAX_PAGE_BYTES
                chunks = []
                received = 0
                for chunk in response.iter_content(65536):
                    received += len(chunk)
                    if received > max_bytes:
                        limit_mib = max_bytes // (1024 * 1024)
                        raise ValueError(f'Page exceeds the {limit_mib} MiB reading limit.')
                    chunks.append(chunk)

                raw = b''.join(chunks)
                if not is_binary_doc and not content_type:
                    sample = raw[:4096]
                    if any(b < 9 or (13 < b < 32) for b in sample):
                        raise ValueError('Only text/HTML pages or supported documents (PDF, DOCX, XLSX, PPTX, ODF, EPUB, RTF) can be read.')
                looks_html = 'html' in content_type or raw.lstrip()[:64].lower().startswith((b'<!doctype html', b'<html'))
                if is_binary_doc:
                    extracted = _extract_doc_bytes(raw, url_path, content_type)
                    text = extracted.get('text', '')
                elif looks_html:
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
                    return profile if not find_in_page else profile + '\n\nPage text (not profile totals):\n' + focused
                return focused
        raise ValueError('Too many redirects.')

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
        raise ValueError('query must contain a search string.')
    if timelimit not in (None, '', 'd', 'w', 'm', 'y'):
        raise ValueError('timelimit must be d, w, m, y, or omitted.')
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
        raise ValueError('offset must be >= 0.')
    if page_id:
        with _pages_lock:
            snapshot = _pages.get(page_id)
            if snapshot is not None:
                _pages.move_to_end(page_id)
        if snapshot is None:
            raise ValueError('page_id is unavailable or expired. Restart with offset=0 and without page_id.')
        saved_url, saved_focus, text = snapshot
        if saved_url != url or (find_in_page is not None and find_in_page != saved_focus):
            raise ValueError('page_id belongs to another URL or find_in_page filter. Restart without page_id.')
    else:
        text = read_public_page(url, find_in_page)
        if not text.strip():
            raise ValueError('The page returned no readable text.')
        page_id = hashlib.sha256(json.dumps([url, find_in_page, text],
                                           ensure_ascii=False).encode('utf-8')).hexdigest()
        with _pages_lock:
            _pages[page_id] = (url, find_in_page, text)
            _pages.move_to_end(page_id)
            while len(_pages) > 8:
                _pages.popitem(last=False)
    if offset > len(text):
        raise ValueError(f'offset exceeds page length: {len(text)} characters.')
    visit_cfg = options('duckduckgo')
    visit_tokens = int(visit_cfg['visit_tokens'])
    max_result_chars = int(visit_cfg['max_result_chars'])
    end = len(text) if visit_tokens <= 0 else min(offset + visit_tokens * 4, len(text))
    while True:
        result = json.dumps({
            'url': url, 'page_id': page_id, 'offset': offset,
            'next_offset': end if end < len(text) else None,
            'has_more': end < len(text), 'total_characters': len(text), 'token_budget_approximate': True,
            'content': text[offset:end],
        }, ensure_ascii=False, separators=(',', ':'))
        if max_result_chars <= 0 or len(result) <= max_result_chars:
            return result
        if end <= offset:
            raise ValueError('URL is too long to return a readable chunk.')
        end = offset + (end - offset) // 2

if __name__ == '__main__':
    mcp.run(transport='stdio')
