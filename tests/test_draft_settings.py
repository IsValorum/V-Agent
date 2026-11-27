import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'agent'))
sys.path.insert(0, str(ROOT / 'tools'))

import draft_settings


class DraftSettingsTests(unittest.TestCase):
    def test_strata_accepts_q8_dspark_and_rejects_q4_dspark(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            main_gguf = d / 'Inkling-2-Mini.gguf'
            q8_gguf = d / 'dspark-Inkling-2-Mini-Q8_0.gguf'
            q4_gguf = d / 'dspark-Inkling-2-Mini-Q4_0.gguf'
            for p in (main_gguf, q8_gguf, q4_gguf):
                p.write_bytes(b'GGUF')
            cfg = d / 'strata-inkling.json'
            cfg.write_text(json.dumps({'args': ['--model', str(main_gguf), '--kv', 'q8_0']}), encoding='utf-8')

            headers = {
                str(main_gguf.resolve()): {
                    'path': str(main_gguf.resolve()), 'head': False, 'arch': 'inkling2_loop',
                    'embedding': 2304, 'pre': 'inkling2', 'markov_rank': None, 'types': ['Q4_K'],
                    'signature': ('inkling2_loop', 2304, 128),
                },
                str(q8_gguf.resolve()): {
                    'path': str(q8_gguf.resolve()), 'head': False, 'arch': 'dflash',
                    'embedding': 2304, 'pre': 'inkling2', 'markov_rank': 256, 'types': ['Q8_0', 'F32', 'BF16'],
                    'signature': ('dflash', 2304, None),
                },
                str(q4_gguf.resolve()): {
                    'path': str(q4_gguf.resolve()), 'head': False, 'arch': 'dflash',
                    'embedding': 2304, 'pre': 'inkling2', 'markov_rank': 256, 'types': ['Q4_0', 'F32', 'BF16'],
                    'signature': ('dflash', 2304, None),
                },
            }

            with mock.patch.object(draft_settings, 'header', side_effect=lambda p: headers[str(Path(p).resolve())]):
                info = draft_settings.describe(cfg)
                self.assertEqual([f['name'] for f in info['files']], ['dspark-Inkling-2-Mini-Q8_0.gguf'])

                saved, _before, changed = draft_settings.save(cfg, str(q8_gguf), 2)
                self.assertTrue(changed)
                self.assertEqual(saved['source'], str(q8_gguf.resolve()))

                with self.assertRaises(ValueError) as ctx:
                    draft_settings.save(cfg, str(q4_gguf), 2)
                self.assertIn('Q8_0', str(ctx.exception))
                self.assertIn('Q4_0', str(ctx.exception))

    def test_dspark_inferred_as_dspark_and_treated_as_companion(self):
        import draft_models
        import model_mover
        import external_models
        with mock.patch('gguf_catalog.inspect', return_value={
            'metadata': {'general.architecture': 'dflash', 'dflash.dspark.markov_rank': 256},
            'head': False,
        }):
            self.assertEqual(draft_models.infer_type('dspark-Inkling-2-Mini-Q4_0.gguf'), 'draft-dspark')
        with mock.patch('gguf_catalog.inspect', return_value={
            'metadata': {'general.architecture': 'dflash'},
            'head': False,
        }):
            self.assertEqual(draft_models.infer_type('dflash-model-Q4_0.gguf'), 'draft-dflash')
        for name in ('dspark-Inkling-2-Mini-Q4_0.gguf', 'dflash-draft.gguf', 'eagle3-head.gguf', 'gemma4-assistant.gguf'):
            self.assertTrue(model_mover._is_companion(name), name)
            self.assertTrue(external_models._skip(Path(name)), name)


if __name__ == '__main__':
    unittest.main()
