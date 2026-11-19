"""Regressions from 2026-11-19: OpenCode plan endpoints, and engine updates without cached release info."""
import sys
import threading
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'agent'))

import engine_updates  # noqa: E402
from remote_protocols import opencode_inference_url, resolve_auth_mode  # noqa: E402


class OpenCodeEndpoints(unittest.TestCase):
    def test_current_inference_bases_use_per_protocol_paths(self):
        go = 'https://opencode.ai/inference/go'
        self.assertEqual(opencode_inference_url(go, '/chat/completions', 'opencode'),
                         'https://opencode.ai/inference/go/openai/v1/chat/completions')
        self.assertEqual(opencode_inference_url(go, '/messages', 'opencode'),
                         'https://opencode.ai/inference/go/anthropic/v1/messages')
        self.assertEqual(opencode_inference_url(go, '/models?after=x', 'opencode'),
                         'https://opencode.ai/inference/go/v1/models?after=x')
        self.assertEqual(opencode_inference_url('https://opencode.ai/inference', '/chat/completions', 'opencode'),
                         'https://opencode.ai/inference/openai/v1/chat/completions')

    def test_legacy_bases_and_other_providers_are_untouched(self):
        self.assertIsNone(opencode_inference_url('https://opencode.ai/zen/go/v1', '/chat/completions', 'opencode'))
        self.assertIsNone(opencode_inference_url('https://opencode.ai/zen/v1', '/models', 'opencode'))
        self.assertIsNone(opencode_inference_url('https://example.com/inference', '/models', 'openai'))

    def test_opencode_uses_bearer_even_for_the_anthropic_protocol(self):
        self.assertEqual(resolve_auth_mode({'protocol': 'anthropic'}, 'opencode'), 'bearer')
        self.assertEqual(resolve_auth_mode({'protocol': 'anthropic'}, 'anthropic'), 'x-api-key')
        self.assertEqual(resolve_auth_mode({'protocol': 'anthropic', 'auth_mode': 'x-api-key'}, 'opencode'), 'x-api-key')


class EngineInstallWithoutReleaseInfo(unittest.TestCase):
    def make(self, found):
        updates = object.__new__(engine_updates.Updates)
        updates.lock = threading.RLock()
        updates.busy = False
        updates.installing = False
        updates.progress = None
        updates.state = {'checked_at': 0, 'releases': {}}
        calls = []

        def check(force=False):
            calls.append(force)
            updates.state['releases']['llama-cpu'] = found
            return {}
        updates.check = check
        return updates, calls

    def test_install_checks_first_and_reports_the_feed_error(self):
        updates, calls = self.make({'error': 'GitHub no respondió.'})
        with self.assertRaisesRegex(ValueError, 'GitHub no respondió'):
            updates.install('llama-cpu')
        self.assertEqual(calls, [True])

    def test_install_without_any_release_explains_it(self):
        updates, calls = self.make({})
        with self.assertRaisesRegex(ValueError, 'No se encontró una versión publicada'):
            updates.install('llama-cpu')
        self.assertEqual(calls, [True])


if __name__ == '__main__':
    unittest.main()
