"""Keeping a long agentic turn alive: engine/provider errors and the context window.

Two things used to end an autonomous run that was otherwise going well:
  * one transient failure of the engine or the provider (a 429/503, a dropped connection, a reply cut
    halfway) raised out of the loop at round 20 and the whole task was lost;
  * a turn of many tool rounds kept every tool result in the prompt until the model's window was full,
    and the engine then refused the request ("exceeds the available context size").
Here: which errors are worth retrying, how long to wait, and how to make the prompt fit again without
losing what was done (old tool batches are archived to the conversation folder and replaced by a
short record, as `context_policy.project_messages` does at the start of a turn).
"""
import copy
import json
import re

# Retried: rate limits, provider overload and gateway errors, connections cut or timed out, replies
# that stopped without their end mark. Never retried: authentication, a bad request, a missing model.
_TRANSIENT_STATUS = re.compile(r'\((?:408|409|425|429|500|502|503|504|520|521|522|523|524|529)\)')
_TRANSIENT_TEXT = re.compile(
    r'se cort[oó] antes de terminar|overloaded|rate[ _-]?limit|too many requests|temporarily unavailable|'
    r'service unavailable|bad gateway|gateway time-?out|timed? ?out|connection (?:reset|aborted|refused)|'
    r'remote ?(?:end )?closed|remotedisconnected|incompleteread|winerror 1005[34]|'
    r'el motor interrumpi[oó] la respuesta|server is busy|try again', re.I)
_OVERFLOW = re.compile(
    r'exceeds? the (?:available )?context|context(?:[ _-]?length| window| size)[^.]{0,40}(?:exceed|too|limit|maximum)|'
    r'maximum context|context_length_exceeded|exceed_context_size|too many tokens|prompt is too long|'
    r'input is too long|request \(\d+ tokens\) exceeds|reduce the length of the (?:messages|prompt)', re.I)
_NOT_RETRIED = re.compile(r'\((?:400|401|402|403|404|405|413|422)\)')

ATTEMPTS = {'transient': 3, 'overflow': 2}
DELAYS = (2.0, 6.0, 15.0)


def classify(error):
    """'overflow', 'transient' or None (stop: retrying would only repeat the same failure)."""
    text = str(error or '')
    if _OVERFLOW.search(text) or '(413)' in text:
        return 'overflow'
    if isinstance(error, (ConnectionError, TimeoutError)):
        return 'transient'
    name = type(error).__name__
    if name in ('RemoteDisconnected', 'IncompleteRead', 'BadStatusLine', 'timeout'):
        return 'transient'
    if _NOT_RETRIED.search(text):
        return None
    if _TRANSIENT_STATUS.search(text) or _TRANSIENT_TEXT.search(text):
        return 'transient'
    return None


def delay(attempt):
    """Seconds to wait before retry number `attempt` (1-based)."""
    return DELAYS[min(max(attempt, 1), len(DELAYS)) - 1]


def chars(messages, tools=None):
    return len(json.dumps(messages, ensure_ascii=False)) + (len(json.dumps(tools, ensure_ascii=False)) if tools else 0)


# Characters per token used to turn a window in tokens into a size the prompt may reach. Low on
# purpose (real text is ~3.5-4 for English, code and JSON are denser): better archive a little early
# than send a request the engine refuses.
CHARS_PER_TOKEN = 3.0


def _shorten_old(messages, keep_last, calls_everywhere=False):
    """Cut long tool outputs and long file contents in calls, except in the last `keep_last` messages.

    The system message and every user message stay whole; so does the shape of each call/result pair
    (only text inside is shortened), so the transcript stays valid for every engine.
    `calls_everywhere` also shortens the file contents sent in the latest calls: they already ran (the
    file is on disk), so the model does not need its own long arguments back.
    """
    out = copy.deepcopy(messages)
    limit = max(0, len(out) - keep_last)
    removed = 0
    for i in range(len(out)):
        message = out[i]
        role = message.get('role')
        if i >= limit and not (calls_everywhere and role == 'assistant'):
            continue
        if role == 'tool' and isinstance(message.get('content'), str) and len(message['content']) > 1200:
            text = message['content']
            message['content'] = (text[:700] + '\n[Older tool output shortened to keep the conversation within the '
                                  'model\'s context: %d characters removed. Run the tool again if you need the rest.]'
                                  % (len(text) - 700))
            removed += len(text) - 700
        elif role == 'assistant':
            for call in message.get('tool_calls') or []:
                function = call.get('function') or {}
                raw = function.get('arguments')
                if not isinstance(raw, str) or len(raw) <= 1500:
                    continue
                try:
                    args = json.loads(raw)
                except ValueError:
                    continue
                if not isinstance(args, dict):
                    continue
                for key in ('content', 'new_text', 'text', 'code'):
                    value = args.get(key)
                    if isinstance(value, str) and len(value) > 600:
                        args[key] = ('[%d characters, sent in this earlier call; read the file if you need them]'
                                     % len(value))
                        removed += len(value)
                function['arguments'] = json.dumps(args, ensure_ascii=False)
            if isinstance(message.get('reasoning_content'), str) and len(message['reasoning_content']) > 2000:
                removed += len(message['reasoning_content']) - 400
                message['reasoning_content'] = message['reasoning_content'][:400] + ' [...]'
    return out, removed


def fit(messages, window_tokens, *, tools=None, archive=None, force=False):
    """Make the prompt fit the window. Returns (messages, report or None).

    `archive(messages, keep_batches)` moves old tool batches out of the prompt (to the conversation
    folder) and returns (messages, info); it is None when there is no folder to write to.
    Nothing changes while the prompt is under 60 % of the window (the engine's prompt cache keeps
    working); `force` (the engine just refused the prompt as too long) always makes it smaller.
    """
    budget = int(window_tokens * CHARS_PER_TOKEN) if window_tokens else 0
    before = chars(messages, tools)
    if not force and (not budget or before <= budget * 0.6):
        return messages, None
    current, archived = messages, 0
    if archive is not None:
        try:
            current, info = archive(messages, 2 if force else 4)
            archived = int((info or {}).get('offloaded_batches') or 0)
        except Exception:
            current = messages
    removed = 0
    # Refused by the engine: the declared window was not the real limit, so aim at half of what was sent.
    target = min(budget * 0.75, before * 0.5) if force and budget else before * 0.5 if force else budget * 0.75
    if force or not budget or chars(current, tools) > target:
        # Shorten everything but the latest steps; if that is not enough, keep only the last call/result.
        for keep, everywhere in (((4, False), (2, False), (2, True)) if force else ((6, False), (2, False))):
            shortened, removed = _shorten_old(current, keep, everywhere)
            if target and chars(shortened, tools) <= target:
                break
        current = shortened
    after = chars(current, tools)
    if after >= before:
        return messages, None
    return current, {'before_chars': before, 'after_chars': after, 'archived_batches': archived,
                     'shortened_chars': removed, 'window_tokens': window_tokens or None}
