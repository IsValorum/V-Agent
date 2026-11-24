"""Models on this PC: each file is shown where it really is, and the user's own folders are searched."""
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'agent'))

import external_models as E


class WhereTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        base = Path(self.tmp.name)
        self.lm, self.hf, self.mine = base / 'lmstudio' / 'models', base / 'hf' / 'hub', base / 'D' / 'IsValorum'
        for folder in (self.lm, self.hf, self.mine):
            folder.mkdir(parents=True)
        self.patches = [mock.patch.object(E, 'HF_CACHE', self.hf), mock.patch.object(E, 'FOLDERS_FILE', base / 'folders.json')]
        for patch in self.patches:
            patch.start()

    def tearDown(self):
        for patch in self.patches:
            patch.stop()
        self.tmp.cleanup()

    def test_a_file_reached_through_lm_studio_but_stored_elsewhere_is_shown_by_its_folder(self):
        outside = (self.mine / 'model.gguf').resolve()
        self.assertEqual(E._where(outside, 'lmstudio', self.lm), 'folder')
        self.assertEqual(E._where((self.lm / 'm.gguf').resolve(), 'lmstudio', self.lm), 'lmstudio')
        self.assertEqual(E._where((self.hf / 'x' / 'm.gguf').resolve(), 'unsloth', self.lm), 'hf_cache')

    def test_folders_are_added_once_and_removed(self):
        self.assertEqual(E.add_folder(str(self.mine)), [str(self.mine)])
        self.assertEqual(E.add_folder(str(self.mine)), [str(self.mine)])
        with self.assertRaises(ValueError):
            E.add_folder(str(self.mine / 'missing'))
        self.assertEqual(E.remove_folder(str(self.mine)), [])

    def test_a_users_folder_is_searched_and_companions_are_left_out(self):
        (self.mine / 'Model' ).mkdir()
        for name in ('Model-Q4_K_M.gguf', 'mmproj-Model.gguf', 'model-imatrix.gguf'):
            (self.mine / 'Model' / name).write_bytes(b'GGUF')
        E.add_folder(str(self.mine))
        with mock.patch.object(E, 'LMSTUDIO', Path(self.tmp.name) / 'none'), \
                mock.patch.object(E, 'UNSLOTH', Path(self.tmp.name) / 'none'):
            found = E.scan()['models']
        self.assertEqual([(m['name'], m['source'], m['folder']) for m in found],
                         [('Model-Q4_K_M', 'folder', str((self.mine / 'Model').resolve()))])


if __name__ == '__main__':
    unittest.main()
