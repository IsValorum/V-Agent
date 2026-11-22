import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'agent'))
from access_policy import AccessPolicy  # noqa: E402
import pc_mcp  # noqa: E402


class McpHardeningTests(unittest.TestCase):
    def test_fs_manage_copy_file_into_existing_dir_preserves_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            policy = AccessPolicy(root)
            (root / 'index.html').write_text('<h1>hello</h1>', encoding='utf-8')
            target_dir = root / 'pruebas'
            target_dir.mkdir()
            (target_dir / 'keep.txt').write_text('important', encoding='utf-8')

            out = pc_mcp.call('fs_manage', {'action': 'copy', 'path': 'index.html', 'destination': 'pruebas', 'overwrite': True}, full_access=False, policy=policy)
            self.assertIn('copied:', out)
            self.assertTrue(target_dir.is_dir())
            self.assertEqual((target_dir / 'keep.txt').read_text(encoding='utf-8'), 'important')
            self.assertEqual((target_dir / 'index.html').read_text(encoding='utf-8'), '<h1>hello</h1>')

    def test_fs_copy_missing_source_reports_matching_subfolder_and_workspace_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            policy = AccessPolicy(root)
            sub = root / 'web'
            sub.mkdir()
            (sub / 'index.html').write_text('<p>ok</p>', encoding='utf-8')

            with self.assertRaises(ValueError) as ctx:
                pc_mcp.fs_copy({'desde': 'index.html', 'destino': 'pruebas/index.html', 'modo': 'nuevo'}, False, policy)
            self.assertIn('web/index.html', str(ctx.exception))

    def test_fs_copy_accepts_english_aliases_and_directory_destination(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            policy = AccessPolicy(root)
            (root / 'a.txt').write_text('line1\nline2\n', encoding='utf-8')
            (root / 'out').mkdir()

            res = pc_mcp.fs_copy({'source': 'a.txt', 'destination': 'out', 'mode': 'new'}, False, policy)
            self.assertIn('pasted:', res)
            self.assertEqual((root / 'out' / 'a.txt').read_text(encoding='utf-8'), 'line1\nline2\n')

    def test_fs_copy_binary_file_gives_clear_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            policy = AccessPolicy(root)
            (root / 'img.bin').write_bytes(b'\xff\xfe\x00\x80')

            with self.assertRaises(ValueError) as ctx:
                pc_mcp.fs_copy({'desde': 'img.bin', 'destino': 'copy.bin', 'modo': 'nuevo'}, False, policy)
            self.assertIn('fs_manage', str(ctx.exception))

    def test_fs_manage_stat_missing_raises_value_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            policy = AccessPolicy(Path(tmp))
            with self.assertRaises(ValueError):
                pc_mcp.call('fs_manage', {'action': 'stat', 'path': 'missing.txt'}, full_access=False, policy=policy)

    def test_attached_files_are_staged_in_sandbox_and_copyable_directly(self):
        import agent
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            policy = AccessPolicy(root)
            msgs = [{'role': 'user', 'content': 'Copia index.html a pruebas/\n\n[Adjuntos]\n--- index.html ---\n<h1>Hola</h1>\n\n--- ../../style.css ---\nbody { color: red; }'}]
            updated, saved = agent._stage_user_attachments(msgs, policy, is_project=False)
            self.assertEqual(saved, ['index.html', 'style.css'])
            self.assertEqual((root / 'index.html').read_text(encoding='utf-8'), '<h1>Hola</h1>')
            self.assertEqual((root / 'style.css').read_text(encoding='utf-8'), 'body { color: red; }')
            self.assertIn('pc__fs_copy', updated[-1]['content'])
            # Now fs_copy and fs_manage work directly on the staged attachment!
            (root / 'pruebas').mkdir()
            res = pc_mcp.fs_copy({'desde': 'index.html', 'destino': 'pruebas/index.html', 'modo': 'nuevo'}, False, policy)
            self.assertIn('pasted:', res)
            self.assertEqual((root / 'pruebas' / 'index.html').read_text(encoding='utf-8'), '<h1>Hola</h1>')

    def test_attached_files_do_not_overwrite_existing_or_project_root(self):
        import agent
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            policy = AccessPolicy(root)
            (root / 'index.html').write_text('original', encoding='utf-8')
            msgs = [{'role': 'user', 'content': 'Mira\n\n[Adjuntos]\n--- index.html ---\nnew version'}]
            _, saved_sandbox = agent._stage_user_attachments(msgs, policy, is_project=False)
            self.assertEqual(saved_sandbox, ['attachments/index.html'])
            self.assertEqual((root / 'index.html').read_text(encoding='utf-8'), 'original')
            self.assertEqual((root / 'attachments' / 'index.html').read_text(encoding='utf-8'), 'new version')
            # Project mode always stages under attachments/
            _, saved_proj = agent._stage_user_attachments(msgs, policy, is_project=True)
            self.assertEqual(saved_proj, ['attachments/index.html'])

    def test_access_policy_check_tool_fs_copy_english_aliases(self):
        with tempfile.TemporaryDirectory() as tmp:
            policy = AccessPolicy(Path(tmp))
            policy.check_tool('fs_copy', {'source': 'a.txt', 'destination': 'sub/b.txt'}, False)
            with self.assertRaises(Exception):
                policy.check_tool('fs_copy', {'source': '../escape.txt', 'destination': 'b.txt'}, False)

    def test_remove_conversation_deletes_sandbox_only_and_unassigns_project(self):
        import os, stat
        from projects import ProjectStore
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            sandbox_root = base / 'workspaces'
            project_dir = base / 'my-project'
            project_dir.mkdir()
            (project_dir / 'keep.txt').write_text('important', encoding='utf-8')

            policy = AccessPolicy(sandbox_root)
            chat_id = 'chat-delete-test-01'
            conv_policy = policy.for_conversation(chat_id)
            (conv_policy.root / 'nested').mkdir(parents=True)
            ro_file = conv_policy.root / 'nested' / 'readonly.txt'
            ro_file.write_text('created by agent', encoding='utf-8')
            os.chmod(ro_file, stat.S_IREAD)

            store = ProjectStore(base / 'projects.json')
            store.select(chat_id, path=str(project_dir))
            self.assertIsNotNone(store.snapshot(chat_id)['selected'])

            self.assertTrue(policy.remove_conversation(chat_id))
            self.assertFalse(conv_policy.root.exists())
            self.assertFalse(policy.remove_conversation(chat_id))

            self.assertTrue(store.unassign(chat_id))
            self.assertIsNone(store.snapshot(chat_id)['selected'])
            self.assertFalse(store.unassign(chat_id))
            # External project folder MUST remain intact
            self.assertTrue((project_dir / 'keep.txt').exists())
            self.assertEqual((project_dir / 'keep.txt').read_text(encoding='utf-8'), 'important')


if __name__ == '__main__':
    unittest.main()
