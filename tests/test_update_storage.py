"""Updates leave nothing behind: installed V-Agent installers, minor updates of other versions; Maya's newest tag."""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

if 'STRATA_AGENT_DATA' not in os.environ:
    os.environ['STRATA_AGENT_DATA'] = tempfile.mkdtemp(prefix='va-test-')
sys.path[:0] = ['agent', '.']
import app_updates  # noqa: E402
import components  # noqa: E402


class InstallerTests(unittest.TestCase):
    def test_installers_already_installed_and_broken_downloads_are_removed(self):
        with tempfile.TemporaryDirectory() as folder:
            service = app_updates.AppUpdates()
            service.root = Path(folder)
            major, minor, patch_ = app_updates.parse_version(app_updates.VERSION)
            names = {'old': 'V-Agent_1.0.1_x64-setup.exe', 'same': f'V-Agent_{app_updates.VERSION}_x64-setup.exe',
                     'newer': f'V-Agent_{major}.{minor}.{patch_ + 1}_x64-setup.exe', 'part': f'V-Agent_{major}.{minor}.{patch_ + 1}_x64-setup.part',
                     'other': 'notes.txt'}
            for name in names.values():
                (service.root / name).write_bytes(b'x')
            service.prune_installed()
            self.assertEqual(sorted(p.name for p in service.root.iterdir()), sorted([names['newer'], names['other']]))


class ComponentTests(unittest.TestCase):
    def test_minor_updates_of_another_version_are_removed(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            with patch.object(components, 'ROOT', root):
                (root / 'r2').mkdir(); (root / 'r4').mkdir(); (root / 'r4' / 'ui-patch.css').write_text('x')
                (root / 'active.json').write_text(json.dumps({'manifest': '{"app_version": "1.0.0"}', 'signature': 'x'}))
                components.prune()
                self.assertEqual(list(root.iterdir()), [])


class MayaTests(unittest.TestCase):
    def test_highest_tag_when_github_lists_them_by_name(self):
        import io
        import maya_engine

        class Response(io.BytesIO):
            def __enter__(self): return self
            def __exit__(self, *a): self.close()
        tags = [{'name': 'v0.9.0'}, {'name': 'v0.10.2'}, {'name': 'v0.10.10'}, {'name': 'nightly'}]
        replies = iter([Response(b'[]'), Response(json.dumps(tags).encode())])
        with patch.object(maya_engine.urllib.request, 'urlopen', lambda request, timeout=0: next(replies)):
            result = maya_engine.check_latest_release('v0.9.0')
        self.assertEqual(result['tag'], 'v0.10.10')
        self.assertTrue(result['available'])


if __name__ == '__main__':
    unittest.main()
