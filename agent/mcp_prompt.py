"""Small model-facing MCP contracts; the hub keeps its original schemas and routes."""
import copy

DESCRIPTIONS = {
    'pc__code_check': 'File: check syntax by default. Directory: list project checks without executing. Run a listed check ID with run=true (full-PC only). Report verification scope; passing syntax or one check does not prove the task is complete.',
    'pc__draft_resume': 'Resume the latest saved draft in this conversation. Takes no arguments; returns a working file without regenerating code.',
    'duckduckgo__web_search': 'Search the web; returns titles, URLs and snippets. When results look relevant, visit the 1–3 most promising URLs with web_visit before answering; snippets may be stale or incomplete.',
    'duckduckgo__web_visit': 'Read a URL. Use it on relevant search results instead of answering from snippets alone. Continue only as needed: reuse page_id and set offset=next_offset.',
    'pc__fs_list': 'List a directory; "." is the working folder.',
    'pc__fs_read': 'Read UTF-8 text. offset continues by character; linea is a 1-based line, ventana is the line count.',
    'pc__fs_write': 'Overwrite a UTF-8 file; creates parent directories.',
    'pc__fs_edit': 'Replace exact blocks in an existing file: one old_text/new_text, or edits=[{old_text,new_text},...] (all or nothing). old_text must match verbatim and appear once, else widen it or set all=true. fs_write creates.',
    'pc__fs_copy': 'Transfer selected text lines between files without retyping. This edits text; use fs_manage to copy/move whole files or directories. modo selects insertion/replacement; cortar=true moves text.',
    'pc__fs_search': 'Search files by glob and/or literal/regex text; returns paths and line matches.',
    'pc__fs_manage': 'Create, delete, move, copy or inspect whole files/directories. For text replacements use fs_edit; for transferring selected lines use fs_copy.',
    'web__http_request': 'Call a URL/API directly, with explicit method, headers, cookies and body. Does not execute page JavaScript. For interactive pages use a browser; for large files use download. HTTP success is not task verification.',
    'web__download': 'Stream a URL to a file atomically; returns path, bytes and sha256. No browser session cookies; use browser_download for authenticated browser downloads. Does not execute or validate the file.',
    'autobrowser__open': 'Open or navigate the autonomous browser; new_tab=true opens another tab. Prefer pc__browser when working in the visible user browser. Get selectors with snapshot before click/fill.',
    'autobrowser__snapshot': 'Return title, URL, text and up to 120 interactive selectors from the autonomous browser.',
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
    """Remove display annotations, keeping validation and property names intact."""
    if not isinstance(schema, dict):
        return copy.deepcopy(schema)
    result = {}
    for key, value in schema.items():
        if key in ('title', 'examples', '$comment', '$schema') or key == 'default' and value is None:
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

def compact_tools(tools):
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
            fn['description'] = DESCRIPTIONS[name]
            # Keep parameter semantics; display-only annotations were removed above.
            if name == 'duckduckgo__web_search' and {'query', 'region', 'timelimit'} <= props.keys() and not set(schema.get('required') or []) - {'query'}:
                # The search server also carries an old URL-reader alias. Visit owns
                # reading/pagination in this agent, so do not declare that API twice.
                fn['parameters'] = {'type': 'object', 'properties': {
                    'query': {'type': 'string'},
                    'region': {'type': 'string', 'description': 'Optional locale override; omit for user settings.'},
                    'timelimit': {'type': ['string', 'null'], 'enum': ['d', 'w', 'm', 'y', None], 'description': 'Age: day/week/month/year; omit for user settings.'},
                }, 'required': ['query']}
            elif name == 'duckduckgo__web_visit' and 'find_in_page' in props:
                props['find_in_page']['description'] = 'Focus keywords.'
            elif name == 'pc__shell_run' and 'timeout' in props:
                props['timeout']['description'] = 'Seconds; omit for user settings.'
        output.append(item)
    return output

def check_search_arguments(name, args):
    """The legacy search->visit alias must not bypass the separate Visit switch."""
    if name == 'duckduckgo__web_search':
        if any(key not in ('query', 'region', 'timelimit') for key in args):
            raise ValueError('web_search accepts query, region, timelimit. Use web_visit to read URLs.')
        if not isinstance(args.get('query'), str) or not args['query'].strip():
            raise ValueError('web_search requires a nonempty query.')


def validate_tool_arguments(schema, args, strict=True):
    """Check the flat contracts used by the local MCPs before any side effects."""
    properties = schema.get('properties')
    if not isinstance(properties, dict):
        return
    for key in schema.get('required') or ():
        if key not in args:
            raise ValueError(f'Missing required argument: {key}.')
    for key, value in args.items():
        if key not in properties:
            if strict or schema.get('additionalProperties') is False:raise ValueError(f'Unknown argument: {key}. Use declared arguments.')
            continue
        field = properties[key]
        if not isinstance(field, dict):
            continue
        kinds = field.get('type')
        kinds = [kinds] if isinstance(kinds, str) else kinds
        matches = {'string': isinstance(value, str), 'integer': type(value) is int,
                   'number': type(value) in (int, float), 'boolean': type(value) is bool,
                   'object': isinstance(value, dict), 'array': isinstance(value, list), 'null': value is None}
        if kinds and not any(matches.get(kind, True) for kind in kinds):
            raise ValueError(f'Argument {key}: expected {" or ".join(kinds)}.')
        if 'enum' in field and value not in field['enum']:
            raise ValueError(f'Argument {key}: value is not a declared option.')
        if type(value) in (int, float):
            if 'minimum' in field and value < field['minimum']:
                raise ValueError(f'Argument {key}: minimum {field["minimum"]}.')
            if 'maximum' in field and value > field['maximum']:
                raise ValueError(f'Argument {key}: maximum {field["maximum"]}.')
