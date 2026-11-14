"""Unit tests for minor component updates, hardened updater headers, and optional local engines."""
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'agent'))

import app_updates  # noqa: E402
import components  # noqa: E402
import engine_updates  # noqa: E402


class _FakeResponse:
    def __init__(self, payload):
        self._raw = json.dumps(payload).encode('utf-8') if not isinstance(payload, (bytes, str)) else (
            payload.encode('utf-8') if isinstance(payload, str) else payload
        )

    def read(self, *_args):
        return self._raw

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class V2UpdatesAndHeadersTests(unittest.TestCase):
    def test_updaters_use_v_agent_user_agent_and_identity_encoding(self):
        self.assertTrue(app_updates.USER_AGENT.startswith('V-Agent/'))
        seen = []

        def fake_urlopen(req, timeout=20):
            seen.append((req.full_url, {k.lower(): v for k, v in req.header_items()}))
            return _FakeResponse([])

        updater = app_updates.AppUpdates('owner/repo')
        with mock.patch('urllib.request.urlopen', side_effect=fake_urlopen):
            raw = updater._get('https://api.github.com/repos/owner/repo/releases?per_page=100', 2**22)
        self.assertEqual(json.loads(raw), [])

        self.assertEqual(len(seen), 1)
        url, headers = seen[0]
        self.assertIn('per_page=100', url)
        self.assertTrue(headers['user-agent'].startswith('V-Agent/'))
        self.assertEqual(headers['accept-encoding'], 'identity')

        src = Path(engine_updates.__file__).read_text(encoding='utf-8')
        self.assertNotIn("'VAL-Agent'", src)
        self.assertIn("'V-Agent/'+app_updates.VERSION", src)

    def test_components_check_fetches_100_releases_and_requires_signed_manifest(self):
        with tempfile.TemporaryDirectory() as td:
            prev_data, prev_root = components.DATA_ROOT, components.ROOT
            components.DATA_ROOT = Path(td)
            components.ROOT = Path(td) / 'components'
            try:
                mgr = components.Components('owner/repo')
                releases = [{
                    'tag_name': f'components-{app_updates.VERSION}-r1',
                    'draft': False,
                    'assets': [{'name': 'MANIFEST', 'browser_download_url': 'https://github.com/owner/repo/releases/download/x/MANIFEST'}],
                }]
                urls = []

                def fake_get(url, limit):
                    urls.append((url, limit))
                    return json.dumps(releases).encode('utf-8')

                with mock.patch.object(mgr, '_get', side_effect=fake_get):
                    snap = mgr.check()
                self.assertIn('per_page=100', urls[0][0])
                self.assertEqual(urls[0][1], 2**22)
                self.assertIn('signed manifest', snap['error'])
            finally:
                components.DATA_ROOT, components.ROOT = prev_data, prev_root


if __name__ == '__main__':
    unittest.main()
