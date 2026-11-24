"""Updating from 1.1.15 or earlier: settings naming the old program layout point at the new one, once."""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'agent'))

import runtime_paths as R


class LayoutMigrationTests(unittest.TestCase):
    def test_old_program_paths_are_rewritten_once_and_nothing_else_changes(self):
        with tempfile.TemporaryDirectory() as folder:
            data, program = Path(folder) / 'data', Path(folder) / 'V-Agent'
            (data / 'settings').mkdir(parents=True)
            (data / 'strata' / 'agent' / 'model-assets' / 'm' / 'tokenizer').mkdir(parents=True)
            old_core = str(program / 'core' / 'strata-core.exe')
            node = str(program / 'core' / '_internal' / 'runtime' / 'node.exe')
            (data / 'mcp.json').write_text(json.dumps({'mcpServers': {
                'pc': {'command': old_core, 'args': ['--role', 'pc'], '_val_bundled': True},
                'mine': {'command': node, 'args': ['server.js'], 'cwd': 'C:/elsewhere/_internal'}}}), encoding='utf-8')
            vocab = data / 'strata' / 'agent' / 'model-assets' / 'm' / 'tokenizer' / 'vocab.json'
            vocab.write_text(json.dumps({'_internal': 1, old_core: 2}), encoding='utf-8')
            prefs = data / 'settings' / 'app-preferences.json'
            prefs.write_text(json.dumps({'language': 'es', 'agent_profile': 'light'}), encoding='utf-8')
            with mock.patch.object(R, 'DATA_ROOT', data), mock.patch.object(R, 'SETTINGS_ROOT', data / 'settings'), \
                    mock.patch.object(R, 'CONFIG_ROOT', data / 'strata'), mock.patch.object(R, 'MIGRATIONS_FILE', data / 'migrations.json'):
                changed = R.migrate_program_layout(program)
                self.assertEqual([Path(p).name for p in changed], ['mcp.json'])
                servers = json.loads((data / 'mcp.json').read_text(encoding='utf-8'))['mcpServers']
                self.assertEqual(servers['pc']['command'], str(program / 'core' / 'v-agent-core.exe'))
                self.assertEqual(servers['mine']['command'], str(program / 'core' / 'lib' / 'runtime' / 'node.exe'))
                self.assertEqual(servers['mine']['cwd'], 'C:/elsewhere/_internal')      # not the program's path
                self.assertEqual(json.loads(vocab.read_text(encoding='utf-8')), {'_internal': 1, old_core: 2})
                self.assertEqual(json.loads(prefs.read_text(encoding='utf-8'))['agent_profile'], 'light')
                self.assertEqual(R.migrate_program_layout(program), [])               # done once


if __name__ == '__main__':
    unittest.main()
