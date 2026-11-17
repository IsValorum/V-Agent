"""The model asks the user a question in the middle of an agentic turn, and waits for the answer.

Offered only to the interface (the request says `ask_user: true`), never to API clients that could not
answer. The turn waits like a tool approval does: until the user answers, lets the agent decide, stops
the reply, or 15 minutes pass (then the agent continues on its own judgment, so an unattended run is
not stuck forever). The tool's text is for the model and stays in English; what the user sees is
translated by the interface.
"""
import re
import threading
import time
import uuid

NAME = 'agent__ask_user'
MAX_PER_TURN = 3
WAIT_SECONDS = 15 * 60
MAX_QUESTION = 600
MAX_OPTION = 120
MAX_ANSWER = 4000

TOOL = {'type': 'function', 'function': {
    'name': NAME,
    'description': (
        'Ask the user one short question and wait for the answer. Use it only when you are blocked by something '
        'only the user can decide or know: a missing requirement, a choice between options with different '
        'results, a preference, or a value you must not guess (a name, a path outside the working folder, an '
        'account). Do not use it to ask permission for tools, to confirm a plan you can simply carry out, or for '
        'anything you can find out with your other tools. When the answer is a choice, give 2-4 short options. '
        'If the user lets you decide, continue with your best judgment and say which assumption you made.'),
    'parameters': {'type': 'object', 'properties': {
        'question': {'type': 'string', 'description': 'The question, in the language the user writes in.'},
        'options': {'type': 'array', 'items': {'type': 'string'}, 'maxItems': 4,
                    'description': 'Optional short answers the user can pick; they can still type another answer.'},
    }, 'required': ['question']},
}}


def clean_args(args):
    """(question, options) from the model's arguments; ValueError with a message for the model."""
    if not isinstance(args, dict):
        raise ValueError('arguments must be an object with "question".')
    question = args.get('question')
    if not isinstance(question, str) or not question.strip():
        raise ValueError('"question" must be a non-empty string.')
    question = ' '.join(question.split())[:MAX_QUESTION] if '\n' not in question.strip() else question.strip()[:MAX_QUESTION]
    options = args.get('options') or []
    if isinstance(options, str):
        options = [options]
    if not isinstance(options, list):
        raise ValueError('"options" must be a list of short strings.')
    seen, cleaned = set(), []
    for option in options:
        text = ' '.join(str(option).split())[:MAX_OPTION]
        if text and text.lower() not in seen:
            seen.add(text.lower())
            cleaned.append(text)
    return question, cleaned[:4]


def result_text(outcome, answer=None):
    """What the model reads back."""
    if outcome == 'answered':
        return 'The user answered: ' + answer
    if outcome == 'skipped':
        return ('The user chose not to answer and lets you decide. Continue with your best judgment and state the '
                'assumption you made in your final reply.')
    if outcome == 'timeout':
        return ('No answer after %d minutes. Continue with your best judgment and state the assumption you made in '
                'your final reply.' % (WAIT_SECONDS // 60))
    return 'error: the question was cancelled because the reply was stopped.'


class Questions:
    """Pending questions, in memory only."""

    def __init__(self):
        self.lock = threading.RLock()
        self.pending = {}

    def create(self, question, options, conversation=None):
        ident = uuid.uuid4().hex
        with self.lock:
            self.pending[ident] = {'event': threading.Event(), 'answer': None, 'skipped': False,
                                   'conversation': conversation}
        return {'type': 'question', 'id': ident, 'question': question, 'options': options}

    def resolve(self, ident, answer=None, skip=False):
        if not isinstance(ident, str) or not re.fullmatch('[a-f0-9]{32}', ident):
            raise ValueError('Invalid question id.')
        if type(skip) is not bool:
            raise ValueError('Invalid answer.')
        if not skip:
            if not isinstance(answer, str) or not answer.strip():
                raise ValueError('Write an answer or let the agent decide.')
            answer = answer.strip()[:MAX_ANSWER]
        with self.lock:
            item = self.pending.get(ident)
            if item is None:
                raise ValueError('This question is no longer waiting for an answer.')
            item['answer'], item['skipped'] = (None, True) if skip else (answer, False)
            item['event'].set()

    def wait(self, ident, cancel, timeout=WAIT_SECONDS):
        """('answered', text) | ('skipped', None) | ('timeout', None) | ('cancelled', None)."""
        with self.lock:
            item = self.pending[ident]
        try:
            deadline = time.monotonic() + timeout
            while not item['event'].wait(.1):
                if cancel.is_set():
                    return 'cancelled', None
                if time.monotonic() > deadline:
                    return 'timeout', None
            if cancel.is_set():
                return 'cancelled', None
            return ('skipped', None) if item['skipped'] else ('answered', item['answer'])
        finally:
            with self.lock:
                self.pending.pop(ident, None)


QUESTIONS = Questions()
