import sys
import tempfile
import unittest
from pathlib import Path

sys.path[:0] = [str(Path('agent').resolve()), str(Path('tools').resolve())]
import draft_models


class DraftTests(unittest.TestCase):
    def test_validate_and_arguments(self):
        with tempfile.TemporaryDirectory() as folder:
            file = Path(folder).resolve() / 'draft.gguf'  # long form (CI temp folders can be 8.3 short names)
            file.write_bytes(b'GGUF')
            settings = draft_models.validate({'enabled': True, 'path': str(file), 'type': 'draft-dflash', 'max': 4, 'min': 1}, require_file=True)
            self.assertEqual(settings['max'], 4)
            args = draft_models.arguments(settings)
            self.assertEqual(args[:4], ['--spec-draft-model', str(file), '--spec-type', 'draft-dflash'])
            self.assertIn('--spec-draft-n-max', args)
            self.assertIn('--spec-draft-n-min', args)

    def test_invalid_values(self):
        for value in ({'enabled': 1}, {'max': 0}, {'min': 5, 'max': 4}, {'type': 'nope'}, {'path': 'draft.bin'}):
            with self.assertRaises(ValueError):
                draft_models.validate(value)
        with self.assertRaises(ValueError):
            draft_models.validate({'enabled': True, 'path': 'missing.gguf'})

    def test_auto_inference_falls_back_to_simple(self):
        with tempfile.TemporaryDirectory() as folder:
            file = Path(folder).resolve() / 'draft.gguf'  # long form (CI temp folders can be 8.3 short names)
            file.write_bytes(b'not a real gguf')
            self.assertEqual(draft_models.infer_type(file), 'draft-simple')


if __name__ == '__main__':
    unittest.main()
