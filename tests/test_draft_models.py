import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

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
        with self.assertRaises(ValueError):
            draft_models.validate({'enabled': True, 'path': '', 'type': 'draft-simple'})

    def test_builtin_mtp_allows_empty_path_and_auto_enables(self):
        settings = draft_models.validate({'enabled': True, 'path': '', 'type': 'draft-mtp', 'max': 3, 'min': 0})
        self.assertTrue(settings['enabled'])
        self.assertEqual(settings['path'], '')
        self.assertEqual(settings['type'], 'draft-mtp')

        with tempfile.TemporaryDirectory() as folder:
            model = Path(folder).resolve() / 'qwen-mtp.gguf'
            model.write_bytes(b'GGUF')
            with mock.patch.object(draft_models, 'has_head', return_value=True):
                # Absent draft preference -> auto-enabled built-in MTP without --spec-draft-model.
                self.assertEqual(
                    draft_models.arguments(None, model),
                    ['--spec-type', 'draft-mtp', '--spec-draft-n-max', '3'],
                )
                self.assertEqual(draft_models.weight_bytes(None, model), 0)
                # Explicit enabled=False -> remembered off.
                self.assertEqual(draft_models.arguments({'enabled': False}, model), [])
                # Draft path pointing at the main model itself -> treated as built-in head, not loaded twice.
                same_args = draft_models.arguments({'enabled': True, 'path': str(model), 'type': 'auto', 'max': 4}, model)
                self.assertEqual(same_args, ['--spec-type', 'draft-mtp', '--spec-draft-n-max', '4'])
                self.assertEqual(draft_models.weight_bytes({'enabled': True, 'path': str(model)}, model), 0)
                # Strata Rust: auto-enables --mtp N when supported, respects explicit off and explicit --mtp option.
                self.assertEqual(draft_models.rust_arguments(None, model, '--mtp <N>'), ['--mtp', '3'])
                self.assertEqual(draft_models.rust_arguments({'enabled': False}, model, '--mtp <N>'), [])
                self.assertEqual(draft_models.rust_arguments(None, model, '--mtp <N>', explicit_mtp=5), [])
                self.assertEqual(draft_models.rust_arguments(None, model, '--gpu'), [])

            with mock.patch.object(draft_models, 'has_head', return_value=False):
                # Model without MTP head -> not auto-enabled and empty-path draft-mtp emits nothing.
                self.assertEqual(draft_models.arguments(None, model), [])
                self.assertEqual(draft_models.arguments({'enabled': True, 'path': '', 'type': 'draft-mtp'}, model), [])
                self.assertEqual(draft_models.rust_arguments(None, model, '--mtp <N>'), [])

    def test_auto_inference_falls_back_to_simple(self):
        with tempfile.TemporaryDirectory() as folder:
            file = Path(folder).resolve() / 'draft.gguf'  # long form (CI temp folders can be 8.3 short names)
            file.write_bytes(b'not a real gguf')
            self.assertEqual(draft_models.infer_type(file), 'draft-simple')


if __name__ == '__main__':
    unittest.main()
