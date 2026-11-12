"""Start-up after an update: the window is served before the tool servers finish starting, and the
first reply still gets every tool."""
import os
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, patch

if 'STRATA_AGENT_DATA' not in os.environ:
    import atexit, shutil
    os.environ['STRATA_AGENT_DATA'] = tempfile.mkdtemp(prefix='va-test-')
    atexit.register(shutil.rmtree, os.environ['STRATA_AGENT_DATA'], True)
sys.path[:0] = ['agent', '.', 'tools']


class StartupTests(unittest.TestCase):
    def test_the_core_serves_without_waiting_for_tool_servers(self):
        import agent
        hub = MagicMock()
        server = MagicMock()
        server.serve_forever.side_effect = SystemExit
        with patch.object(agent, 'ThreadingHTTPServer', return_value=server), \
                patch.object(agent, 'create_agent_hub', return_value=hub), \
                patch.object(agent, 'http_json', side_effect=OSError), \
                patch.object(sys, 'argv', ['backend.py']), patch.dict(os.environ, {'STRATA_AGENT_NO_OPEN': '1'}):
            with self.assertRaises(SystemExit):
                agent.main()
        hub.start.assert_called_once_with(wait=False)
        server.serve_forever.assert_called_once()

    def test_the_first_reply_waits_for_tool_servers_still_starting(self):
        import agent
        order = []
        hub = MagicMock()
        hub.wait.side_effect = lambda timeout: order.append(('wait', timeout))
        hub.openai_tools.side_effect = lambda *a, **k: order.append(('tools',)) or []
        with patch.object(agent, 'HUB', hub):
            agent.tools_for({'files': True})
        self.assertEqual(order[:2], [('wait', None), ('tools',)])


class UpdateHelperTests(unittest.TestCase):
    def test_installer_is_built_for_fast_extraction(self):
        import json
        from pathlib import Path
        config = json.loads(Path('desktop/src-tauri/tauri.conf.json').read_text(encoding='utf-8'))
        # LZMA took ~12 s of the ~25 s restart to unpack 540 MB; zlib unpacks it in ~2 s.
        self.assertEqual(config['bundle']['windows']['nsis']['compression'], 'zlib')


if __name__ == '__main__':
    unittest.main()
