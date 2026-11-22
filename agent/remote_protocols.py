"""Translate provider wire formats at the transport boundary, never in the tool loop."""
import gzip
import json
import re
import zlib
from urllib.parse import urlsplit


def normalize_orphan_tool_messages(messages):
    """Turn synthetic role='tool' notes (no tool_call_id) into role='user' at provider/template boundaries."""
    if not isinstance(messages,list):
        return messages
    out=[]
    for item in messages:
        if isinstance(item,dict) and item.get('role')=='tool' and not item.get('tool_call_id'):
            out.append({'role':'user','content':_content_text(item.get('content'))})
        else:
            out.append(item)
    return out


def openai_payload(body,base_url,send_sampling=False):
    body=dict(body)
    for field in ('seed','frequency_penalty','presence_penalty'):body.pop(field,None)
    if not send_sampling:
        body.pop('temperature',None);body.pop('top_p',None)
    if isinstance(body.get('messages'),list):
        body['messages']=normalize_orphan_tool_messages(body['messages'])
    host=(urlsplit(base_url).hostname or '').lower()
    if host=='api.openai.com' and 'max_tokens' in body:body['max_completion_tokens']=body.pop('max_tokens')
    effort=body.pop('reasoning_effort',None)
    if effort and effort!='default':
        if 'deepseek' in host or 'deepseek' in str(body.get('model','')).lower():
            if effort=='none':body['thinking']={'type':'disabled'}
            else:
                body['thinking']={'type':'enabled'}
                body['reasoning_effort']='max' if effort=='xhigh' else 'low' if effort=='minimal' else effort
                if isinstance(body.get('messages'),list):
                    body['messages']=[{**m,'reasoning_content':m.get('reasoning_content') or ''} if isinstance(m,dict) and m.get('role')=='assistant' and m.get('tool_calls') and 'reasoning_content' not in m else m for m in body['messages']]
        elif effort!='none':
            body['reasoning_effort']='high' if effort=='xhigh' else 'low' if effort=='minimal' else effort
        elif host=='api.openai.com':
            body['reasoning_effort']='none'
    return body


def positive_int(value):
    try:
        if isinstance(value, bool):return None
        result=int(value)
        return result if 0<result<=100_000_000 else None
    except (TypeError,ValueError,OverflowError):return None


def model_info(item,overrides):
    identifier=str(item['id'])
    limits=item.get('limits') if isinstance(item.get('limits'),dict) else {};architecture=item.get('top_provider') if isinstance(item.get('top_provider'),dict) else {}
    context=next((n for n in (positive_int(item.get(k)) for k in ('context_length','context_window','max_input_tokens','max_model_len')) if n),None)
    context=context or positive_int(limits.get('context')) or positive_int(architecture.get('context_length'))
    manual=overrides.get(identifier,{})
    return {'id':identifier,'display_name':str(item.get('display_name') or item.get('name') or identifier),
            'context':positive_int(manual.get('context')) or context,
            'reported_context':context,'context_source':'manual' if positive_int(manual.get('context')) else 'provider' if context else 'unknown',
            'max_output_tokens':positive_int(item.get('max_tokens')) or positive_int(item.get('max_output_tokens')) or positive_int(item.get('max_completion_tokens')) or positive_int(architecture.get('max_completion_tokens')) or positive_int(limits.get('output')),
            'capabilities':item.get('capabilities') if isinstance(item.get('capabilities'),dict) else {}}


def claude_content(content):
    if isinstance(content,str):return [{'type':'text','text':content}] if content else []
    blocks=[]
    for part in content or []:
        if not isinstance(part,dict):continue
        if part.get('type')=='text' and part.get('text'):blocks.append({'type':'text','text':part['text']})
        elif part.get('type')=='image_url':
            url=part.get('image_url',{}).get('url','') if isinstance(part.get('image_url'),dict) else ''
            if not url:continue
            match=re.fullmatch(r'data:(image/(?:png|jpeg|gif|webp));base64,(.+)',url,re.S|re.I)
            blocks.append({'type':'image','source':({'type':'base64','media_type':match[1].lower(),'data':match[2]} if match else {'type':'url','url':url})})
    return blocks


def claude_payload(payload,version,output_limit=None):
    system=[];messages=[]
    # Anthropic refuses a tool_use id used twice in a conversation. A history made with a local engine can
    # repeat one (call_0 on every round): a repeated id gets a suffix, and its results follow it.
    seen=set();renamed={}
    for message in payload.get('messages',[]):
        role=message.get('role');content=claude_content(message.get('content'))
        if role in ('system','developer'):system.extend(content);continue
        if role=='tool':
            if not message.get('tool_call_id'):
                role='user'
            else:
                content=[{'type':'tool_result','tool_use_id':renamed.get(message['tool_call_id'],message['tool_call_id']),'content':content}];role='user'
        elif role=='assistant':
            renamed={}
            for call in message.get('tool_calls') or []:
                function=call.get('function') or {};args=function.get('arguments') or '{}'
                if isinstance(args,str):
                    try:args=json.loads(args)
                    except ValueError:args={}
                if not isinstance(args,dict):raise ValueError('Los argumentos de la herramienta deben ser un objeto JSON.')
                ident=original=str(call.get('id',''));n=1
                while ident in seen:n+=1;ident=original+'_'+str(n)
                seen.add(ident);renamed[original]=ident
                content.append({'type':'tool_use','id':ident,'name':function.get('name',''),'input':args})
        if not content:continue
        role='assistant' if role=='assistant' else 'user'
        if messages and messages[-1]['role']==role:messages[-1]['content'].extend(content)
        else:messages.append({'role':role,'content':content})
    limit=positive_int(payload.get('max_tokens')) or min(output_limit or 8192,8192)
    body={'model':payload['model'],'messages':messages,'max_tokens':min(limit,output_limit) if output_limit else limit,'stream':True}
    if system:body['system']=system
    if payload.get('tools'):
        body['tools']=[{'name':t['function']['name'],'description':t['function'].get('description',''),'input_schema':t['function'].get('parameters') or {'type':'object','properties':{}}} for t in payload['tools']]
        choice=payload.get('tool_choice','auto')
        if choice in ('auto','none','required'):body['tool_choice']={'type':{'required':'any'}.get(choice,choice)}
        elif isinstance(choice,dict):body['tool_choice']={'type':'tool','name':choice['function']['name']}
    # The current Claude API removed sampling parameters. Older gateways can opt in to the legacy version.
    if version<'2026-10-21' and 'temperature' in payload:body['temperature']=payload['temperature']
    return body


class ClaudeStream:
    def __init__(self):self.usage={};self.tools={}

    def packet(self,event):
        kind=event.get('type');delta={};finish=None
        if kind=='error':raise ValueError('Claude: '+str(event.get('error',{}).get('message') or 'Error de streaming'))
        if kind=='message_start':
            usage=event.get('message',{}).get('usage',{})
            self.usage={'prompt_tokens':sum(usage.get(k,0) or 0 for k in ('input_tokens','cache_creation_input_tokens','cache_read_input_tokens')),'completion_tokens':usage.get('output_tokens',0)}
        elif kind=='content_block_start':
            block=event.get('content_block',{});index=event['index']
            if block.get('type')=='tool_use':
                self.tools[index]=len(self.tools)
                delta={'tool_calls':[{'index':self.tools[index],'id':block['id'],'type':'function','function':{'name':block['name'],'arguments':json.dumps(block['input']) if block.get('input') else ''}}]}
            elif block.get('type')=='text':delta={'content':block.get('text','')}
        elif kind=='content_block_delta':
            part=event.get('delta',{});index=event['index']
            if part.get('type')=='text_delta':delta={'content':part.get('text','')}
            elif part.get('type')=='thinking_delta':delta={'reasoning_content':part.get('thinking','')}
            elif part.get('type')=='input_json_delta' and index in self.tools:delta={'tool_calls':[{'index':self.tools[index],'function':{'arguments':part.get('partial_json','')}}]}
        elif kind=='message_delta':
            if 'output_tokens' in event.get('usage',{}):self.usage['completion_tokens']=event['usage']['output_tokens']
            reason=event.get('delta',{}).get('stop_reason');finish={'tool_use':'tool_calls','max_tokens':'length'}.get(reason,'stop') if reason else None
        elif kind=='message_stop':return b'data: [DONE]\n\n'
        else:return None
        return ('data: '+json.dumps({'choices':[{'index':0,'delta':delta,'finish_reason':finish}],**({'usage':self.usage} if self.usage else {})},ensure_ascii=False)+'\n\n').encode()


COMPACT_INSTRUCTIONS = (
    'Compress the conversation history into a concise, self-contained technical handoff summary '
    'in the same language as the user. Preserve every concrete fact needed to continue without loss: '
    'user goals and constraints, decisions made, exact file paths, symbol names, commands run, '
    'verified tool outputs, remaining errors/blockers, and pending tasks. Omit filler or repetition.'
)


def _content_text(content):
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, dict):
                if item.get('type') in ('text', 'output_text', 'input_text') and item.get('text'):
                    parts.append(str(item['text']))
                elif item.get('type') == 'image_url':
                    parts.append('[imagen adjunta]')
        return '\n'.join(parts)
    return str(content or '')


def compact_transcript(messages, max_chars=240000):
    lines = []
    for item in messages or []:
        if not isinstance(item, dict):
            continue
        role = item.get('role') or 'user'
        text = _content_text(item.get('content')).strip()
        if role == 'assistant' and item.get('tool_calls'):
            calls = []
            for call in item.get('tool_calls') or []:
                fn = (call.get('function') or {})
                calls.append(f"{fn.get('name', 'tool')}({str(fn.get('arguments') or '')[:1200]})")
            block = '[Assistant tool calls]\n' + '\n'.join(calls)
            if text:
                block = f'[Assistant]\n{text}\n' + block
            lines.append(block)
        elif role == 'tool':
            lines.append(f"[Tool output ({item.get('tool_call_id', '')})]\n{text[:4000]}")
        elif text:
            lines.append(f'[{role.capitalize()}]\n{text}')
    joined = '\n\n'.join(lines)
    if len(joined) > max_chars:
        joined = joined[-max_chars:]
    return joined


def openai_responses_compact_payload(model_id, messages, instructions=None):
    items = []
    for item in messages or []:
        if not isinstance(item, dict):
            continue
        role = item.get('role')
        if role == 'tool':
            text = _content_text(item.get('content')).strip()
            if text:
                items.append({'role': 'developer', 'content': f"Tool output: {text[:8000]}"})
            continue
        if role == 'assistant' and item.get('tool_calls'):
            summary = _content_text(item.get('content')).strip()
            calls = []
            for call in item.get('tool_calls') or []:
                fn = (call.get('function') or {})
                calls.append(f"{fn.get('name', 'tool')}({str(fn.get('arguments') or '')[:1500]})")
            text = ((summary + '\n') if summary else '') + 'Called tools: ' + '; '.join(calls)
            items.append({'role': 'assistant', 'content': text})
            continue
        if role in ('user', 'assistant', 'system', 'developer'):
            text = _content_text(item.get('content')).strip()
            if text:
                items.append({'role': 'user' if role not in ('user', 'assistant', 'developer') else role, 'content': text})
    payload = {'model': model_id, 'input': items}
    if instructions or COMPACT_INSTRUCTIONS:
        payload['instructions'] = instructions or COMPACT_INSTRUCTIONS
    return payload


def extract_responses_compact_summary(data):
    if not isinstance(data, dict):
        return '', None, None
    output = data.get('output')
    texts = []
    compaction_item = None
    if isinstance(output, list):
        for item in output:
            if not isinstance(item, dict):
                continue
            itype = item.get('type')
            if itype == 'compaction':
                compaction_item = item
            elif itype == 'message':
                for part in item.get('content') or []:
                    if isinstance(part, dict) and part.get('text'):
                        texts.append(str(part['text']))
            elif item.get('text'):
                texts.append(str(item['text']))
    raw_usage = data.get('usage') if isinstance(data.get('usage'), dict) else None
    usage = None
    if raw_usage:
        inp = raw_usage.get('input_tokens', raw_usage.get('prompt_tokens'))
        out = raw_usage.get('output_tokens', raw_usage.get('completion_tokens'))
        if isinstance(inp, int) and isinstance(out, int):
            usage = {'prompt_tokens': inp, 'completion_tokens': out}
    return '\n\n'.join(t for t in texts if t.strip()), compaction_item, usage


DEFAULT_ANTHROPIC_VERSION = '2023-06-01'
DEFAULT_OPENROUTER_REFERER = 'https://github.com/IsValorum/V-Agent'
DEFAULT_OPENROUTER_TITLE = 'V-Agent'
PROVIDER_PRESETS = ('auto', 'openai', 'anthropic', 'openrouter', 'opencode', 'azure')
AUTH_MODES = ('auto', 'bearer', 'x-api-key', 'api-key', 'none')
_HEADER_NAME_RE = re.compile(r"^[!#$%&'*+\-.^_`|~0-9A-Za-z]+$")


def default_user_agent(version='1.1.1'):
    clean = re.sub(r'[^0-9A-Za-z._+-]', '', str(version or '1.1.1')).strip() or '1.1.1'
    return f'V-Agent/{clean}'


def infer_provider_preset(protocol, base_url='', preset='auto'):
    chosen = str(preset or 'auto').strip().lower()
    if chosen in PROVIDER_PRESETS and chosen != 'auto':
        return chosen
    host = (urlsplit(str(base_url or '')).hostname or '').lower()
    path = (urlsplit(str(base_url or '')).path or '').lower()
    if 'openrouter.ai' in host:
        return 'openrouter'
    if 'opencode' in host or '/zen/' in path:
        return 'opencode'
    if host.endswith('.openai.azure.com') or '.services.ai.azure.com' in host or '/openai/deployments/' in path:
        return 'azure'
    if protocol == 'anthropic' or 'anthropic.com' in host:
        return 'anthropic'
    return 'openai'


_OPENCODE_INFERENCE = re.compile(r'^(/inference(?:/go)?)/?$', re.I)


def opencode_inference_url(base_url, path, preset):
    """OpenCode's current endpoints (https://opencode.ai/inference and /inference/go) are per protocol:
    /openai/v1/chat/completions, /anthropic/v1/messages, and the model list at /v1/models. The older
    /zen/v1 and /zen/go/v1 bases keep the plain OpenAI layout, so they return None here."""
    if preset != 'opencode':
        return None
    parts = urlsplit(str(base_url or ''))
    match = _OPENCODE_INFERENCE.match(parts.path or '')
    if not match:
        return None
    root = parts.scheme + '://' + parts.netloc + match.group(1)
    if path.startswith('/models'):
        return root + '/v1' + path
    if path.startswith('/messages'):
        return root + '/anthropic/v1' + path
    return root + '/openai/v1' + path


def resolve_auth_mode(cfg, preset):
    explicit = str((cfg or {}).get('auth_mode') or 'auto').strip().lower()
    if explicit in AUTH_MODES and explicit != 'auto':
        return explicit
    protocol = str((cfg or {}).get('protocol') or 'openai').strip().lower()
    if preset == 'opencode':
        return 'bearer'   # OpenCode documents Authorization: Bearer for every protocol, Anthropic included
    if preset == 'anthropic' or (preset == 'auto' and protocol == 'anthropic'):
        return 'x-api-key'
    if preset == 'azure':
        return 'api-key'
    return 'bearer'


def _clean_header_value(value):
    text = str(value or '').strip()
    if '\r' in text or '\n' in text:
        raise ValueError('Cabecera HTTP no válida: contiene saltos de línea.')
    try:
        text.encode('latin-1')
    except UnicodeEncodeError:
        raise ValueError('Cabecera HTTP no válida: usa solo caracteres ASCII/Latin-1 en cabeceras HTTP.') from None
    return text


def extract_azure_deployment(base_url):
    """Extract classic Azure OpenAI deployment name from /openai/deployments/<name> if present."""
    match = re.search(r'/openai/deployments/([^/?#]+)', str(base_url or ''), re.I)
    return match.group(1) if match else ''


def decode_http_body(raw, content_encoding=''):
    """Decompress gzip/deflate HTTP responses if an upstream proxy ignored Accept-Encoding: identity."""
    enc = str(content_encoding or '').split(',')[0].strip().lower()
    if not raw or not enc or enc == 'identity':
        return raw
    if enc in ('gzip', 'x-gzip'):
        return gzip.decompress(raw)
    if enc == 'deflate':
        try:
            return zlib.decompress(raw)
        except zlib.error:
            return zlib.decompress(raw, -zlib.MAX_WBITS)
    return raw


def iter_http_lines(response):
    """Yield lines from an HTTP response, transparently decompressing gzip/deflate if a proxy forced it."""
    enc = str((response.getheader('Content-Encoding') if hasattr(response, 'getheader') else '') or '').split(',')[0].strip().lower()
    if enc not in ('gzip', 'x-gzip', 'deflate'):
        yield from response
        return
    wbits = (16 + zlib.MAX_WBITS) if enc in ('gzip', 'x-gzip') else zlib.MAX_WBITS
    dec = zlib.decompressobj(wbits)
    buf = b''
    while True:
        chunk = response.read(8192)
        if not chunk:
            break
        try:
            buf += dec.decompress(chunk)
        except zlib.error:
            if enc == 'deflate' and wbits == zlib.MAX_WBITS:
                dec = zlib.decompressobj(-zlib.MAX_WBITS)
                buf += dec.decompress(chunk)
            else:
                raise
        while b'\n' in buf:
            line, buf = buf.split(b'\n', 1)
            yield line + b'\n'
    tail = buf + dec.flush()
    if tail:
        yield tail


def parse_extra_headers(raw):
    """Normalize custom headers from a dict or 'Name: Value' lines, blocking CRLF & telemetry leaks."""
    if not raw:
        return {}
    items = []
    if isinstance(raw, dict):
        items = list(raw.items())
    elif isinstance(raw, str):
        for line in raw.splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith('#'):
                continue
            if ':' not in stripped:
                raise ValueError('Cada cabecera personalizada debe tener el formato Nombre: Valor.')
            k, v = stripped.split(':', 1)
            items.append((k.strip(), v.strip()))
    else:
        raise ValueError('Formato de cabeceras personalizadas no válido.')
    cleaned = {}
    for raw_k, raw_v in items:
        name = _clean_header_value(raw_k)
        value = _clean_header_value(raw_v)
        if not name or not _HEADER_NAME_RE.fullmatch(name):
            raise ValueError(f'Nombre de cabecera no válido: {name!r}.')
        if name.lower().startswith('x-stainless-'):
            continue
        cleaned[name] = value
    return cleaned


def _merge_csv_tokens(*values):
    seen = set()
    ordered = []
    for raw in values:
        for part in str(raw or '').split(','):
            token = part.strip()
            if token and token.lower() not in seen:
                seen.add(token.lower())
                ordered.append(token)
    return ','.join(ordered)


def _set_header_ci(headers, key, value):
    for existing in [k for k in headers if k.lower() == key.lower()]:
        if existing != key:
            headers.pop(existing, None)
    headers[key] = value


def append_api_version_query(url, cfg, preset):
    """Append ?api-version=... when targeting Azure OpenAI if configured and not already present."""
    if preset != 'azure':
        return url
    api_ver = str((cfg or {}).get('azure_api_version') or '').strip()
    if not api_ver or 'api-version=' in url.lower():
        return url
    from urllib.parse import quote
    sep = '&' if '?' in url else '?'
    return f'{url}{sep}api-version={quote(api_ver, safe="")}'


def build_provider_headers(cfg, api_key='', *, stream=False, session_id=None, default_ua=None, extra_headers=None):
    """Build hardened provider HTTP headers without Python/Stainless leaks and with SSE anti-buffering."""
    cfg = cfg or {}
    protocol = str(cfg.get('protocol') or 'openai').strip().lower()
    base_url = str(cfg.get('base_url') or '')
    preset = infer_provider_preset(protocol, base_url, cfg.get('provider_preset'))
    ua = _clean_header_value(cfg.get('user_agent') or cfg.get('user_agent_override') or default_ua or default_user_agent())

    headers = {
        'Content-Type': 'application/json',
        'User-Agent': ua,
        'Accept': 'text/event-stream' if stream else 'application/json',
        'Accept-Encoding': 'identity',
    }
    if stream:
        headers['Cache-Control'] = 'no-cache'

    auth_mode = resolve_auth_mode(cfg, preset)
    if api_key:
        if auth_mode == 'x-api-key':
            headers['x-api-key'] = api_key
        elif auth_mode == 'api-key':
            headers['api-key'] = api_key
        elif auth_mode == 'bearer':
            headers['Authorization'] = 'Bearer ' + api_key

    if protocol == 'anthropic':
        headers['anthropic-version'] = str(cfg.get('api_version') or DEFAULT_ANTHROPIC_VERSION).strip() or DEFAULT_ANTHROPIC_VERSION
        merged_beta = _merge_csv_tokens(cfg.get('anthropic_beta'), (extra_headers or {}).get('anthropic-beta'))
        if merged_beta:
            headers['anthropic-beta'] = merged_beta
    else:
        for field, header in (('organization', 'OpenAI-Organization'), ('project', 'OpenAI-Project')):
            if cfg.get(field):
                headers[header] = str(cfg[field]).strip()

    send_session = cfg.get('send_session_id')
    if send_session is None:
        send_session = (preset == 'opencode')
    if send_session and session_id:
        headers['x-opencode-session'] = str(session_id)

    referer = _clean_header_value(cfg.get('http_referer') or (DEFAULT_OPENROUTER_REFERER if preset == 'openrouter' else ''))
    x_title = _clean_header_value(cfg.get('x_title') or (DEFAULT_OPENROUTER_TITLE if preset == 'openrouter' else ''))
    if referer:
        headers['HTTP-Referer'] = referer
    if x_title:
        headers['X-Title'] = x_title

    for source in (parse_extra_headers(cfg.get('extra_headers')), parse_extra_headers(extra_headers)):
        for k, v in source.items():
            if k.lower() == 'anthropic-beta' and protocol == 'anthropic':
                headers['anthropic-beta'] = _merge_csv_tokens(headers.get('anthropic-beta'), v)
            else:
                _set_header_ci(headers, k, v)

    if stream:
        _set_header_ci(headers, 'Accept', 'text/event-stream')
        _set_header_ci(headers, 'Cache-Control', 'no-cache')
        _set_header_ci(headers, 'Accept-Encoding', 'identity')

    return headers

