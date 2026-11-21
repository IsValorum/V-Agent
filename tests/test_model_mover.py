import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'agent'))
import model_hub  # noqa: E402
import model_mover  # noqa: E402


class ModelMoverTests(unittest.TestCase):
    def test_infer_layout_from_group_and_parents(self):
        self.assertEqual(
            model_mover.infer_layout(r'D:\lm\unsloth\Qwen3-8B-GGUF\Qwen3-8B-Q4_K_M.gguf', group='unsloth/Qwen3-8B-GGUF'),
            ('unsloth', 'Qwen3-8B-GGUF'),
        )
        self.assertEqual(
            model_mover.infer_layout(r'C:\cache\models--bartowski--Llama-3.2-3B-GGUF\snapshots\abc\model.gguf'),
            ('bartowski', 'Llama-3.2-3B-GGUF'),
        )
        self.assertEqual(
            model_mover.infer_layout(r'D:\MyModels\CreatorX\CoolModel\CoolModel-Q8_0.gguf'),
            ('CreatorX', 'CoolModel'),
        )

    def test_collect_companions_shards_vision_and_mtp(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / 'unsloth' / 'Gemma-4-GGUF'
            root.mkdir(parents=True)
            s1 = root / 'gemma-Q4_K_M-00001-of-00002.gguf'
            s2 = root / 'gemma-Q4_K_M-00002-of-00002.gguf'
            mm = root / 'mmproj-F16.gguf'
            mtp = root / 'gemma-mtp-Q8_0.gguf'
            for f in (s1, s2, mm, mtp):
                f.write_bytes(b'GGUF' * 10)
            collected = [p.name for p in model_mover.collect_model_files(s1)]
            self.assertEqual(collected[0], s1.name)
            self.assertIn(s2.name, collected)
            self.assertIn(mm.name, collected)
            self.assertIn(mtp.name, collected)

    def test_move_organizes_into_models_creator_model_with_progress(self):
        with tempfile.TemporaryDirectory() as src_tmp, tempfile.TemporaryDirectory() as dst_tmp:
            src_dir = Path(src_tmp) / 'bartowski' / 'Demo-8B-GGUF'
            src_dir.mkdir(parents=True)
            main_gguf = src_dir / 'Demo-8B-Q4_K_M.gguf'
            mmproj = src_dir / 'mmproj-BF16.gguf'
            main_gguf.write_bytes(b'A' * 4096)
            mmproj.write_bytes(b'B' * 2048)

            registered = []
            mover = model_mover.ModelMover(
                folder_fn=lambda: Path(dst_tmp) / 'models',
                register_fn=lambda path, name, item: registered.append((path, name)) or {'id': 'llama--demo', 'status': 'added'},
            )
            mover.start([{'path': str(main_gguf), 'name': 'Demo-8B-Q4_K_M', 'group': 'bartowski/Demo-8B-GGUF'}])
            for _ in range(100):
                snap = mover.snapshot()
                if not snap['active']:
                    break
                time.sleep(0.02)
            snap = mover.snapshot()
            self.assertEqual(snap['phase'], 'done')
            self.assertEqual(snap['percent'], 100.0)
            self.assertEqual(snap['files_done'], 2)
            expected_dir = Path(dst_tmp) / 'models' / 'bartowski' / 'Demo-8B-GGUF'
            self.assertTrue((expected_dir / main_gguf.name).is_file())
            self.assertTrue((expected_dir / mmproj.name).is_file())
            self.assertFalse(main_gguf.exists())
            self.assertFalse(mmproj.exists())
            self.assertEqual(len(registered), 1)
            self.assertEqual(Path(registered[0][0]), expected_dir / main_gguf.name)

    def test_hub_downloads_use_creator_model_layout(self):
        with tempfile.TemporaryDirectory() as tmp:
            dl = model_hub.Downloads()
            dl.folder = lambda: Path(tmp) / 'models'
            target = dl._target_dir('unsloth/Qwen3-8B-GGUF')
            self.assertEqual(target, Path(tmp) / 'models' / 'unsloth' / 'Qwen3-8B-GGUF')


if __name__ == '__main__':
    unittest.main()
