"""Strata Rust streams a thinking model's reasoning inside the reply text: split it at the think marks."""
import json
import sys
import unittest
from pathlib import Path

sys.path[:0] = [str(Path(__file__).resolve().parents[1] / 'agent')]

from think_split import ThinkSplit, opens_think  # noqa: E402


def run(chunks, thinking):
    split = ThinkSplit(thinking)
    reasoning = content = ''
    for i, chunk in enumerate(chunks):
        r, c = split.feed(chunk, final=i == len(chunks) - 1)
        reasoning += r
        content += c
    return reasoning, content


class ThinkSplitTests(unittest.TestCase):
    def test_a_prompt_opened_block_ends_at_the_mark_even_when_split_across_chunks(self):
        self.assertEqual(run(['Plan: say hi.\n</th', 'ink>\n\nHo', 'la'], True), ('Plan: say hi.\n', 'Hola'))

    def test_a_block_the_model_opens_itself(self):
        self.assertEqual(run(['  <thi', 'nk>why</think>\n\nanswer'], False), ('why', 'answer'))

    def test_without_marks_everything_is_the_reply(self):
        self.assertEqual(run(['Hola', ', ¿qué tal?'], False), ('', 'Hola, ¿qué tal?'))
        self.assertEqual(run(['<', 'b>bold</b>'], False), ('', '<b>bold</b>'))

    def test_a_reply_cut_while_thinking_stays_reasoning(self):
        self.assertEqual(run(['still thinking </thi'], True), ('still thinking </thi', ''))

    def test_sse_lines_get_their_own_fields(self):
        split = ThinkSplit(True)
        first = json.loads(split.line(b'data: {"choices":[{"delta":{"content":"idea</think>\\n\\nok"}}]}')[6:])
        self.assertEqual(first['choices'][0]['delta'], {'reasoning_content': 'idea', 'content': 'ok'})
        same = b'data: {"choices":[],"usage":{"prompt_tokens":3}}'
        self.assertEqual(split.line(same), same)

    def test_template_check(self):
        qwen = "{%- if add_generation_prompt %}{{- '<|im_start|>assistant\\n' }}{{- '<think>\\n' }}{%- endif %}"
        self.assertTrue(opens_think(qwen))
        self.assertFalse(opens_think("{% if add_generation_prompt %}<|assistant|>{% endif %}"))
        self.assertFalse(opens_think(None))


if __name__ == '__main__':
    unittest.main()
