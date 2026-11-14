"""Resume saved work within one conversation, without regenerating its contents."""
import json
import re
from pathlib import Path


def extract_file(snapshot):
    args = snapshot.get('args') or {}
    if isinstance(args.get('content'), str):
        return args.get('path') or 'archivo.txt', args['content'], True
    raw = snapshot.get('raw') or ''
    from tool_markup import complete_draft_call
    decoded = complete_draft_call(raw, {'pc__fs_write': {}})
    if decoded and isinstance(decoded[1].get('content'), str):
        return decoded[1].get('path') or 'archivo.txt', decoded[1]['content'], True
    # A stopped JSON string: keep only complete decoded characters. Never invent
    # missing escapes, closing HTML or the rest of the program.
    match = re.search(r'"content"\s*:\s*"', raw)
    if match:
        encoded = raw[match.end():]
        pieces = []
        i = 0
        complete = False
        while i < len(encoded):
            char = encoded[i]
            if char == '"':
                complete = True
                break
            if char != '\\':
                pieces.append(char)
                i += 1
                continue
            size = 6 if encoded[i:i+2] == '\\u' else 2
            token = encoded[i:i+size]
            try:
                if len(token) != size:
                    break
                json.loads('"' + token + '"')
                pieces.append(token)
            except ValueError:
                break
            i += size
        content = json.loads('"' + ''.join(pieces) + '"', strict=False)
        if not complete and content and 0xD800 <= ord(content[-1]) <= 0xDBFF:
            content = content[:-1]
        path = re.search(r'"path"\s*:\s*("(?:[^"\\]|\\.)*")', raw)
        return json.loads(path[1]) if path else 'archivo.html', content, complete
    match = re.search(r'<parameter=content>\r?\n?', raw)
    if match:
        tail = raw[match.end():]
        closed = '</parameter>' in tail
        text = tail.split('</parameter>', 1)[0]
        if closed and text.endswith('\n'):
            text = text[:-1]
        path = re.search(r'<parameter=path>\s*(.*?)\s*</parameter>', raw, re.S)
        return (path[1].strip() if path else '') or 'archivo.html', text, closed
    return None


def pending_draft(workspace, draft_id=None):
    from draft_store import read_draft
    folder = workspace.path('drafts')
    candidates = [folder / (draft_id + '.json')] if draft_id else sorted(
        folder.glob('*.json'), key=lambda p: p.stat().st_mtime_ns, reverse=True)
    for path in candidates:
        if not re.fullmatch(r'[0-9a-f]{32}', path.stem):
            continue
        try:
            snapshot = read_draft(workspace, path.stem)
        except (OSError, ValueError):
            continue
        if snapshot.get('name') not in ('pc__fs_write', 'mcp__draft'):
            continue
        if not draft_id and snapshot.get('status') == 'completed':
            return None
        file = extract_file(snapshot)
        if file and file[1]:
            return snapshot, file
    return None


def resume_draft(workspace, draft_id=None):
    if draft_id is not None and (not isinstance(draft_id, str) or not re.fullmatch(r'[0-9a-f]{32}', draft_id)):
        raise ValueError('Invalid draft identifier.')
    found = pending_draft(workspace, draft_id)
    if not found:
        raise ValueError('No recoverable file draft found in this conversation.')
    snapshot, (name, content, complete) = found
    filename = re.sub(r'[^\w. -]', '_', Path(str(name).replace('\\', '/')).name)[:100] or 'archivo.txt'
    relative = 'recuperados/' + snapshot['id'] + '-' + filename
    target = workspace.path(relative)
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        with target.open('x', encoding='utf-8', newline='') as file:
            file.write(content)
    except FileExistsError:
        pass  # A later resume must preserve edits already made to this copy.
    return {'draft_id': snapshot['id'], 'path': relative, 'target_path': filename, 'complete': complete,
            'chars': len(target.read_text(encoding='utf-8')),
            'note': 'Continue working on this file; read and edit only what is needed, then write the final target file (' + filename + ').' if complete else
                    'Generation interrupted: this file contains only the partial prefix received so far. Read the end with pc__fs_read and write/complete the final target file (' + filename + ') instead of rewriting from scratch.'}
