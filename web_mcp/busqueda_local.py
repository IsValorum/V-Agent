"""Local DuckDuckGo policy for Open WebUI 0.11.4 (text only)."""
import asyncio
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor, as_completed
import json
import os
import re
import threading
import time
import unicodedata
import urllib.request
from urllib.parse import urlparse

_CACHE_LOCK = threading.Lock()
_SEARCH_CACHE = OrderedDict()  # key -> (expires_at, results)
_BACKEND_COOLDOWN = {}         # backend -> monotonic_until
_CACHE_TTL_S = 90.0
_COOLDOWN_S = 120.0

STOPWORDS = set('a al algo ante con como cual cuando de del desde donde el ella en entre es esta este esto la las lo los mas para por que se sin sobre su sus un una unos unas y o the a an of for in on to and or is'.split())
LOCAL_DOMAINS = {'elsalvador.com', 'laprensagrafica.com', 'diarioelsalvador.com', 'elsalvadorinfo.net', 'contrapunto.com.sv'}

def normalize(value):
    value = unicodedata.normalize('NFKD', str(value or '').lower())
    return ''.join(c for c in value if not unicodedata.combining(c))

def keywords(query):
    return set(re.findall(r'\w+', normalize(query))) - STOPWORDS

def score_result(query, result):
    title = normalize(result.get('title'))
    body = normalize(result.get('body') or result.get('snippet'))
    terms = keywords(query)
    title_terms, body_terms = keywords(title), keywords(body)
    hits = terms & (title_terms | body_terms)
    phrase = normalize(query).strip()
    score = (15 if phrase and phrase in title else 10 if phrase and phrase in body else 0)
    score += sum(17 if term in title_terms else 12 for term in hits)
    if terms and not hits:
        return -20
    host = (urlparse(result.get('href') or result.get('url') or '').hostname or '').lower()
    if host.endswith('.sv') or any(host == d or host.endswith('.' + d) for d in LOCAL_DOMAINS):
        score += 4
    if re.search(r'\bel salvador\b|\bsalvadoren[oa]s?\b', title + ' ' + body):
        score += 3
    return score

def rank_results(query, results, count=5):
    ranked, seen = [], set()
    for index, result in enumerate(results):
        link = result.get('href') or result.get('url') or result.get('image')
        if not link or link in seen:
            continue
        seen.add(link)
        score = score_result(query, result)
        if score >= 0:
            ranked.append((score, index, result))
    return [r for _, _, r in sorted(ranked, key=lambda item: (-item[0], item[1]))[:count]]

def short_snippet(text):
    words = str(text or '').split()
    lines, current = [], ''
    for word in words:
        if current and len(current) + len(word) + 1 > 160:
            lines.append(current)
            current = ''
            if len(lines) == 2:
                break
        current = (current + ' ' + word).strip()
    if len(lines) < 2 and current:
        lines.append(current)
    return '\n'.join(lines)[:321]

def _is_no_results_error(error):
    name = type(error).__name__.lower()
    if 'timeout' in name or 'ratelimit' in name:
        return False
    msg = str(error or '').strip().lower().rstrip('.!')
    return msg in ('no results found', 'no results') or (
        'no results found' in msg and not any(
            token in msg for token in (
                'timeout', 'timed out', 'rate', '403', '429',
                '500', '502', '503', 'connect', 'ssl', 'proxy', 'dns', 'network',
            )
        )
    )


def search(query, count=5, region=None, timelimit=None, filter_list=None, threads=1, strict_errors=False, safesearch='moderate', timeout=10, filter_ads=True):
    from ddgs import DDGS
    if not query or not query.strip():
        return []
    if timelimit not in (None, '', 'd', 'w', 'm', 'y'):
        timelimit = None
    count = max(1, min(int(count or 5), 10))
    # Request a little extra to compensate for filtered advertisements and
    # incomplete entries, without fetching several pages for five results.
    candidates = min(15, count + 3)
    proxies = urllib.request.getproxies()
    proxy = proxies.get('https') or proxies.get('http')

    target_region = region or os.getenv('WEB_SEARCH_REGION', 'wt-wt')
    # Normalizar regiones habituales
    if target_region in ('us-en', 'en-us'):
        target_region = 'us-en'
    elif target_region in ('sv-es', 'es-sv'):
        target_region = 'sv-es'

    raw = []
    # Real ddgs network calls benefit from short caching, cooldown of failing backends,
    # parallel primary racing (duckduckgo + yahoo), and multi-threaded auto fallback.
    is_real_ddgs = getattr(DDGS, '__module__', '').startswith('ddgs')
    cache_key = (query.strip().lower(), count, target_region, timelimit or '', safesearch, bool(filter_ads))
    if is_real_ddgs and not filter_list:
        now = time.monotonic()
        with _CACHE_LOCK:
            cached = _SEARCH_CACHE.get(cache_key)
            if cached and cached[0] > now:
                _SEARCH_CACHE.move_to_end(cache_key)
                return [dict(item) for item in cached[1]]
            elif cached:
                _SEARCH_CACHE.pop(cache_key, None)

    now = time.monotonic()
    fast_engines = ('duckduckgo', 'yahoo', 'yandex')
    if is_real_ddgs:
        active_fast = [b for b in fast_engines if _BACKEND_COOLDOWN.get(b, 0) <= now]
        if not active_fast:
            active_fast = ['yahoo', 'yandex']
        attempts = [(b, target_region) for b in active_fast] + [('auto', target_region)]
    else:
        attempts = [
            ('duckduckgo', target_region),
            ('yahoo', target_region),
            ('auto', target_region),
        ]

    failures = []
    completed = False
    def usable(rows):
        seen=set();out=[]
        for result in rows or []:
            if not isinstance(result,dict):continue
            link=result.get('href') or result.get('url') or ''
            parsed=urlparse(link)
            if not result.get('title') or parsed.scheme not in ('http','https') or not parsed.hostname or link in seen:continue
            if filter_ads and (result.get('is_ad') or result.get('sponsored') or result.get('is_sponsored') or
                parsed.hostname.lower() in ('ad.doubleclick.net','googleadservices.com','www.googleadservices.com')):continue
            seen.add(link);out.append(result)
        return out

    def _call_one(search_query, backend_choice, reg, per_timeout, worker_threads, max_res=None):
        with DDGS(proxy=proxy, timeout=per_timeout) as client:
            client.threads = worker_threads
            kwargs = {
                'safesearch': safesearch,
                'timelimit': timelimit or None,
                'max_results': max_res if max_res is not None else candidates
            }
            if backend_choice:
                kwargs['backend'] = backend_choice
            if reg:
                kwargs['region'] = reg
            return usable(client.text(search_query, **kwargs))

    def run_attempts(search_query, pairs):
        nonlocal raw, completed
        # On real ddgs, race the active fast single-engine backends concurrently
        # so the first responder with usable results wins immediately.
        if is_real_ddgs:
            race_pairs = [p for p in pairs if p[0] in fast_engines]
            rest_pairs = [p for p in pairs if p[0] not in fast_engines]
            if len(race_pairs) >= 2:
                fast_timeout = min(timeout, 5)
                pool = ThreadPoolExecutor(max_workers=len(race_pairs))
                futures = {pool.submit(_call_one, search_query, b, r, fast_timeout, 1): (b, r) for b, r in race_pairs}
                winner = None
                try:
                    for fut in as_completed(futures):
                        b, _r = futures[fut]
                        try:
                            rows = fut.result()
                            completed = True
                            if rows:
                                winner = (b, rows)
                                break
                            with _CACHE_LOCK:
                                _BACKEND_COOLDOWN[b] = time.monotonic() + _COOLDOWN_S
                        except Exception as error:
                            if _is_no_results_error(error):
                                completed = True
                                with _CACHE_LOCK:
                                    _BACKEND_COOLDOWN[b] = time.monotonic() + _COOLDOWN_S
                                continue
                            failures.append(f'{b or "auto"}: {type(error).__name__}: {str(error)[:180]}')
                            with _CACHE_LOCK:
                                _BACKEND_COOLDOWN[b] = time.monotonic() + _COOLDOWN_S
                finally:
                    pool.shutdown(wait=False, cancel_futures=True)
                if winner is not None:
                    raw = winner[1]
                    return True
                pairs = rest_pairs

        for backend_choice, reg in pairs:
            try:
                per_timeout = min(timeout, 5) if (is_real_ddgs and backend_choice in fast_engines) else timeout
                worker_threads = (6 if backend_choice == 'auto' else 1) if is_real_ddgs else (threads or 1)
                max_res = count if (is_real_ddgs and backend_choice == 'auto') else candidates
                raw = _call_one(search_query, backend_choice, reg, per_timeout, worker_threads, max_res=max_res)
                completed = True
                if raw:
                    return True
                if is_real_ddgs and backend_choice in fast_engines:
                    with _CACHE_LOCK:
                        _BACKEND_COOLDOWN[backend_choice] = time.monotonic() + _COOLDOWN_S
            except Exception as error:
                if _is_no_results_error(error):
                    completed = True
                    if is_real_ddgs and backend_choice in fast_engines:
                        with _CACHE_LOCK:
                            _BACKEND_COOLDOWN[backend_choice] = time.monotonic() + _COOLDOWN_S
                    continue
                failures.append(f'{backend_choice or "auto"}: {type(error).__name__}: {str(error)[:180]}')
                if is_real_ddgs and backend_choice in fast_engines:
                    with _CACHE_LOCK:
                        _BACKEND_COOLDOWN[backend_choice] = time.monotonic() + _COOLDOWN_S
        return False

    run_attempts(query, attempts)
    if not raw and completed:
        relaxed = ' '.join(re.sub(r'["“”]+', ' ', query).split())
        if relaxed and relaxed != query.strip():
            run_attempts(relaxed, attempts)
        else:
            relaxed = query.strip()
        if not raw and target_region and target_region != 'wt-wt':
            run_attempts(relaxed or query, [('yahoo', 'wt-wt'), ('yandex', 'wt-wt'), ('auto', 'wt-wt')] if is_real_ddgs else [('auto', 'wt-wt')])

    if strict_errors and not completed:
        summary = '; '.join(list(dict.fromkeys(failures))[:3])
        raise RuntimeError(f'Server-side search backends did not respond ({summary}). Use another enabled web/browser tool or suggest the user search directly in the browser.')

    if filter_list and raw:
        try:
            from open_webui.retrieval.web.main import get_filtered_results
            raw = get_filtered_results(raw, filter_list)
        except Exception:
            pass

    # Preserve search-engine ordering. No country-specific boosts.
    selected = raw[:count] if raw else []

    out = [{'title': r.get('title', ''), 'link': r.get('href') or r.get('url') or '',
            'snippet': short_snippet(r.get('body') or r.get('snippet') or '')} for r in selected]
    if is_real_ddgs and out and not filter_list:
        with _CACHE_LOCK:
            _SEARCH_CACHE[cache_key] = (time.monotonic() + _CACHE_TTL_S, [dict(item) for item in out])
            _SEARCH_CACHE.move_to_end(cache_key)
            while len(_SEARCH_CACHE) > 64:
                _SEARCH_CACHE.popitem(last=False)
    return out

def relevant_sections(text, find_in_page):
    if not find_in_page:
        return text
    terms = keywords(find_in_page)
    phrase = normalize(find_in_page).strip()
    paragraphs = re.split(r'\n\s*\n', text)
    selected = set()
    for i, paragraph in enumerate(paragraphs):
        normalized = normalize(paragraph)
        if (phrase and phrase in normalized) or terms & keywords(paragraph):
            selected.update(range(max(0, i - 1), min(len(paragraphs), i + 2)))
    if not selected:
        return '[No matches found for find_in_page.]\n\n' + text
    # Relevant paragraphs and their neighbors precede the rest, before truncation.
    return '\n\n'.join([paragraphs[i] for i in sorted(selected)] +
                       [p for i, p in enumerate(paragraphs) if i not in selected])

_context_cache = (0, None)

def serving_context():
    global _context_cache
    if time.monotonic() - _context_cache[0] < 30 and _context_cache[1]:
        return _context_cache[1]
    try:
        with urllib.request.urlopen('http://127.0.0.1:8080/props', timeout=2) as response:
            props = json.load(response)
        settings = props.get('default_generation_settings', {})
        ctx = int(settings.get('n_ctx') or props.get('n_ctx') or 0)
        if ctx > 0:
            _context_cache = (time.monotonic(), ctx)
            return ctx
    except Exception:
        pass
    return None

def page_limit(context_tokens=None):
    # Four chars/token is an estimate, not an exact tokenizer budget.
    caps = [60000, int(os.getenv('WEB_FETCH_MAX_CONTENT_LENGTH', '60000')),
            int(os.getenv('WEB_TOOL_RESULT_MAX_CHARS', '60000'))]
    if context_tokens and int(context_tokens) > 0:
        caps.append(int(int(context_tokens) * 4 * 0.50))
    return max(1, min(caps))

def trim_page(text, find_in_page=None, context_tokens=None):
    text = relevant_sections(str(text or ''), find_in_page)
    cap = page_limit(context_tokens)
    notice = '\n\n[Contenido recortado por el limite de lectura/contexto.]'
    return text if len(text) <= cap else text[:max(0, cap-len(notice))] + notice[:cap]

async def read_page(request, url, find_in_page=None, metadata=None):
    # Keep Open WebUI's existing URL validation, loader and network policy.
    from open_webui.retrieval.utils import get_content_from_url
    content, _ = await get_content_from_url(request, url)
    ctx = await asyncio.to_thread(serving_context)
    if ctx is None:
        metadata = metadata or {}
        ctx = (metadata.get('params') or {}).get('num_ctx')
    return trim_page(content, find_in_page, ctx)
