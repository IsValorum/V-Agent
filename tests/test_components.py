import base64
import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path[:0] = ['agent', '.']
import app_updates
import components
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey


class ComponentTests(unittest.TestCase):
    def setUp(self):
        self.private = Ed25519PrivateKey.generate()
        raw = self.private.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
        self.public = base64.b64encode(raw).decode()
        self.tmp = tempfile.TemporaryDirectory(); self.root = Path(self.tmp.name)
        self.patches = [patch.object(app_updates, 'PUBLIC_KEY', self.public), patch.object(components, 'ROOT', self.root)]
        for item in self.patches: item.start()

    def tearDown(self):
        for item in self.patches: item.stop()
        sys.meta_path[:] = [f for f in sys.meta_path if not getattr(f, 'v_agent_components', None)]
        sys.modules.pop('mcp_prompt', None)
        self.tmp.cleanup()

    def manifest(self, files, version=None, revision=1):
        body = {'product': 'V-Agent', 'channel': 'components', 'app_version': version or app_updates.VERSION, 'revision': revision,
                'files': [{'name': name, 'size': len(data), 'sha256': hashlib.sha256(data).hexdigest()} for name, data in files.items()]}
        raw = json.dumps(body).encode()
        return raw, base64.b64encode(self.private.sign(raw)).decode()

    def install(self, files, revision=1):
        raw, sig = self.manifest(files, revision=revision)
        folder = self.root / ('r%d' % revision); folder.mkdir(parents=True)
        for name, data in files.items(): (folder / name).write_bytes(data)
        (self.root / 'active.json').write_text(json.dumps({'manifest': raw.decode(), 'signature': sig}))
        return folder

    def test_verified_component_replaces_the_bundled_module(self):
        self.install({'mcp_prompt.py': b'COMPONENT_MARK = "updated"\n'})
        sys.modules.pop('mcp_prompt', None)
        self.assertIsNotNone(components.enable_overlay())
        import mcp_prompt
        self.assertEqual(getattr(mcp_prompt, 'COMPONENT_MARK', None), 'updated')

    def test_tampered_file_falls_back_to_bundled_code(self):
        folder = self.install({'mcp_prompt.py': b'COMPONENT_MARK = "updated"\n'})
        (folder / 'mcp_prompt.py').write_bytes(b'COMPONENT_MARK = "evil"\n')
        self.assertIsNone(components.active_overlay())

    def test_rejects_unlisted_files_other_versions_and_foreign_signatures(self):
        raw, sig = self.manifest({'agent.py': b'x'})
        with self.assertRaises(ValueError): components.validate(raw, sig)
        raw, sig = self.manifest({'pc_mcp.py': b'x'}, version='9.9.9')
        with self.assertRaises(ValueError): components.validate(raw, sig)
        raw, _ = self.manifest({'pc_mcp.py': b'x'})
        other = base64.b64encode(Ed25519PrivateKey.generate().sign(raw)).decode()
        with self.assertRaises(ValueError): components.validate(raw, other)

    def test_reset_returns_to_bundled_components(self):
        self.install({'pc_mcp.py': b'x = 1\n'})
        updater = components.Components('owner/V-Agent')
        self.assertEqual(updater.installed_revision(), 1)
        updater.reset()
        self.assertEqual(updater.installed_revision(), 0); self.assertIsNone(components.active_overlay())


if __name__ == '__main__':
    unittest.main()
