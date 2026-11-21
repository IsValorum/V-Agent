import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'agent'))
import instructions  # noqa: E402


class InstructionsTest(unittest.TestCase):
    def test_empty_snapshot_and_prompt(self):
        with tempfile.TemporaryDirectory() as tmp:
            snap = instructions.snapshot(data_dir=tmp)
            self.assertEqual(snap['content'], '')
            self.assertFalse(snap['project_active'])
            self.assertEqual(instructions.prompt_section(data_dir=tmp), '')

    def test_save_read_and_clear_global(self):
        with tempfile.TemporaryDirectory() as tmp:
            saved = instructions.save_global('Always use concise answers.\r\nUse Python 3.12.', data_dir=tmp)
            self.assertEqual(saved['content'], 'Always use concise answers.\nUse Python 3.12.')
            raw = (Path(tmp) / 'AGENTS.md').read_bytes()
            self.assertFalse(raw.startswith(b'\xef\xbb\xbf'))
            block = instructions.prompt_section(data_dir=tmp)
            self.assertIn('Global instructions (AGENTS.md):', block)
            self.assertIn('Use Python 3.12.', block)
            cleared = instructions.save_global('   \n  ', data_dir=tmp)
            self.assertEqual(cleared['content'], '')
            self.assertFalse((Path(tmp) / 'AGENTS.md').exists())

    def test_project_instructions_combined_and_deduplicated(self):
        with tempfile.TemporaryDirectory() as data_tmp, tempfile.TemporaryDirectory() as proj_tmp:
            instructions.save_global('Global rule.', data_dir=data_tmp)
            (Path(proj_tmp) / 'AGENTS.md').write_text('Project rule.', encoding='utf-8')
            block = instructions.prompt_section(project_root=proj_tmp, data_dir=data_tmp)
            self.assertIn('Global instructions (AGENTS.md):\nGlobal rule.', block)
            self.assertIn('Project instructions (AGENTS.md):\nProject rule.', block)
            snap = instructions.snapshot(project_root=proj_tmp, data_dir=data_tmp)
            self.assertTrue(snap['project_active'])
            self.assertTrue(snap['project_path'].endswith('AGENTS.md'))
            # Same folder as data_dir must not duplicate the global file.
            same_block = instructions.prompt_section(project_root=data_tmp, data_dir=data_tmp)
            self.assertNotIn('Project instructions (AGENTS.md):', same_block)

    def test_validation_and_truncation(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ValueError):
                instructions.save_global(123, data_dir=tmp)
            with self.assertRaises(ValueError):
                instructions.save_global('a' * (instructions.MAX_CHARS + 1), data_dir=tmp)
            (Path(tmp) / 'AGENTS.md').write_text('x' * (instructions.MAX_CHARS + 500), encoding='utf-8')
            block = instructions.prompt_section(data_dir=tmp)
            self.assertIn(f'[Truncated to {instructions.MAX_CHARS} characters.]', block)


if __name__ == '__main__':
    unittest.main()
