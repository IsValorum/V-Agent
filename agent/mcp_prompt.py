"""Small model-facing MCP contracts; the hub keeps its original schemas and routes."""
import copy

DESCRIPTIONS = {
    'pc__code_check': 'File: check syntax by default (returns structured JSON with ok:false when syntax issues exist). Directory: list project checks without executing. Run a listed check ID with run=true (full-PC only). Report verification scope; passing syntax or one check does not prove the task is complete.',
    'pc__draft_resume': 'Resume the latest saved draft (drafts/) in this conversation. Takes no arguments; restores a readable file path (recuperados/...) plus tail preview without regenerating code. Finish it fast with fs_copy(desde=..., destino=..., modo="nuevo") + fs_edit. Do not read drafts/ directly with fs_read.',
    'duckduckgo__web_search': 'Search the web; returns titles, URLs and snippets. When results look relevant, visit the 1–3 most promising URLs with web_visit before answering; snippets may be stale or incomplete.',
    'duckduckgo__web_visit': 'Read a URL. Use it on relevant search results instead of answering from snippets alone. Continue only as needed: reuse page_id and set offset=next_offset.',
    'pc__fs_list': 'List a directory; "." is the working folder, or pass any relative or absolute directory path.',
    'pc__fs_read': 'Read a UTF-8 text file (relative or absolute path; for directories use fs_list). offset continues by character; linea is a 1-based line, ventana is the line count.',
    'pc__doc_read': 'Extract text, tables and metadata from PDF, DOCX, XLSX, PPTX, ODT/ODS/ODP, EPUB, RTF, HTML, XML and CSV (relative or absolute path).',
    'pc__fs_write': 'Create or overwrite a UTF-8 file (relative or absolute path); creates parent directories.',
    'pc__fs_edit': 'Replace exact blocks in an existing file: one old_text/new_text, or edits=[{old_text,new_text},...] (all or nothing). old_text must match verbatim and appear once, else widen it or set all=true. fs_write creates.',
    'pc__fs_copy': 'Transfer selected text lines between files without retyping. This edits text; use fs_manage to copy/move whole files or directories. modo selects insertion/replacement; cortar=true moves text.',
    'pc__fs_search': 'Search files by glob and/or literal/regex text in path (default ".", or any directory path); returns paths and line matches.',
    'pc__fs_manage': 'Create, delete, move, copy or inspect whole files/directories. For text replacements use fs_edit; for transferring selected lines use fs_copy.',
    'admin__start': 'Start the elevated Administrator helper session (prompts Windows UAC once).',
    'admin__status': 'Report whether the elevated Administrator helper is running or on standby (ready to auto-start on admin__run or admin__start).',
    'admin__run': 'Run a PowerShell or CMD command with elevated Administrator privileges (auto-starts the UAC helper on first call if on standby).',
    'admin__stop': 'Stop the elevated Administrator helper session.',
    'web__http_request': 'Call a URL/API directly, with explicit method, headers, cookies and body. Does not execute page JavaScript (use duckduckgo__web_search, pc__browser or JSON APIs instead of JS-gated search pages). Truncates cleanly at max_bytes when reading; pass format="readability" or extract="readability" for clean text. For large files use download.',
    'web__download': 'Stream a URL to a file atomically; returns path, bytes and sha256. No browser session cookies; use browser_download for authenticated browser downloads. Does not execute or validate the file.',
    'autobrowser__open': 'Open or navigate the autonomous browser; new_tab=true opens and activates a new tab (returns active_index). Use pc__browser or duckduckgo__web_search if a site blocks headless browsers with a server-side CAPTCHA. Get selectors with snapshot before click/fill.',
    'autobrowser__snapshot': 'Return title, URL, text excerpt and compact interactive selectors (default max_items=50) from the autonomous browser.',
    'autobrowser__screenshot': 'Capture a PNG of the autonomous browser page and return its path.',
    'autobrowser__browser_console': 'Read console messages from the autonomous browser.',
    'autobrowser__browser_download': 'Download a URL through the autonomous browser.',
    'computer__screen_capture': 'Capture the desktop, save a PNG and return Windows OCR text plus the active window. Use OCR text instead of polling screenshots.',
    'computer__window_list': 'List visible windows and the active one.',
    'computer__window_focus': 'Focus a visible window by title substring.',
    'computer__mouse_click': 'Click absolute screen coordinates.',
    'computer__keyboard_type': 'Type Unicode text into the focused control.',
    'computer__keyboard_key': 'Press a key or combo (Ctrl+L, Alt+F4, Enter, ...).',
    'pc__web_render': 'Execute HTML in a headless browser and report runtime errors plus available scene diagnostics. Timeouts are inconclusive. No console errors does not prove correct visuals, interactions or requirements.',
    'pc__shell_run': 'Run a Windows cmd command (not bash: no ls/cat/which). With limited access only CMD built-ins and python run, offline; use fs_list/fs_read for files. background=true starts a job for job_wait/job_status/job_stop. Environment is not kept between calls; use console for a persistent session.',
    'pc__sys_info': 'Exact CPU model, OS, RAM, disks and GPU.',
    'pc__browser': 'Control the visible V-Agent browser. Snapshot gives a short text excerpt and selectors; use action=text for the page, click/fill with those selectors, eval for advanced cases.',
    'pc__console': 'Use the visible persistent shell session; cwd and environment survive between calls. Full-PC only; Light mode requires approval for each execution. For background jobs use shell_run. Exit 0 only confirms the command completed.',
}

def compact_schema(schema):
    """Preserve complete parameter descriptions and schema instructions."""
    if not isinstance(schema, dict):
        return copy.deepcopy(schema)
    result = {}
    for key, value in schema.items():
        if key == '$schema':
            continue
        if key in ('properties', 'patternProperties', '$defs', 'definitions', 'dependentSchemas'):
            result[key] = {name: compact_schema(child) for name, child in value.items()}
        elif key in ('allOf', 'anyOf', 'oneOf', 'prefixItems'):
            result[key] = [compact_schema(child) for child in value]
        elif key in ('items', 'additionalProperties', 'unevaluatedProperties', 'not', 'if', 'then', 'else', 'contains'):
            result[key] = compact_schema(value)
        else:
            result[key] = copy.deepcopy(value)
    variants = result.get('anyOf')
    if variants and all(isinstance(child, dict) and set(child) == {'type'} and isinstance(child['type'], str) for child in variants):
        result['type'] = list(dict.fromkeys(child['type'] for child in variants))
        del result['anyOf']
    return result

def _dynamic_description(name, enabled_names):
    """Describe alternatives using only tools actually enabled in this request."""
    if name == 'web__http_request':
        alts = []
        if 'duckduckgo__web_search' in enabled_names:
            alts.append('duckduckgo__web_search')
        if 'pc__browser' in enabled_names:
            alts.append('pc__browser')
        alts.append('public JSON APIs')
        alt_text = ', '.join(alts)
        return (
            'Call a URL/API directly, with explicit method, headers, cookies and body. '
            f'Does not execute page JavaScript (prefer {alt_text}; if blocked on the server side, suggest the user open it in a visible browser). '
            'Truncates cleanly at max_bytes when reading; pass format="readability" or extract="readability" for clean text. For large files use download.'
        )
    if name == 'autobrowser__open':
        alts = [t for t in ('pc__browser', 'duckduckgo__web_search') if t in enabled_names]
        gate = (
            f"If a site returns server_blocked=true or a CAPTCHA, do not retry the blocked host here; use {' or '.join(alts)} or suggest the user open it in the visible browser."
            if alts
            else "If a site returns server_blocked=true or a CAPTCHA, do not retry the blocked host here; suggest the user open it directly in a visible browser."
        )
        return f'Open or navigate the autonomous browser; new_tab=true opens and activates a new tab (returns active_index). {gate} Get selectors with snapshot before click/fill.'
    if name == 'web__download':
        if 'autobrowser__browser_download' in enabled_names:
            return DESCRIPTIONS['web__download']
        return 'Stream a URL to a file atomically; returns path, bytes and sha256. No browser session cookies. Does not execute or validate the file.'
    if name == 'pc__shell_run':
        parts = [
            'Run a Windows cmd command (not bash: no ls/cat/which). With limited access only CMD built-ins and python run, offline; use fs_list/fs_read for files.'
        ]
        if 'pc__job_wait' in enabled_names:
            parts.append('background=true starts a job for job_wait/job_status/job_stop.')
        if 'pc__console' in enabled_names:
            parts.append('Environment is not kept between calls; use console for a persistent session.')
        else:
            parts.append('Environment is not kept between calls.')
        return ' '.join(parts)
    return DESCRIPTIONS[name]


def compact_tools(tools):
    enabled_names = {((tool.get('function') or {}).get('name') or '') for tool in tools}
    output = []
    for tool in tools:
        item = copy.deepcopy(tool)
        fn = item.get('function') or {}
        name = fn.get('name')
        if 'parameters' in fn:
            fn['parameters'] = compact_schema(fn['parameters'])
        schema = fn.get('parameters') or {}
        props = schema.get('properties') or {}
        if name=='web__http_request':props.pop('download_dir',None)
        if name in DESCRIPTIONS:
            orig_desc = str(fn.get('description') or '').strip()
            dyn_desc = _dynamic_description(name, enabled_names)
            # Never shorten an existing MCP description when no dynamic routing adjustment applies.
            if name in ('web__http_request', 'autobrowser__open', 'web__download', 'pc__shell_run'):
                fn['description'] = dyn_desc
            else:
                fn['description'] = orig_desc if len(orig_desc) > len(dyn_desc) else dyn_desc
            if name == 'duckduckgo__web_search' and {'query', 'region', 'timelimit'} <= props.keys() and not set(schema.get('required') or []) - {'query'}:
                # The search server also carries an old URL-reader alias. Visit owns
                # reading/pagination in this agent, so preserve full search parameter schemas without 'url'.
                fn['parameters'] = {'type': 'object', 'properties': {
                    k: copy.deepcopy(props[k]) for k in ('query', 'region', 'timelimit') if k in props
                }, 'required': ['query']}
        output.append(item)
    return output

def check_search_arguments(name, args):
    """The legacy search->visit alias must not bypass the separate Visit switch."""
    if name == 'duckduckgo__web_search':
        if any(key not in ('query', 'region', 'timelimit') for key in args):
            raise ValueError('web_search accepts query, region, timelimit. Use web_visit to read URLs.')
        if not isinstance(args.get('query'), str) or not args['query'].strip():
            raise ValueError('web_search requires a nonempty query.')


def _matches_kind(value, kind):
    if kind == 'string': return isinstance(value, str)
    if kind == 'integer': return type(value) is int
    if kind == 'number': return type(value) in (int, float)
    if kind == 'boolean': return type(value) is bool
    if kind == 'object': return isinstance(value, dict)
    if kind == 'array': return isinstance(value, list)
    if kind == 'null': return value is None
    return True


def _parse_int_text(value):
    text = value.strip()
    digits = text[1:] if text[:1] in '+-' else text
    return int(text) if digits.isascii() and digits.isdigit() else None


def _parse_number_text(value):
    text = value.strip().lower()
    if text in ('nan', 'inf', '+inf', '-inf', 'infinity', '+infinity', '-infinity'):
        return None
    try:
        parsed = float(value.strip())
    except ValueError:
        return None
    return parsed if parsed == parsed and abs(parsed) != float('inf') else None


def _schema_types(field):
    branches = [b for b in (field.get('anyOf') or field.get('oneOf') or ()) if isinstance(b, dict)]
    raw_types = []
    for src in [field, *branches]:
        t = src.get('type')
        if isinstance(t, str):
            raw_types.append(t)
        elif isinstance(t, list):
            raw_types.extend(t)
    return list(dict.fromkeys(raw_types)), branches


def validate_tool_arguments(schema, args, strict=True):
    """Check the flat contracts used by the local MCPs before any side effects."""
    if not isinstance(args, dict):
        raise ValueError('Tool arguments must be a JSON object.')
    properties = schema.get('properties')
    if not isinstance(properties, dict):
        return
    for key in list(args):
        if key not in properties:
            if strict or schema.get('additionalProperties') is False:
                allowed = ', '.join(sorted(properties))
                raise ValueError(f'Unknown argument: {key}. Allowed arguments: {allowed}.')
    for key in schema.get('required') or ():
        if key not in args:
            raise ValueError(f'Missing required argument: {key}.')
    for key, value in list(args.items()):
        if key not in properties:
            continue
        field = properties[key]
        if not isinstance(field, dict):
            continue
        kinds, branches = _schema_types(field)
        # Coerce common 4B/8B stringified scalars/JSON when the parameter does not accept strings.
        if isinstance(value, str) and kinds and 'string' not in kinds:
            stripped = value.strip()
            if 'boolean' in kinds and stripped.lower() in ('true', 'false'):
                value = stripped.lower() == 'true'
                args[key] = value
            elif 'integer' in kinds and _parse_int_text(value) is not None:
                value = _parse_int_text(value)
                args[key] = value
            elif 'number' in kinds and _parse_number_text(value) is not None:
                value = _parse_number_text(value)
                args[key] = value
            elif 'object' in kinds and stripped.startswith('{'):
                try:
                    parsed = __import__('json').loads(stripped)
                    if isinstance(parsed, dict):
                        value = parsed
                        args[key] = value
                except ValueError:
                    pass
            elif 'array' in kinds and stripped.startswith('['):
                try:
                    parsed = __import__('json').loads(stripped)
                    if isinstance(parsed, list):
                        value = parsed
                        args[key] = value
                except ValueError:
                    pass
        if kinds and not any(_matches_kind(value, kind) for kind in kinds):
            raise ValueError(f'Argument {key}: expected {" or ".join(kinds)}.')
        if 'enum' in field and value not in field['enum']:
            opts = ', '.join(repr(item) for item in field['enum'])
            raise ValueError(f'Argument {key}: invalid value {value!r}; expected one of: {opts}.')
        matched_branch = None
        if branches:
            for branch in branches:
                bt = branch.get('type')
                bt_list = [bt] if isinstance(bt, str) else (bt or ())
                if not bt_list or any(_matches_kind(value, kind) for kind in bt_list):
                    matched_branch = branch
                    if 'enum' in branch and value not in branch['enum']:
                        continue
                    break
            if matched_branch and 'enum' in matched_branch and value not in matched_branch['enum']:
                opts = ', '.join(repr(item) for item in matched_branch['enum'])
                raise ValueError(f'Argument {key}: invalid value {value!r}; expected one of: {opts}.')
        num_schema = matched_branch if matched_branch and ('minimum' in matched_branch or 'maximum' in matched_branch) else field
        if type(value) in (int, float):
            if 'minimum' in num_schema and value < num_schema['minimum']:
                raise ValueError(f'Argument {key}: minimum {num_schema["minimum"]}.')
            if 'maximum' in num_schema and value > num_schema['maximum']:
                raise ValueError(f'Argument {key}: maximum {num_schema["maximum"]}.')
        if isinstance(value, list):
            items_schema = (matched_branch.get('items') if matched_branch else None) or field.get('items')
            if isinstance(items_schema, dict) and isinstance(items_schema.get('type'), str):
                item_kind = items_schema['type']
                for idx, item in enumerate(value):
                    if not _matches_kind(item, item_kind):
                        raise ValueError(f'Argument {key}[{idx}]: expected {item_kind}.')
