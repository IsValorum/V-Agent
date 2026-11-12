"""Error detection that used to say "fine" when the file or the preview was broken."""
import hashlib
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path[:0] = ['agent', '.']
import verify
import app_updates
import render_check


def check(name, text):
    with tempfile.TemporaryDirectory() as folder:
        path = Path(folder) / name
        path.write_text(text, encoding='utf-8')
        return verify.verificar_archivo(str(path))


class SyntaxCheckTests(unittest.TestCase):
    def test_python_errors_found_only_when_compiling(self):
        # ast.parse accepted all three; Python refuses them when the file runs.
        for source in ('x = 1\nreturn x\n', 'await f()\n', 'for i in []:\n    pass\nbreak\n'):
            self.assertIs(check('a.py', source)['ok'], False, source)
        self.assertIs(check('a.py', 'def f():\n    return 1\n')['ok'], True)

    def test_css_structure(self):
        self.assertIs(check('a.css', 'a { color: red; }\nb { background: url("x(1).png"); }\n')['ok'], True)
        for broken in ('a { color: red;\nb { }\n', '/* open\na{}', 'a { content: "x }\n', 'a } {'):
            self.assertIs(check('a.css', broken)['ok'], False, broken)

    @unittest.skipUnless(shutil.which('powershell'), 'Windows PowerShell required')
    def test_powershell_parser(self):
        self.assertIs(check('a.ps1', 'if ($x) { "hola" }\n')['ok'], True)
        result = check('a.ps1', 'if ($x) { "hola"\n')
        self.assertIs(result['ok'], False)
        self.assertIn('line 1', result['errores'][0])

    def test_missing_compiler_is_never_reported_as_fine(self):
        original = shutil.which
        shutil.which = lambda *a, **k: None
        try:
            result = check('a.rs', 'fn main() {}\n')
        finally:
            shutil.which = original
        self.assertIsNone(result['ok'])
        self.assertIn('rustc', result['avisos'][0])

    def test_written_files_are_checked_for_new_languages(self):
        for extension in ('.css', '.ps1', '.ts', '.c', '.rs', '.go', '.php', '.rb', '.lua'):
            self.assertIn(extension, verify.COMPROBABLES)


class PreviewSandboxTests(unittest.TestCase):
    def test_probe_matches_the_preview_iframe(self):
        # The preview iframe: sandbox="allow-scripts allow-modals", opaque origin.
        frame = Path('agent/ui/app/markdown.js').read_text(encoding='utf-8')
        self.assertIn("setAttribute('sandbox','allow-scripts allow-modals')", frame)
        for denied in ("'localStorage'", "'sessionStorage'", "'cookie'", 'IDBFactory', 'CacheStorage', 'window.open'):
            self.assertIn(denied, render_check.SANDBOX_VISTA_PREVIA)


class InstallerReuseTests(unittest.TestCase):
    def test_verified_installer_is_reused_and_old_ones_removed(self):
        with tempfile.TemporaryDirectory() as folder:
            updater = app_updates.AppUpdates('owner/V-Agent')
            updater.root = Path(folder)
            body = b'installer'
            (updater.root / 'V-Agent_1.0.1_x64-setup.exe').write_bytes(b'old')
            (updater.root / 'V-Agent_1.0.2_x64-setup.part').write_bytes(b'half')
            target = updater.root / 'V-Agent_1.0.3_x64-setup.exe'
            target.write_bytes(body)
            updater.state['available'] = {'installer': {'name': target.name, 'size': len(body),
                                                        'sha256': hashlib.sha256(body).hexdigest(),
                                                        'url': 'https://example.invalid/never-fetched'}}
            self.assertEqual(updater.download(), target)  # no network: the URL would be refused
            self.assertEqual(updater.state['ready'], str(target))
            self.assertEqual(sorted(p.name for p in updater.root.iterdir()), [target.name])
            self.assertFalse(updater.state['busy'])


if __name__ == '__main__':
    unittest.main()
