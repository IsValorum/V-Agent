"""Recover complete model tool envelopes and keep their transport markup out of chat."""
import hashlib
import json
import re

from serve.frontend import declared_tool_name, function_end, json_tool_call, parse_tool_call, tool_json_loads

OPEN = "<" + "tool_call" + ">"
CLOSE = "</" + "tool_call" + ">"
LT, GT = "<", ">"

# Recognize complete Markdown fences and inline code before examining calls.
_PROTECTED = (
    r"^[ \t]*(?P<fence>`{3,}|~{3,})[^\n]*\n.*?(?:^[ \t]*(?P=fence)[ \t]*(?=\r?$)|\Z)"
    r"|(?P<inline>`+)[^`\n]*?(?P=inline)|^[ \t]*>[^\n]*"
    r'|(?P<quote>["“«])(?=' + re.escape(OPEN) + r')[^\n]*'
)
PATTERN = re.compile(
    r"(?ms)(?P<protected>" + _PROTECTED + r")|"
    + re.escape(OPEN) + r"\s*(?=[{<])"
)
_JSON = json.JSONDecoder(strict=False)
_ATTRIBUTE_CALL = re.compile(r'^<\s*name\s*=\s*"([^"]+)"\s*,?\s*"?arguments"?\s*:\s*(\{.*\})$', re.S)


def _partial_suffix(buf, word):
    for n in range(min(len(buf), len(word) - 1), 0, -1):
        if buf.endswith(word[:n]):
            return n
    return 0


def _one_call(body, schemas, aliases):
    """Decode complete envelopes without guessing keys, quotes or closing delimiters."""
    body = body.strip()
    if body.startswith("<function=") and function_end(body) == len(body):
        name = declared_tool_name(body[len("<function="):body.index(">")].strip(), schemas)
        if name:
            return name, parse_tool_call(body, {"parameters": schemas[name]}).arguments
        return None

    call = json_tool_call(body, schemas)
    if call and call.arguments:
        return call.name, call.arguments
    flat = complete_json_call(body, schemas, aliases, flat_only=True)
    if flat:
        return flat
    if call:
        return call.name, call.arguments
    if aliases:
        call = json_tool_call(body, aliases, aliases=False)
        if call:
            return aliases[call.name], call.arguments

    # Some models use literal newlines in strings or a name attribute before an
    # otherwise complete object. Decode those forms without changing any values.
    attribute = _ATTRIBUTE_CALL.fullmatch(body)
    try:
        if attribute:
            name = declared_tool_name(attribute[1], schemas)
            args = tool_json_loads(attribute[2], strict=False)
        else:
            obj = tool_json_loads(body, strict=False)
            if not isinstance(obj, dict):
                return None
            name = declared_tool_name(obj.get("name"), schemas)
            args = obj.get("arguments")
    except ValueError:
        return None
    return (name, args) if name and isinstance(args, dict) else None


def _envelope_end(text, start):
    """Locate the closing tag after the value, ignoring tags inside valid JSON."""
    value_end = -1
    if text[start] == "{":
        try:
            _, value_end = _JSON.raw_decode(text, start)
        except ValueError:
            pass
    elif text.startswith("<function=", start):
        relative_end = function_end(text[start:])
        if relative_end >= 0:
            value_end = start + relative_end
    if value_end >= 0:
        closing = value_end
        while closing < len(text) and text[closing].isspace():
            closing += 1
        if text.startswith(CLOSE, closing):
            return value_end, closing + len(CLOSE), True
    closing = text.find(CLOSE, start)
    if closing >= 0:
        return closing, closing + len(CLOSE), True
    return len(text), len(text), False


def complete_json_call(body, schemas, aliases, *, flat_only=False, partial_close=False):
    """Decode a complete object, including declared arguments next to name."""
    body = body.lstrip()

    def unique_object(pairs):
        obj = dict(pairs)
        if len(obj) != len(pairs):
            raise ValueError("duplicate key")
        return obj

    def reject_constant(value):
        raise ValueError(value)

    try:
        decoder = json.JSONDecoder(strict=False, object_pairs_hook=unique_object, parse_constant=reject_constant)
        obj, end = decoder.raw_decode(body)
        tail = body[end:].strip()
        if tail and not (partial_close and CLOSE.startswith(tail)):
            return None
    except ValueError:
        return None
    if not isinstance(obj, dict) or not isinstance(obj.get("name"), str):
        return None
    spelling = obj["name"]
    name = declared_tool_name(spelling, schemas) or aliases.get(spelling)
    if not name:
        return None
    if "arguments" in obj:
        if not flat_only and set(obj) == {"name", "arguments"} and isinstance(obj["arguments"], dict):
            return name, obj["arguments"]
        return None

    args = {key: value for key, value in obj.items() if key != "name"}
    schema = schemas[name]
    properties = schema.get("properties")
    if args and isinstance(properties, dict) and args.keys() <= properties.keys() and set(schema.get("required") or ()) <= args.keys():
        return name, args
    return None


def _complete_json_draft(body, schemas, drafts, aliases):
    """Accept a missing outer tag only for the exact draft seen by the engine."""
    fingerprint = hashlib.sha256(body.encode("utf-8")).digest()
    if fingerprint not in drafts:
        return None
    decoded = complete_json_call(body, schemas, aliases, partial_close=True)
    return decoded if decoded and decoded[0] == drafts[fingerprint] else None


def complete_draft_call(body, schemas, aliases=None):
    """Recover a complete captured envelope; never add arguments or closing braces."""
    body = body.strip()
    if body.startswith('<function='):
        tail = body[len('<function='):]
        if re.match(r'^"(?:[^"\\]|\\.)+"\s*,\s*"arguments"\s*:', tail):
            # A mixed XML opener followed by an otherwise complete JSON object.
            # Duplicate keys, incomplete strings and trailing prose stay rejected.
            return complete_json_call('{"name":' + tail, schemas, aliases or {})
    return complete_json_call(body, schemas, aliases or {})


def recover_text_calls(content, allowed, *, terminal=False, eof_drafts=None, aliases=None):
    """Return only enabled, complete calls, plus clean display text and an attempt flag."""
    schemas = allowed if isinstance(allowed, dict) else {name: {} for name in allowed or ()}
    aliases = aliases or {}
    content = content or ""
    calls, chunks = [], []
    pos = scan = 0
    attempted = False
    while match := PATTERN.search(content, scan):
        scan = match.end()
        if match.group("protected"):
            continue
        attempted = True
        body_end, scan, closed = _envelope_end(content, scan)
        chunks.append(content[pos:match.start()])
        pos = scan
        # An actual call can follow a complete sentence on the same line.
        prefix = content[content.rfind("\n", 0, match.start()) + 1:match.start()].rstrip()
        if prefix and not prefix.endswith((".", "!", "?", CLOSE)):
            continue
        body = content[match.end():body_end]
        if closed:
            decoded = _one_call(body, schemas, aliases)
        elif eof_drafts:
            decoded = _complete_json_draft(body, schemas, eof_drafts, aliases)
        else:
            decoded = None
        if decoded:
            name, args = decoded
            args.pop("_pc_access_key", None)
            calls.append({"id": "", "name": name, "arguments": json.dumps(args, ensure_ascii=False),
                          "args_valid": True, "parsed_args": args})
    chunks.append(content[pos:])
    if terminal and content[pos:].strip():
        calls.clear()
    return calls, "".join(chunks), attempted


def strip_tool_markup(text):
    _, clean, attempted = recover_text_calls(text, {})
    return clean, attempted


class CallFilter:
    """Filtro de streaming: no emite nada de una llamada escrita como texto.

    Tracks Markdown across chunks so examples remain visible. Holds only a
    possible delimiter and discards tool wrappers as they arrive.
    """

    def __init__(self):
        self.buf = ""
        self.suppress = False
        self.empty_openers = 0
        self.json_call = False
        self.in_string = False
        self.escaped = False
        self.fence = ""
        self.inline = ""
        self.delimiter = ""
        self.line_start = True
        self.blockquote = False
        self.last_char = ""

    def _finish_delimiter(self):
        run, self.delimiter = self.delimiter, ""
        if not run:
            return
        if self.line_start and len(run) >= 3 and not self.inline:
            if not self.fence:
                self.fence = run
            elif self.fence[0] == run[0] and len(run) >= len(self.fence):
                self.fence = ""
        elif not self.fence and run[0] == "`":
            if not self.inline:
                self.inline = run
            elif run == self.inline:
                self.inline = ""
        self.line_start = False

    def _track_markdown(self, text):
        for char in text:
            if char in "`~":
                if self.delimiter and char != self.delimiter[-1]:
                    self._finish_delimiter()
                self.delimiter += char
            else:
                self._finish_delimiter()
                if char == "\n":
                    self.line_start = True
                    self.blockquote = False
                elif self.line_start and not char.isspace():
                    self.blockquote = char == ">"
                    self.line_start = False
            self.last_char = char

    def _track_json(self, text):
        if not self.json_call:
            return
        for char in text:
            if self.escaped:
                self.escaped = False
            elif self.in_string and char == "\\":
                self.escaped = True
            elif char == '"':
                self.in_string = not self.in_string

    def feed(self, text):
        """-> lo que se puede mostrar ya."""
        out = []
        self.buf += text or ""
        while self.buf:
            if self.suppress:
                at = self.buf.find(CLOSE)
                if at >= 0:
                    self._track_json(self.buf[:at])
                    self.buf = self.buf[at + len(CLOSE):]
                    if not self.in_string:
                        self.suppress = False
                    else:
                        self._track_json(CLOSE)
                    continue
                keep = _partial_suffix(self.buf, CLOSE)
                end = len(self.buf) - keep
                self._track_json(self.buf[:end])
                self.buf = self.buf[end:]
                return "".join(out)
            at = self.buf.find(OPEN)
            if at < 0:
                hold = _partial_suffix(self.buf, OPEN)
                emit = self.buf[:len(self.buf) - hold]
                self.buf = self.buf[len(self.buf) - hold:] if hold else ""
                if emit:
                    self._track_markdown(emit)
                    out.append(emit)
                return "".join(out)
            before, self.buf = self.buf[:at], self.buf[at:]
            if before:
                self._track_markdown(before)
                out.append(before)
            self._finish_delimiter()
            if self.fence or self.inline or self.blockquote or self.last_char in ('"', '“', '«'):
                out.append(OPEN)
                self._track_markdown(OPEN)
                self.buf = self.buf[len(OPEN):]
                continue
            after = self.buf[len(OPEN):].lstrip()
            if not after or (after != OPEN and OPEN.startswith(after)):
                return "".join(out)
            if after.startswith(OPEN):
                self.empty_openers += 1
                self.buf = after
                continue
            if after[0] in "{<":
                self.suppress = True
                self.json_call = after[0] == "{"
                self.in_string = self.escaped = False
                self.buf = self.buf[len(OPEN):]
                continue
            out.append(OPEN)
            self._track_markdown(OPEN)
            self.buf = self.buf[len(OPEN):]
        return "".join(out)

    def flush(self):
        tail, self.buf = self.buf, ""
        if self.suppress or (self.empty_openers and tail.lstrip().startswith(OPEN)):
            self.suppress = False
            return ""
        return tail
