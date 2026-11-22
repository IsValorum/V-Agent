"""Issue #2: a local engine reuses the prompt it already read only up to the first change. What changes from
turn to turn must not rewrite the system prompt or, on every tool round, a message in the middle."""
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path[:0] = [str(Path(__file__).resolve().parents[1] / 'agent'), str(Path(__file__).resolve().parents[1] / 'tools')]

from context_policy import project_messages  # noqa: E402


class Workspace:
    def __init__(self, root):
        self.root = Path(root)

    def path(self, relative):
        return self.root / relative


def history(batches):
    messages = [{'role': 'system', 'content': 'rules'}, {'role': 'user', 'content': 'go'}]
    for n in range(batches):
        messages.append({'role': 'assistant', 'content': '', 'tool_calls': [{'id': f'c{n}', 'type': 'function',
                         'function': {'name': 'pc__fs_read', 'arguments': json.dumps({'path': f'f{n}.txt'})}}]})
        messages.append({'role': 'tool', 'tool_call_id': f'c{n}', 'content': 'x' * 5000})
    return messages


class ArchiveInBlocks(unittest.TestCase):
    def archived(self, messages, **kw):
        with tempfile.TemporaryDirectory() as folder:
            out, _ = project_messages(messages, Workspace(folder), **kw)
        return sum('[Archived tool data' in str(m.get('content')) for m in out)

    def test_one_batch_at_a_time_without_blocks(self):
        self.assertEqual([self.archived(history(n)) for n in (5, 6, 7)], [1, 2, 3])

    def test_blocks_rewrite_the_history_once_every_eight_batches(self):
        counts = [self.archived(history(n), block=8) for n in range(4, 22)]
        self.assertEqual(counts, [0] * 8 + [8] * 8 + [16] * 2)

    def test_the_prefix_stays_identical_between_rounds_inside_a_block(self):
        with tempfile.TemporaryDirectory() as folder:
            a, _ = project_messages(history(13), Workspace(folder), block=8)
            b, _ = project_messages(history(14), Workspace(folder), block=8)
        self.assertEqual(a, b[:len(a)])


class TurnNotes(unittest.TestCase):
    def setUp(self):
        import agent
        self.attach = agent.attach_turn_note

    def test_the_note_goes_on_the_latest_user_message_not_the_system_prompt(self):
        messages = [{'role': 'system', 'content': 'rules'}, {'role': 'user', 'content': 'first'},
                    {'role': 'assistant', 'content': 'ok'}, {'role': 'user', 'content': 'second'}]
        out = self.attach(messages, 'Recovery state: draft available')
        self.assertEqual(out[:3], messages[:3])
        self.assertEqual(out[3]['content'], 'second\n\n[Recovery state: draft available]')
        self.assertEqual(messages[3]['content'], 'second')  # the caller's list is not changed

    def test_image_messages_and_empty_histories(self):
        out = self.attach([{'role': 'user', 'content': [{'type': 'text', 'text': 'look'}]}], 'note')
        self.assertEqual(out[0]['content'][-1], {'type': 'text', 'text': '[note]'})
        self.assertEqual(self.attach([], 'note'), [{'role': 'user', 'content': '[note]'}])


if __name__ == '__main__':
    unittest.main()
