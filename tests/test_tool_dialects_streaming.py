"""Every tool-call dialect, fed whole and in small pieces, gives the same calls and no leftover markup."""
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'agent'))
sys.path.insert(0, str(ROOT))

from serve.frontend import OutputParser
import engine_options
import templates

TOOL = {'name': 'read', 'description': 'Read a file.',
        'parameters': {'type': 'object', 'properties': {'path': {'type': 'string'}, 'lines': {'type': 'integer'}}}}
ARGS = {'path': 'a.txt', 'lines': 3}

# (call_format, thinking, reply text) for each dialect the parser knows
CASES = [
    ('function', False, '<tool_call>\n<function=read>\n<parameter=path>\na.txt\n</parameter>\n'
                        '<parameter=lines>\n3\n</parameter>\n</function>\n</tool_call>'),
    ('inkling2', False, '<|message_model|>read<|content_invoke_tool_json|>{"name":"read","args":{"path":"a.txt","lines":3}}<|end_message|>'),
    ('mistral', False, '[TOOL_CALLS][{"name":"read","arguments":{"path":"a.txt","lines":3}}]'),
    ('mistral', False, '[TOOL_CALLS]read[ARGS]{"path":"a.txt","lines":3}'),
    ('llama3', False, '<|python_tag|>{"name":"read","parameters":{"path":"a.txt","lines":3}}<|eom_id|>'),
    ('kimi', False, '<|tool_calls_section_begin|><|tool_call_begin|>functions.read:0<|tool_call_argument_begin|>'
                    '{"path":"a.txt","lines":3}<|tool_call_end|><|tool_calls_section_end|>'),
    ('minimax', False, '<minimax:tool_call><invoke name="read"><parameter name="path">a.txt</parameter>'
                       '<parameter name="lines">3</parameter></invoke></minimax:tool_call>'),
    ('harmony', True, '<|channel|>analysis<|message|>checking<|end|><|start|>assistant<|channel|>commentary '
                      'to=functions.read <|constrain|>json<|message|>{"path":"a.txt","lines":3}<|call|>'),
]
MARKUP = ('<|', '|>', '[TOOL_CALLS]', '[ARGS]', '<invoke', '</invoke', 'minimax:', '<tool_call')


def run(fmt, thinking, text, step):
    parser = OutputParser(thinking=thinking, tools=[TOOL], stream_tools=True, call_format=fmt)
    events = []
    for i in range(0, len(text), step):
        events += parser.feed(text[i:i + step])
    events += parser.finish()
    calls = [(e.call.name, e.call.arguments) for e in events if e.kind == 'tool_call' and e.call]
    shown = ''.join(e.text for e in events if e.kind == 'content')
    return calls, shown


class DialectStreamingTests(unittest.TestCase):
    def test_each_dialect_whole_and_in_pieces(self):
        for fmt, thinking, text in CASES:
            for step in (len(text), 7, 3, 1):
                with self.subTest(fmt=fmt, step=step, text=text[:30]):
                    calls, shown = run(fmt, thinking, text, step)
                    self.assertEqual(calls, [('read', ARGS)])
                    self.assertFalse(any(tag in shown for tag in MARKUP), shown)

    def test_text_before_a_call_is_kept(self):
        for fmt, thinking, text in CASES:
            if thinking:
                continue
            with self.subTest(fmt=fmt):
                calls, shown = run(fmt, False, 'Reading it now. ' + text, 5)
                self.assertEqual(calls, [('read', ARGS)])
                self.assertEqual(shown.strip(), 'Reading it now.')


class DialectDetectionAndHintsTests(unittest.TestCase):
    MARKERS = {'inkling2': '<|content_invoke_tool_json|>', 'kimi': '<|tool_call_begin|><|tool_call_argument_begin|>',
               'minimax': '<minimax:tool_call>', 'harmony': '<|channel|>commentary to=', 'mistral': '[TOOL_CALLS]',
               'llama3': '<|python_tag|>'}

    def test_template_detection_and_own_syntax_hint(self):
        import agent as agent_module
        for fmt, marker in self.MARKERS.items():
            with self.subTest(fmt=fmt), tempfile.TemporaryDirectory() as folder:
                (Path(folder) / templates.FICHERO).write_text('{{ messages }}' + marker, encoding='utf-8')
                self.assertEqual(templates.formato_llamada(folder), fmt)
                hint = agent_module._formato_esperado(folder)
                self.assertNotIn('"arguments":{"argument":"value"}}\n', hint)   # not the generic JSON example
                self.assertIn('tool_name', hint)


HELP_LLAMA = """\
-t,    --threads N                      number of threads
-ctk,  --cache-type-k TYPE              KV cache data type for K
                                        allowed values: f32, f16, bf16, q8_0, q4_0
--list-devices                          print list of available devices and exit
--api-key KEY                           API key to use for authentication
--allow-unauthenticated-tools           let anyone call server tools
--skip-chat-parsing                     return raw text
--gpt-oss-20b-default                   download and use gpt-oss-20b
--slot-save-path PATH                   path to save slot kv cache
--cors-origins ORIGINS                  allowed origins
--poll <0...100>                        polling level
--perf, --no-perf                       internal timings
"""
HELP_RUST = """\
      --preserve-thinking [<PRESERVE_THINKING>]
          Keep the think block of earlier replies [possible values: true, false]
      --kv <KV>
          KV cache format [default: f16] [possible values: f16, q8]
      --api-key <KEY>
          Key clients must send
"""


class ExtraOptionsTests(unittest.TestCase):
    def test_only_safe_new_flags_are_offered(self):
        llama = {o['flag'] for o in engine_options.discover_extra_options('llama', HELP_LLAMA)}
        self.assertEqual(llama, {'--poll', '--perf'})
        rust = engine_options.discover_extra_options('rust', HELP_RUST)
        self.assertEqual([(o['flag'], o['kind']) for o in rust], [('--preserve-thinking', 'bool')])

    def test_extra_values_are_checked_and_passed_as_one_argument(self):
        with self.assertRaises(ValueError):
            engine_options.validate({'flag__poll': '50; del x'})
        saved = engine_options.validate({'flag__poll': '50', 'flag__perf': True})
        self.assertEqual(engine_options.arguments('llama', saved, HELP_LLAMA), ['--poll', '50', '--perf'])
        # a flag the installed engine no longer lists is not passed
        self.assertEqual(engine_options.arguments('llama', {'flag__gone': True}, HELP_LLAMA), [])


class TextRecoveryTests(unittest.TestCase):
    """A call another template writes, left as text by llama.cpp or an API, still runs; examples do not."""
    ALLOWED = {'read': TOOL['parameters']}

    def test_each_dialect_left_as_text_is_recovered(self):
        from tool_markup import recover_text_calls
        for fmt, thinking, text in CASES:
            if fmt == 'function':
                continue
            with self.subTest(fmt=fmt, text=text[:30]):
                calls, clean, attempted = recover_text_calls('Reading it. ' + text, self.ALLOWED)
                self.assertTrue(attempted)
                self.assertEqual([(c['name'], c['parsed_args']) for c in calls], [('read', ARGS)])
                self.assertFalse(any(tag in clean for tag in MARKUP), clean)

    def test_examples_and_unknown_tools_are_not_run(self):
        from tool_markup import recover_text_calls
        fenced = 'Like this:\n```\n[TOOL_CALLS][{"name":"read","arguments":{"path":"x"}}]\n```\nDone.'
        calls, clean, _ = recover_text_calls(fenced, self.ALLOWED)
        self.assertEqual((calls, clean), ([], fenced))
        inline = 'Write `<|python_tag|>{"name":"read","parameters":{}}` to call it.'
        self.assertEqual(recover_text_calls(inline, self.ALLOWED)[:2], ([], inline))
        unknown = '<|channel|>commentary to=functions.erase <|constrain|>json<|message|>{"all":true}<|call|>'
        self.assertEqual(recover_text_calls(unknown, self.ALLOWED)[0], [])


class ExtraOptionKindsTests(unittest.TestCase):
    HELP = """--poll <0...100>                        polling level (default: 50)
--cpu-strict <0|1>                      strict placement
--rope-scale N                          RoPE context scaling factor
--keep N                                tokens to keep (default: 0)
      --mode <MODE>
          How to run [default: fast] [possible values: fast, small]
"""

    def test_kinds_and_values(self):
        found = {o['flag']: o for o in engine_options.discover_extra_options('llama', self.HELP)}
        self.assertEqual((found['--poll']['kind'], found['--poll']['min'], found['--poll']['max']), ('int', 0, 100))
        self.assertEqual(found['--cpu-strict']['choices'], ['0', '1'])
        self.assertEqual(found['--rope-scale']['kind'], 'float')
        self.assertEqual(found['--keep']['kind'], 'int')
        self.assertEqual(found['--mode']['choices'], ['fast', 'small'])
        saved = engine_options.validate({'flag__poll': 101, 'flag__rope_scale': 2.5, 'flag__cpu_strict': '2',
                                         'flag__keep': 8, 'flag__mode': 'small'})
        # out of range and unlisted values are left out, the rest pass as one argument each
        self.assertEqual(engine_options.arguments('llama', saved, self.HELP),
                         ['--rope-scale', '2.5', '--keep', '8', '--mode', 'small'])


if __name__ == '__main__':
    unittest.main()
