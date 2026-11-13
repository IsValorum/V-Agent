"""File tools found unreliable in the real-model battery: search, copy/move, history, unwritten files."""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path[:0] = ['agent', '.', 'tools']
if 'STRATA_AGENT_DATA' not in os.environ:
    import atexit, shutil
    os.environ['STRATA_AGENT_DATA'] = tempfile.mkdtemp(prefix='va-test-')
    atexit.register(shutil.rmtree, os.environ['STRATA_AGENT_DATA'], True)
import pc_mcp
from access_policy import AccessPolicy
from file_versions import FileVersions


class FileToolTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name).resolve()
        self.policy = AccessPolicy(self.root)

    def tearDown(self):
        self.tmp.cleanup()

    def call(self, name, **args):
        return pc_mcp.call(name, args, full_access=False, policy=self.policy)

    def test_default_search_pattern_includes_top_level_files(self):
        (self.root / 'a.py').write_text('# TODO revisar\n', encoding='utf-8')
        (self.root / 'docs').mkdir()
        (self.root / 'docs' / 'c.md').write_text('TODO: documentar\n', encoding='utf-8')
        (self.root / 'b.py').write_text('x = 1\n', encoding='utf-8')
        found = json.loads(self.call('fs_search', contains='TODO'))
        self.assertEqual(sorted(m['path'].replace('\\', '/') for m in found['matches']), ['a.py', 'docs/c.md'])
        only_py = json.loads(self.call('fs_search', glob='**/*.py', contains='TODO'))
        self.assertEqual([m['path'] for m in only_py['matches']], ['a.py'])

    def test_move_with_missing_source_never_touches_the_destination(self):
        (self.root / 'respaldo.txt').write_text('importante', encoding='utf-8')
        for overwrite in (False, True):
            with self.assertRaises(ValueError) as error:
                self.call('fs_manage', action='move', path='archivo/respaldo.txt', destination='respaldo.txt', overwrite=overwrite)
            self.assertIn('Source does not exist', str(error.exception))
        self.assertEqual((self.root / 'respaldo.txt').read_text(encoding='utf-8'), 'importante')

    def test_copy_and_move_replace_only_when_asked(self):
        (self.root / 'a.txt').write_text('nuevo', encoding='utf-8')
        (self.root / 'b.txt').write_text('viejo', encoding='utf-8')
        with self.assertRaises(ValueError):
            self.call('fs_manage', action='copy', path='a.txt', destination='b.txt')
        self.call('fs_manage', action='copy', path='a.txt', destination='b.txt', overwrite=True)
        self.assertEqual((self.root / 'b.txt').read_text(encoding='utf-8'), 'nuevo')
        self.call('fs_manage', action='move', path='a.txt', destination='sub/a.txt')
        self.assertTrue((self.root / 'sub' / 'a.txt').is_file()); self.assertFalse((self.root / 'a.txt').exists())
        (self.root / 'carpeta').mkdir()
        with self.assertRaises(ValueError):
            self.call('fs_manage', action='move', path='carpeta', destination='carpeta/dentro')
        with self.assertRaises(ValueError):
            self.call('fs_manage', action='copy', path='b.txt', destination='b.txt', overwrite=True)

    def test_history_describes_each_version_for_the_model(self):
        versions = FileVersions(self.root / '.versions')
        target = self.root / 'config.json'
        versions.capture(target, self.root)                       # before creation
        target.write_text('{"modo": "claro"}', encoding='utf-8')
        versions.capture(target, self.root)                       # before the change
        target.write_text('{"modo": "oscuro"}', encoding='utf-8')
        info = versions.describe(target, self.root)
        self.assertEqual(info['current'], '{"modo": "oscuro"}')
        newest, oldest = info['versions']
        self.assertEqual(newest['preview'], '{"modo": "claro"}')
        self.assertIn('did not exist', oldest['state'])
        self.assertIn('created', versions.history(target, self.root)[0])  # the interface still gets its list

    def test_file_tools_report_clear_english_error_when_given_a_directory(self):
        (self.root / 'sub').mkdir()
        (self.root / 'a.txt').write_text('hola', encoding='utf-8')
        with self.assertRaises(ValueError) as read_err:
            self.call('fs_read', path='sub')
        self.assertIn('is a directory, not a file; use fs_list', str(read_err.exception))
        with self.assertRaises(ValueError) as write_err:
            self.call('fs_write', path='sub', content='x')
        self.assertIn('is an existing directory, not a file', str(write_err.exception))
        with self.assertRaises(ValueError) as edit_err:
            self.call('fs_edit', path='sub', old_text='a', new_text='b')
        self.assertIn('is a directory, not a file', str(edit_err.exception))
        with self.assertRaises(ValueError) as list_err:
            self.call('fs_list', path='a.txt')
        self.assertIn('is a file, not a directory; use fs_read', str(list_err.exception))


class UnwrittenFileTests(unittest.TestCase):
    def test_detects_code_shown_instead_of_the_requested_file(self):
        import agent
        tools = [{'function': {'name': 'pc__fs_write'}}]
        ask = [{'role': 'user', 'content': 'Crea pagina.html con un botón'}]
        self.assertEqual(agent.archivo_no_creado(ask, tools, 'Aquí está:\n```html\n<html></html>\n```'), 'pagina.html')
        self.assertIsNone(agent.archivo_no_creado(ask, tools, 'Listo, sin código.'))
        self.assertIsNone(agent.archivo_no_creado([{'role': 'user', 'content': 'Explícame index.html'}], tools, '```html```'))
        written = ask + [{'role': 'assistant', 'tool_calls': [{'function': {'name': 'pc__fs_write'}}]}]
        self.assertIsNone(agent.archivo_no_creado(written, tools, '```html```'))
        self.assertIsNone(agent.archivo_no_creado(ask, [], '```html```'))


if __name__ == '__main__':
    unittest.main()
