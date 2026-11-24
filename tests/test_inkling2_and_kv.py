import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'agent'))
sys.path.insert(0, str(ROOT / 'tools'))
sys.path.insert(0, str(ROOT))

from serve.frontend import OutputParser
import templates
import engine_options
import kv_settings
import memory_estimate


class Inkling2AndKVTests(unittest.TestCase):
    def test_inkling2_parser_thinking_content_and_tool_call_streaming(self):
        tool = {'name': 'pc__fs_write', 'parameters': {'type': 'object', 'properties': {'path': {'type': 'string'}, 'content': {'type': 'string'}}}}
        raw = (
            '<|message_model|><|content_thinking|>Let me check the file.<|end_message|>'
            '<|message_model|><|content_text|>Sure, writing now.<|end_message|>'
            '<|message_model|>pc__fs_write<|content_invoke_tool_json|>'
            '{"name":"pc__fs_write","args":{"path":"demo.txt","content":"line1\\n<|end_message|>\\nline2"}}'
            '<|end_message|><|content_model_end_sampling|>'
        )
        parser = OutputParser(thinking=True, tools=[tool], stream_tools=True, call_format='inkling2')
        events = []
        for i in range(0, len(raw), 7):
            events.extend(parser.feed(raw[i:i + 7]))
        events.extend(parser.finish('stop'))

        reasoning = ''.join(e.text for e in events if e.kind == 'reasoning')
        content = ''.join(e.text for e in events if e.kind == 'content')
        calls = [e.call for e in events if e.kind == 'tool_call']

        self.assertEqual(reasoning, 'Let me check the file.')
        self.assertEqual(content, 'Sure, writing now.')
        self.assertNotIn('pc__fs_write', content)
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0].name, 'pc__fs_write')
        self.assertEqual(calls[0].arguments, {'path': 'demo.txt', 'content': 'line1\n<|end_message|>\nline2'})

    def test_formato_llamada_detects_inkling2(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)
            (p / 'chat_template.jinja').write_text('{{- "<|message_model|>" ~ fn.name ~ "<|content_invoke_tool_json|>" -}}', encoding='utf-8')
            self.assertEqual(templates.formato_llamada(p, native=True), 'inkling2')

    def test_engine_options_arch_filtering(self):
        help_txt = '--kv-resident N --attn-requant TYPE --loop-bf16 --no-loop-bf16 --cache-bias F'
        vals = {'kv_resident': 64, 'attn_requant': 'q5_0', 'loop_bf16': True, 'cache_bias': 0.5}
        inkling_args = engine_options.arguments('strata', vals, help_txt, arch='inkling2_loop')
        self.assertIn('--kv-resident', inkling_args)
        self.assertIn('--attn-requant', inkling_args)
        self.assertIn('--loop-bf16', inkling_args)
        self.assertIn('--cache-bias', inkling_args)

        gemma_args = engine_options.arguments('strata', vals, help_txt, arch='gemma4')
        self.assertIn('--kv-resident', gemma_args)
        self.assertNotIn('--attn-requant', gemma_args)
        self.assertNotIn('--loop-bf16', gemma_args)
        self.assertNotIn('--cache-bias', gemma_args)

    def test_kv_settings_inkling2_and_memory_estimate_fp8(self):
        self.assertIn('fp8', memory_estimate._KV_BPE)
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            gguf = d / 'model.gguf'
            gguf.write_bytes(b'GGUF')
            exe = d / 'strata-poly.exe'
            exe.write_bytes(b'MZ')
            cfg = d / 'strata-test.json'
            cfg.write_text('{"exe": "' + str(exe).replace('\\', '\\\\') + '", "_val_managed_engine": true, "args": ["--model", "' + str(gguf).replace('\\', '\\\\') + '", "--kv", "fp16"]}', encoding='utf-8')
            with mock.patch.object(kv_settings, '_shape', return_value=('inkling2_loop', [128, None])), \
                 mock.patch.object(engine_options, 'help_text', return_value='--kv fmt fp16 q8_0 q4_0 fp8'):
                info = kv_settings.describe(cfg)
            self.assertEqual(info['architecture'], 'inkling2_loop')
            self.assertEqual([o['value'] for o in info['options']], ['fp16', 'q8_0', 'fp8', 'q4_0'])

    def test_all_new_tool_call_dialects(self):
        tool = {'name': 'pc__fs_read', 'parameters': {'type': 'object', 'properties': {'path': {'type': 'string'}, 'lines': {'type': 'integer'}}}}
        cases = [
            ('mistral', '[TOOL_CALLS] [{"name":"pc__fs_read","arguments":{"path":"a.txt","lines":10}}]', 'pc__fs_read', {'path': 'a.txt', 'lines': 10}),
            ('mistral', '[TOOL_CALLS]pc__fs_read[ARGS]{"path":"b.txt","lines":5}', 'pc__fs_read', {'path': 'b.txt', 'lines': 5}),
            ('llama3', '<|python_tag|>{"name":"pc__fs_read","parameters":{"path":"c.txt","lines":3}}<|eom_id|>', 'pc__fs_read', {'path': 'c.txt', 'lines': 3}),
            ('kimi', '<|tool_calls_section_begin|><|tool_call_begin|>functions.pc__fs_read:0<|tool_call_argument_begin|>{"path":"d.txt","lines":7}<|tool_call_end|><|tool_calls_section_end|>', 'pc__fs_read', {'path': 'd.txt', 'lines': 7}),
            ('minimax', '<minimax:tool_call><invoke name="pc__fs_read"><parameter name="path">e.txt</parameter><parameter name="lines">9</parameter></invoke></minimax:tool_call>', 'pc__fs_read', {'path': 'e.txt', 'lines': 9}),
            ('harmony', '<|channel|>commentary to=functions.pc__fs_read <|constrain|>json<|message|>{"path":"f.txt","lines":2}<|call|>', 'pc__fs_read', {'path': 'f.txt', 'lines': 2}),
        ]
        for dialect, payload, expected_name, expected_args in cases:
            with self.subTest(dialect=dialect):
                parser = OutputParser(thinking=False, tools=[tool], stream_tools=True, call_format=dialect)
                events = []
                for i in range(0, len(payload), 9):
                    events.extend(parser.feed(payload[i:i + 9]))
                events.extend(parser.finish('stop'))
                calls = [e.call for e in events if e.kind == 'tool_call']
                self.assertEqual(len(calls), 1)
                self.assertEqual(calls[0].name, expected_name)
                self.assertEqual(calls[0].arguments, expected_args)

    def test_dynamic_kv_and_extra_options_discovery(self):
        fake_help = '  --future-turbo-mode   Enable next-gen acceleration\n  --future-cache-mb N   Extra cache in MB\n'
        extras = engine_options.discover_extra_options('strata', fake_help)
        keys = [e['key'] for e in extras]
        self.assertIn('flag__future_turbo_mode', keys)
        self.assertIn('flag__future_cache_mb', keys)
        validated = engine_options.validate({'flag__future_turbo_mode': True, 'flag__future_cache_mb': '256'})
        argv = engine_options.arguments('strata', validated, fake_help)
        self.assertEqual(argv, ['--future-turbo-mode', '--future-cache-mb', '256'])


if __name__ == '__main__':
    unittest.main()
