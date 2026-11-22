"""After a Strata update the old engine folder is gone; the model configs must follow the new executable
before the model list is built, or every model shows as unavailable and none can be chosen."""
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'agent'), str(ROOT / 'tools'), str(ROOT)]

from desktop_runtime import sync_managed_configs  # noqa: E402


class StrataConfigSync(unittest.TestCase):
    def test_managed_configs_follow_the_new_engine_and_others_are_left_alone(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            new = root / 'engine-updates' / 'strata' / 'poly.10' / 'bin' / 'strata-poly.exe'
            old = str(root / 'engine-updates' / 'strata' / 'poly.9' / 'bin' / 'strata-poly.exe')
            managed = root / 'strata-model.json'
            managed.write_text(json.dumps({'exe': old, '_val_managed_engine': True, 'args': [],
                                           'vision': {'exe': 'old-vision.exe'}}), encoding='utf-8')
            custom = root / 'strata-custom.json'
            custom.write_text(json.dumps({'exe': 'C:/mine/strata.exe', 'args': []}), encoding='utf-8')
            vision = root / 'new-vision.exe'
            changed = sync_managed_configs(root, new, lambda: vision)
            self.assertEqual(changed, [managed])
            cfg = json.loads(managed.read_text(encoding='utf-8'))
            self.assertEqual(cfg['exe'], str(new))
            self.assertIn(str(new.parent), cfg['lib_dirs'])
            self.assertEqual(cfg['vision']['exe'], str(vision))
            self.assertEqual(json.loads(custom.read_text(encoding='utf-8'))['exe'], 'C:/mine/strata.exe')
            # Nothing to do the second time.
            self.assertEqual(sync_managed_configs(root, new, lambda: vision), [])


if __name__ == '__main__':
    unittest.main()
