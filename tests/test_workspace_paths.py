import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'agent'))
import access_policy
from access_policy import AccessPolicy, migrate_workspace_layout


class WorkspacePathTests(unittest.TestCase):
    def test_legacy_folders_migrate_without_losing_files(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / 'workspaces'
            legacy = root / 'conversaciones' / 'chat-1'
            (legacy / 'borradores').mkdir(parents=True)
            (legacy / 'salidas').mkdir()
            (legacy / 'contexto').mkdir()
            (legacy / 'borradores' / 'draft.json').write_text('draft', encoding='utf8')
            (legacy / 'salidas' / 'result.txt').write_text('result', encoding='utf8')
            (legacy / 'contexto' / 'batch.json').write_text('batch', encoding='utf8')
            migrate_workspace_layout(root)
            current = root / 'conversations' / 'chat-1'
            self.assertEqual((current / 'drafts' / 'draft.json').read_text(encoding='utf8'), 'draft')
            self.assertEqual((current / 'outputs' / 'result.txt').read_text(encoding='utf8'), 'result')
            self.assertEqual((current / 'context' / 'batch.json').read_text(encoding='utf8'), 'batch')
            self.assertFalse((root / 'conversaciones').exists())

    def test_access_policy_uses_english_workspace_name(self):
        with tempfile.TemporaryDirectory() as directory:
            policy = AccessPolicy(Path(directory) / 'sandbox')
            self.assertEqual(policy.workspaces.name, 'conversations')
            self.assertEqual(policy.for_conversation('chat-1').root.name, 'chat-1')


if __name__ == '__main__':
    unittest.main()
