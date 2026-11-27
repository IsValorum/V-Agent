"""Every figure shown comes from the engine or the provider (2026-11-19): none is computed from text sizes."""
import json
import sys
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'agent'))

import engine_manager  # noqa: E402
from engine_manager import EngineManager  # noqa: E402


def manager(kind, live=False):
    m = EngineManager.__new__(EngineManager)
    m.kind, m.loaded, m.live, m.loaded_context, m.llama_key = kind, kind + '--model', live, 8192, 'k'
    m.last_usage, m.last_timing, m.settings = {}, {}, {'api': {}}
    return m


# GET /api/stats of Strata Rust v1.2.1 (field names as served by the engine).
RUST_STATS = {'backend': 'cuda', 'busy': 1, 'ctx': 32768, 'live_tokens': 37, 'loading': False, 'model': 'qwen',
              'recent': [{'prompt_tokens': 3000, 'cached_tokens': 2000, 'completion_tokens': 401, 'system_tokens': 900,
                          'prefill_ms': 500.0, 'decode_ms': 8000.0, 'finish': 'stop', 'at': 1}]}


class StrataRust(unittest.TestCase):
    def test_live_tokens_and_exact_last_request_come_from_its_stats(self):
        m = manager('rust', live=True)
        with patch.object(EngineManager, '_engine_json', return_value=RUST_STATS):
            result = m.metrics()
        self.assertEqual(result['live']['state'], 'generating')
        self.assertEqual(result['live']['generated'], 37)
        self.assertIsNone(result['live']['prompt_tokens'])          # counted by the engine only at the end
        self.assertEqual(result['engine']['max_context'], 32768)
        self.assertEqual(result['requests'], [{'prompt_tokens': 3000, 'output_tokens': 401}])
        self.assertEqual(result['last'], {'decode': 50.0, 'prefill': 2000.0})   # (401-1)/8 s, 1000/0.5 s

    def test_reading_before_the_first_token(self):
        m = manager('rust', live=True)
        with patch.object(EngineManager, '_engine_json', return_value={**RUST_STATS, 'live_tokens': 0}):
            self.assertEqual(m.metrics()['live']['state'], 'reading')

    def test_the_usage_line_carries_the_engine_clocks(self):
        m = manager('rust')
        packet = {'choices': [], 'usage': {'prompt_tokens': 3000, 'completion_tokens': 401}}
        with patch.object(EngineManager, '_engine_json', return_value=RUST_STATS):
            line = m._with_engine_timings(packet)
        timings = json.loads(line[6:])['timings']
        self.assertEqual((timings['predicted_per_second'], timings['prompt_per_second'], timings['cache_n']), (50.0, 2000.0, 2000))


class ProjectMaya(unittest.TestCase):
    def test_its_metrics_are_passed_through(self):
        data = {'engine': {'max_context': 65536}, 'live': {'state': 'generating', 'prompt_tokens': 5000, 'generated': 12,
                                                           'tok_s': 21.5, 'prefill_tok_s_mean': 900.0},
                'requests': [{'prompt_tokens': 4000, 'output_tokens': 300, 'decode_tok_s': 22.0, 'prefill_tok_s': 850.0}]}
        m = manager('maya', live=True)
        with patch.object(EngineManager, '_engine_json', return_value=data):
            result = m.metrics()
        self.assertEqual((result['live']['prompt_tokens'], result['live']['tok_s'], result['live']['prefill']), (5000, 21.5, 900.0))
        self.assertEqual(result['last'], {'decode': 22.0, 'prefill': 850.0})


class ProviderApi(unittest.TestCase):
    def test_no_invented_counts_while_a_provider_streams(self):
        m = manager('api', live=True)
        m.selected_remote = lambda: {'context': 128000}
        m.live_usage, m.last_usage = {}, {'prompt_tokens': 9000, 'completion_tokens': 300}
        live = m.metrics()['live']
        self.assertIsNone(live['prompt_tokens'])
        self.assertIsNone(live['generated'])
        self.assertIsNone(live['tok_s'])

    def test_claude_reports_its_input_at_the_start(self):
        m = manager('api', live=True)
        m.selected_remote = lambda: {'context': 200000}
        m.live_usage = {'prompt_tokens': 15234}
        self.assertEqual(m.metrics()['live']['prompt_tokens'], 15234)


class ContextMeter(unittest.TestCase):
    def test_an_unreported_live_prompt_shows_the_last_measure(self):
        import agent
        usage = agent.context_usage({'engine': {'max_context': 8192},
                                     'live': {'state': 'generating', 'prompt_tokens': None, 'generated': 10},
                                     'requests': [{'prompt_tokens': 3000, 'output_tokens': 400}]}, True)
        self.assertEqual((usage['used'], usage['source']), (3400, 'last'))


class LlamaStream(unittest.TestCase):
    def test_live_timings_feed_the_meters_and_only_the_final_one_is_passed_on(self):
        chunks = [
            {'choices': [{'delta': {'role': 'assistant', 'content': None}}], 'timings': {'prompt_n': 0, 'cache_n': 0, 'predicted_n': 0},
             'prompt_progress': {'total': 381, 'cache': 0, 'processed': 8, 'time_ms': 50}},
            {'choices': [{'delta': {'content': 'Hi'}}], 'timings': {'prompt_n': 381, 'cache_n': 0, 'predicted_n': 5, 'predicted_per_second': 120.0}},
            {'choices': [{'delta': {}, 'finish_reason': 'stop'}]},
            {'choices': [], 'usage': {'prompt_tokens': 381, 'completion_tokens': 5},
             'timings': {'prompt_n': 381, 'cache_n': 0, 'predicted_n': 5, 'predicted_per_second': 118.0, 'prompt_per_second': 1100.0}},
        ]
        lines = [('data: ' + json.dumps(c)).encode() for c in chunks] + [b'data: [DONE]']

        class Response:
            status = 200
            fp = None
            def getheader(self, *a): return None

        class Connection:
            sock = object()
            def connect(self): pass
            def request(self, *a): self.sent = json.loads(a[2])
            def getresponse(self): return Response()
            def close(self): pass

        class Control:
            cancelled = threading.Event()
            def attach(self, c): pass
            def detach(self, c): pass

        m = manager('llama')
        m.base = lambda: 'http://127.0.0.1:19383/v1'
        m.headers = lambda **k: {}
        m.selected_remote = lambda: None
        connection = Connection()
        seen = []

        def lines_with_metrics(_response):
            for line in lines:
                yield line
                seen.append(m.metrics()['live'])
        with patch('engine_manager.http.client.HTTPConnection', return_value=connection), \
                patch('engine_manager.iter_http_lines', side_effect=lines_with_metrics), \
                patch('engine_manager.urllib.request.urlopen', side_effect=OSError):
            out = list(m.stream({'model': 'm', 'stream': True, 'messages': [{'role': 'user', 'content': 'hi'}]}, Control()))
        self.assertTrue(connection.sent['timings_per_token'] and connection.sent['return_progress'])
        self.assertEqual((seen[0]['state'], seen[0]['prompt_read'], seen[0]['prompt_total']), ('reading', 8, 381))
        self.assertEqual((seen[1]['generated'], seen[1]['tok_s']), (5, 120.0))
        self.assertEqual(sum(b'"timings"' in line for line in out), 1)
        self.assertEqual(m.metrics()['last'], {'decode': 118.0, 'prefill': 1100.0})

    def test_rust_live_prompt_tokens_use_full_engine_count_only(self):
        import agent
        rust = manager('rust', live=True)
        rust.loaded_context = 32768
        rust.live_prompt_tokens = 2048
        with patch.object(EngineManager, '_engine_json', return_value={'busy': True, 'live_tokens': 37, 'ctx': 32768, 'recent': []}):
            u = agent.context_usage(rust.metrics(), True)
        self.assertEqual((u['prompt_tokens'], u['completion_tokens'], u['used'], u['source']), (2048, 37, 2085, 'live'))

        # When idle, live_prompt_tokens is never reported as live.
        with patch.object(EngineManager, '_engine_json', return_value={'busy': False, 'live_tokens': 0, 'ctx': 32768, 'recent': []}):
            u_idle = agent.context_usage(rust.metrics(), True)
        self.assertIsNone(u_idle['used'])

        # Without an engine count, Strata Rust never invents a prompt token count.
        rust.live_prompt_tokens = None
        with patch.object(EngineManager, '_engine_json', return_value={'busy': True, 'live_tokens': 37, 'ctx': 32768, 'recent': []}):
            u_none = agent.context_usage(rust.metrics(), True)
        self.assertIsNone(u_none['used'])

        # count_prompt_tokens on Strata Rust preserves system prompt and tool messages (never drops them).
        captured = {}
        def fake_json(path, body=None, timeout=15):
            captured['path'] = path; captured['body'] = body
            return {'input_tokens': 1234}
        with patch.object(EngineManager, '_engine_json', side_effect=fake_json):
            n = rust.count_prompt_tokens([
                {'role': 'system', 'content': 'Be helpful.'},
                {'role': 'user', 'content': 'Check files'},
                {'role': 'assistant', 'content': '', 'tool_calls': [{'id': 'c1', 'type': 'function', 'function': {'name': 'fs_list', 'arguments': '{}'}}]},
                {'role': 'tool', 'tool_call_id': 'c1', 'content': 'a.txt'},
            ])
        self.assertEqual(n, 1234)
        self.assertEqual(captured['path'], '/v1/messages/count_tokens')
        self.assertIn('system', captured['body'])
        self.assertTrue(any(isinstance(b, dict) and b.get('type') == 'tool_result' for m in captured['body']['messages'] for b in m['content']))


if __name__ == '__main__':
    unittest.main()
