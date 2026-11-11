import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path[:0] = [str(Path('agent').resolve()), str(Path('tools').resolve())]
import plugins


class PluginTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name) / 'plugins'
        self.old_root, self.old_state = plugins.ROOT, plugins.STATE
        plugins.ROOT = self.root
        plugins.STATE = self.root / 'installed.json'

    def tearDown(self):
        plugins.ROOT, plugins.STATE = self.old_root, self.old_state
        self.temp.cleanup()

    def test_manifest_toggle_and_prompt(self):
        result = plugins.install_manifest({
            'name': 'Review toolkit',
            'version': '1.2',
            'description': 'Review support',
            'instructions': 'Verify changed files before answering.',
            'commands': [{'name': 'Review', 'prompt': 'Review the current diff.'}],
        })
        self.assertEqual(len(result), 1)
        self.assertFalse(result[0]['enabled'])
        self.assertEqual(plugins.prompt_block(), '')
        plugins.set_enabled('review-toolkit', True)
        self.assertIn('Review toolkit', plugins.prompt_block())
        self.assertIn('Verify changed files', plugins.prompt_block())
        self.assertEqual(len(plugins.public()[0]['commands']), 1)
        plugins.remove('review-toolkit')
        self.assertEqual(plugins.public(), [])

    def test_folder_skill_and_command_files(self):
        folder = Path(self.temp.name) / 'bundle'
        (folder / 'skills' / 'review').mkdir(parents=True)
        (folder / 'commands').mkdir()
        (folder / 'plugin.json').write_text(json.dumps({'name': 'Bundle', 'version': '1'}), encoding='utf8')
        (folder / 'skills' / 'review' / 'SKILL.md').write_text('Check regressions first.', encoding='utf8')
        (folder / 'commands' / 'check.md').write_text('---\ndescription: check\n---\nRun the checks.', encoding='utf8')
        result = plugins.install_path(folder)
        item = result[0]
        self.assertIn('Check regressions first', plugins._read()['bundle']['instructions'])
        self.assertEqual(item['commands'][0]['name'], 'check')
        self.assertIn('Run the checks', item['commands'][0]['prompt'])

    def test_invalid_manifest_and_duplicate(self):
        with self.assertRaises(ValueError):
            plugins.install_manifest({'name': ''})
        plugins.install_manifest({'name': 'One'})
        with self.assertRaises(ValueError):
            plugins.install_manifest({'name': 'One'})
        with self.assertRaises(ValueError):
            plugins.set_enabled('missing', True)


if __name__ == '__main__':
    unittest.main()
