"""Fixes from the code audit of 1.1.16: registry MCP names, oversized document parts."""
import io
import sys
import unittest
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'agent'))

import doc_extractor  # noqa: E402
import extensions  # noqa: E402


class RegistryNames(unittest.TestCase):
    def test_every_registry_name_becomes_a_valid_local_name(self):
        for raw in ('io.github/foo', '1abc', 'a//b', '__x__', 'x' * 50, '', None):
            name = extensions._server_name(raw)
            self.assertTrue(extensions.validate_servers({name: {'url': 'https://example.com/mcp'}}), raw)


class DocumentParts(unittest.TestCase):
    def test_a_part_larger_than_the_limit_is_refused(self):
        data = io.BytesIO()
        with zipfile.ZipFile(data, 'w', zipfile.ZIP_DEFLATED) as zf:
            zf.writestr('content.xml', b'<a>' + b' ' * 4096 + b'</a>')
        with zipfile.ZipFile(io.BytesIO(data.getvalue())) as zf:
            self.assertEqual(len(doc_extractor._zip_read(zf, 'content.xml')), 4103)
            with self.assertRaises(ValueError):
                doc_extractor._zip_read(zf, 'content.xml', limit=1024)


if __name__ == '__main__':
    unittest.main()
