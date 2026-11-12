"""Strata Rust lists a model before loading it: "ready" must mean really loaded (WinError 10061 otherwise)."""
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path[:0] = ['agent', '.', 'tools']
import engine_manager


class RustReadinessTests(unittest.TestCase):
    def manager(self, kind):
        m = engine_manager.EngineManager.__new__(engine_manager.EngineManager)
        m.kind, m.llama_key, m.settings = kind, 'k', {}
        return m

    def test_rust_is_ready_only_after_it_says_loaded(self):
        with tempfile.TemporaryDirectory() as folder:
            log = Path(folder) / 'llama-server.log'
            log.write_text('old session\nloaded Something-Else\n', encoding='utf-8')
            start = log.stat().st_size
            m = self.manager('rust')
            with log.open('a', encoding='utf-8') as out:
                out.write('listening on http://127.0.0.1:19383/\nloading model.gguf\n')
            self.assertFalse(m._ready(log, start))  # an earlier session's "loaded" does not count
            with log.open('a', encoding='utf-8') as out:
                out.write('chat template: Xml\nloaded Qwen3.8\n')
            self.assertTrue(m._ready(log, start))

    def test_failures_say_which_engine_and_why(self):
        text = engine_manager.load_failure('Strata Rust', "Error: unsupported architecture 'gemma4' (supported: qwen3, qwen35moe)")
        self.assertIn('Strata Rust no ejecuta modelos de arquitectura «gemma4»', text)
        self.assertIn('qwen35moe', text)
        self.assertTrue(engine_manager.load_failure('Strata Rust', 'boom').startswith('Strata Rust no pudo cargar'))

    def test_rust_gets_the_private_key(self):
        self.assertEqual(self.manager('rust').headers().get('Authorization'), 'Bearer k')
        source = Path('agent/engine_manager.py').read_text(encoding='utf-8')
        self.assertIn("'STRATA_API_KEY':self.llama_key", source)


class LiveNumbersTests(unittest.TestCase):
    def test_speeds_are_measured_for_engines_that_only_count_tokens(self):
        t = engine_manager.measured_timings({'prompt_tokens': 1200, 'completion_tokens': 101,
                                             'prompt_tokens_details': {'cached_tokens': 1000}}, 0, 0.5, 2.5)
        self.assertEqual((t['prompt_per_second'], t['predicted_per_second'], t['cache_n']), (400.0, 50.0, 1000))
        cached = engine_manager.measured_timings({'prompt_tokens': 1200, 'completion_tokens': 50,
                                                  'prompt_tokens_details': {'cached_tokens': 1198}}, 0, .05, 1.05)
        self.assertNotIn('prompt_per_second', cached)  # 2 new tokens: no meaningful reading speed

    def test_rust_reports_the_reply_in_progress_not_the_previous_one(self):
        m = engine_manager.EngineManager.__new__(engine_manager.EngineManager)
        m.kind, m.loaded, m.live, m.loaded_context = 'rust', 'rust--x', True, 8192
        m.last_usage = {'prompt_tokens': 3000, 'completion_tokens': 400}
        m.live_prompt, m.live_generated = 3400, 37
        live = m.metrics()
        self.assertEqual((live['live']['prompt_tokens'], live['live']['generated'], live['engine']['max_context']), (3400, 37, 8192))


class LoadFailureTests(unittest.TestCase):
    def test_the_real_reason_is_shown_not_the_whole_log(self):
        log = '\n'.join(['0.00.90 I srv init',
                         "0.01.06 E llama_model_load: error loading model: check_tensor_dims: tensor 'token_embd.weight' has wrong shape",
                         '0.01.07 E failed to load model', ''])
        text = engine_manager.load_failure('llama.cpp', log)
        self.assertIn("tensor 'token_embd.weight' has wrong shape", text)
        self.assertNotIn('srv init', text)
        self.assertIn('sin memoria', engine_manager.load_failure('llama.cpp', 'cudaMalloc failed: out of memory'))
        broke = engine_manager.load_failure('llama.cpp', '\n'.join(['0.1 I ok', '0.2 E llama: something broke', '']))
        self.assertIn('something broke', broke)
        self.assertNotIn('I ok', broke)


class PreferencesAcrossEnginesTests(unittest.TestCase):
    def test_the_same_file_keeps_its_settings_under_another_engine(self):
        import json, model_preferences
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'prefs.json'
            path.write_text(json.dumps({'llama--local-abc': {'effort': 'none', 'context': 8192, 'kv': 'q8_0',
                                                             'sampling': {'temperature': 0.3}}}), encoding='utf-8')
            prefs = model_preferences.ModelPreferences(path)
            base = {'sampling': {'temperature': 0.7}, 'effort': 'think', 'rounds': 10}
            inherited = prefs.get('rust--local-abc', base)
            self.assertEqual((inherited['effort'], inherited['context'], inherited['sampling']['temperature']), ('none', 8192, 0.3))
            self.assertNotIn('kv', inherited)  # engine-specific: not carried over
            self.assertEqual(prefs.get('rust--local-other', base)['effort'], 'think')


if __name__ == '__main__':
    unittest.main()
