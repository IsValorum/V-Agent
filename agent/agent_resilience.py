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
import random
import re
import socket

# How the open-source harnesses do it (read in their sources, 2026-11-17), and what is taken here:
#   * OpenCode (packages/core/src/model-retry.ts, packages/ai/src/provider-error.ts): a provider's
#     throttle or server error is retried 10 times, exponential from 2 s with jitter; Retry-After is
#     honoured (capped at 15 min); a quota/balance error is never retried; with no network path at all it
#     keeps trying for an hour; a timed-out attempt is retried at most 3 times; context overflow is its own
#     class (compact, then retry).
#   * Goose (goose-provider-types/src/retry.rs): exponential from 1 s, gap capped at 30 s, jitter 0.8-1.2,
#     the provider's retry delay wins for rate limits; permanent 4xx are not retried.
#   * Roo Code: when the user lets it act alone it never gives up on a busy provider (5 s x 2^n up to
#     10 min per wait, with a visible countdown).  Aider (litellm): about 60 s in total.
# Here: OpenCode's classes and Retry-After, Goose's 30 s cap per gap: 10 attempts, about 3.5 minutes of
# waiting for a provider that keeps answering "overloaded" (DeepSeek 529 lasted longer than 23 s).

_OVERFLOW = re.compile(
    r'exceeds? the (?:available )?context|context(?:[ _-]?length| window| size)[^.]{0,40}(?:exceed|too|limit|maximum)|'
    r'maximum context|context_length_exceeded|exceed_context_size|model_context_window_exceeded|prompt is too long|'
    r'input is too long|request \(\d+ tokens\) exceeds|reduce the length of the (?:messages|prompt)|'
    r'greater than the context length|context window exceeded', re.I)
# A 429 that is an exhausted balance or plan, not a throttle: waiting does not help.
_QUOTA = re.compile(r'insufficient[-_\s]?(?:quota|balance)|(?<!token_)quota[-_\s]?exceeded|budget exceeded|usage limit|'
                    r'billing|credit limit|package has expired|no queda saldo', re.I)
_THROTTLE_OR_BUSY = re.compile(
    r'se cort[oó] antes de terminar|overloaded|saturado|rate[ _-]?limit|too many requests|temporarily unavailable|'
    r'service[-_\s]?unavailable|bad gateway|at capacity|server (?:is )?busy|try again|resource[-_\s]?exhausted|'
    r'connection (?:reset|aborted|refused)|remote ?(?:end )?closed|remotedisconnected|incompleteread|'
    r'winerror 1005[34]|el motor interrumpi[oó] la respuesta|upstream (?:connect|request)', re.I)
_UNREACHABLE = re.compile(r'getaddrinfo failed|name or service not known|nodename nor servname|no route to host|'
                          r'network is unreachable|winerror 1006[45]|winerror 10051|winerror 1100[12]', re.I)
_TIMEOUT = re.compile(r'timed? ?out|time-?out', re.I)
_STATUS = re.compile(r'\((\d{3})\)')

ATTEMPTS = {'transient': 10, 'timeout': 3, 'overflow': 2}
UNREACHABLE_SECONDS = 3600
RETRY_AFTER_MAX_SECONDS = 15 * 60
FIRST_DELAY, GAP_CAP = 2.0, 30.0


def _status(error):
    status = getattr(error, 'status', None)
    if isinstance(status, int):
        return status
    match = _STATUS.search(str(error or ''))
    return int(match.group(1)) if match else None


def classify(error):
    """'overflow', 'transient', 'timeout', 'unreachable' or None (stop: a retry would fail the same way)."""
    text = str(error or '')
    status = _status(error)
    if status != 429 and (_OVERFLOW.search(text) or status == 413):
        return 'overflow'
    if status == 402 or _QUOTA.search(text):
        return None
    if isinstance(error, socket.gaierror) or _UNREACHABLE.search(text):
        return 'unreachable'
    if status in (408, 409, 425, 429) or (status is not None and status >= 500):
        return 'transient'
    if status is not None and 400 <= status < 500:
        return None
    if isinstance(error, TimeoutError) or type(error).__name__ == 'timeout' or _TIMEOUT.search(text):
        return 'timeout'
    if isinstance(error, ConnectionError) or type(error).__name__ in ('RemoteDisconnected', 'IncompleteRead', 'BadStatusLine'):
        return 'transient'
    if _THROTTLE_OR_BUSY.search(text):
        return 'transient'
    return None


def allowed(kind, attempt, elapsed):
    """Whether retry number `attempt` (1-based) may run, `elapsed` seconds after this round's first failure."""
    if kind == 'unreachable':
        return elapsed < UNREACHABLE_SECONDS
    return attempt <= ATTEMPTS.get(kind, 0)


def delay(attempt, retry_after_ms=None, jitter=True):
    """Seconds before retry number `attempt`: 2, 4, 8, 16 s, then 30 s, with +-20 % jitter so many clients do
    not come back at the same instant; never shorter than the provider's Retry-After (capped at 15 min)."""
    seconds = min(FIRST_DELAY * 2 ** (max(attempt, 1) - 1), GAP_CAP)
    if jitter:
        seconds *= 0.8 + random.random() * 0.4
    if retry_after_ms:
        seconds = max(seconds, min(retry_after_ms / 1000.0, RETRY_AFTER_MAX_SECONDS))
    return round(seconds, 1)


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
