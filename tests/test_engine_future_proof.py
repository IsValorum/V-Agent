"""What a future engine update brings (new Maya families, new flags) shows up without changing V-Agent."""
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'agent'))
sys.path.insert(0, str(ROOT))

import engine_options
import maya_engine

MAYA_HELP = """\
usage: maya --config FILE
  --max-context N        tokens the caches hold
  --kv FMT               cache format
  --parallel N           answers at once
  --lookahead-depth N         a new option a later Maya adds (default: 4)
  --fast-attn <on|off>   another new one
"""


class MayaFutureTests(unittest.TestCase):
    def test_unknown_family_gets_the_shared_panel_not_glm(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'maya-new.json'
            path.write_text(json.dumps({'exe': 'maya-x.exe', 'args': ['--max-context', '8192'],
                                        'installer': {'family': 'kestrel'}, 'model_name': 'Kestrel'}), encoding='utf-8')
            info = maya_engine.describe_config(path)
            self.assertEqual(info['family'], 'generic')
            self.assertIn('context', info['schema']['fields'])
            self.assertNotIn('draft', info['schema']['fields'])
            self.assertEqual(maya_engine.apply_family_settings(path, {"context": 16384})['context'], 16384)

    def test_known_families_are_unchanged(self):
        for family in maya_engine.KNOWN_FAMILIES:
            with self.subTest(family=family):
                self.assertEqual(maya_engine.config_family({'exe': 'x', 'args': [], 'installer': {'family': family}}),
                                 family)

    def test_new_maya_flags_are_offered_and_managed_ones_are_not(self):
        catalog = engine_options.catalog('maya', MAYA_HELP)
        flags = {o['flag']: o['kind'] for o in catalog['options']}
        self.assertEqual(flags, {'--lookahead-depth': 'int', '--fast-attn': 'choice'})
        saved = engine_options.validate({'flag__lookahead_depth': 6, 'flag__fast_attn': 'on'})
        args, applied = engine_options.apply('maya', ['--max-context', '8192', '--lookahead-depth', '2'], saved, MAYA_HELP)
        self.assertEqual(args, ['--max-context', '8192', '--lookahead-depth', '6', '--fast-attn', 'on'])


if __name__ == '__main__':
    unittest.main()
