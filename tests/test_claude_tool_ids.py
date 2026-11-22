"""A history made with a local engine can repeat a tool call id (call_0 on every round); Anthropic refuses a
tool_use id used twice, so the payload gives repeats a suffix and their results follow."""
import sys
import unittest
from pathlib import Path

sys.path[:0] = [str(Path(__file__).resolve().parents[1] / 'agent')]

from remote_protocols import claude_payload  # noqa: E402


def call(ident, name='pc__fs_read'):
    return {'id': ident, 'type': 'function', 'function': {'name': name, 'arguments': '{"path": "a.txt"}'}}


class ClaudeToolIds(unittest.TestCase):
    def test_repeated_ids_become_unique_and_results_follow(self):
        messages = [{'role': 'user', 'content': 'go'},
                    {'role': 'assistant', 'content': '', 'tool_calls': [call('call_0')]},
                    {'role': 'tool', 'tool_call_id': 'call_0', 'content': 'one'},
                    {'role': 'assistant', 'content': '', 'tool_calls': [call('call_0'), call('call_1')]},
                    {'role': 'tool', 'tool_call_id': 'call_0', 'content': 'two'},
                    {'role': 'tool', 'tool_call_id': 'call_1', 'content': 'three'},
                    {'role': 'assistant', 'content': 'done'}]
        body = claude_payload({'model': 'claude', 'messages': messages}, '2023-06-01')
        uses = [b['id'] for m in body['messages'] for b in m['content'] if b['type'] == 'tool_use']
        results = [b['tool_use_id'] for m in body['messages'] for b in m['content'] if b['type'] == 'tool_result']
        self.assertEqual(uses, ['call_0', 'call_0_2', 'call_1'])
        self.assertEqual(results, ['call_0', 'call_0_2', 'call_1'])

    def test_unique_ids_are_unchanged(self):
        messages = [{'role': 'user', 'content': 'go'},
                    {'role': 'assistant', 'content': '', 'tool_calls': [call('toolu_a')]},
                    {'role': 'tool', 'tool_call_id': 'toolu_a', 'content': 'one'}]
        body = claude_payload({'model': 'claude', 'messages': messages}, '2023-06-01')
        self.assertEqual(body['messages'][1]['content'][0]['id'], 'toolu_a')
        self.assertEqual(body['messages'][2]['content'][0]['tool_use_id'], 'toolu_a')


if __name__ == '__main__':
    unittest.main()
