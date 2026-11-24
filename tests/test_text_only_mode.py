"""The "Chat" agent mode (profile "text") offers web search and page reading, and nothing else."""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'agent'))
sys.path.insert(0, str(ROOT))

import agent_profiles

EVERYTHING = {'web_search', 'web_visit', 'fs_list', 'fs_read', 'fs_write', 'shell_run', 'sys_info', 'browser', 'console',
              'http_request', 'download', 'hf_cli', 'screen_capture', 'run'}


class TextOnlyModeTests(unittest.TestCase):
    def test_only_the_two_web_tools(self):
        for full in (False, True):
            with self.subTest(full_access=full):
                self.assertEqual(agent_profiles.filter_enabled(EVERYTHING, 'text', full), {'web_search', 'web_visit'})
                self.assertFalse(agent_profiles.external_allowed('text', full))
        self.assertEqual(agent_profiles.filter_enabled({'fs_read'}, 'text', True), set())

    def test_is_a_known_profile(self):
        self.assertEqual(agent_profiles.normalize('text'), 'text')
        source = (ROOT / 'agent' / 'app_preferences.py').read_text(encoding='utf-8')
        self.assertEqual(source.count("('text','light','balanced','advanced')"), 2)   # loaded and accepted when saved

    def test_rule_speaks_of_the_web_not_a_folder(self):
        import agent
        tools = [{'type': 'function', 'function': {'name': 'duckduckgo__web_search', 'parameters': {}}},
                 {'type': 'function', 'function': {'name': 'duckduckgo__web_visit', 'parameters': {}}}]
        rule = agent.tool_rule(tools, full_access=True)
        self.assertIn('web', rule)
        self.assertNotIn('folder', rule)

    def test_the_globe_button_is_the_permission(self):
        from tool_approvals import needs_approval
        for mode in ('ask', 'auto'):
            with self.subTest(mode=mode):
                self.assertFalse(needs_approval(mode, 'duckduckgo__web_search', {'query': 'x'}, 'text'))
                self.assertFalse(needs_approval(mode, 'duckduckgo__web_visit', {'url': 'https://a.b'}, 'text'))
        self.assertTrue(needs_approval('ask', 'duckduckgo__web_visit', {'url': 'https://a.b'}, 'light'))


if __name__ == '__main__':
    unittest.main()
