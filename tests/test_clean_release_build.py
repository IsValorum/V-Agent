"""Tests for clean-worktree release builds and personal-data verification."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / 'scripts') not in sys.path:
    sys.path.insert(0, str(ROOT / 'scripts'))

import clean_release_build as crb


def _init_temp_repo(repo: Path) -> None:
    subprocess.run(['git', 'init', str(repo)], check=True, capture_output=True)
    subprocess.run(['git', '-C', str(repo), 'config', 'user.name', 'Test'], check=True, capture_output=True)
    subprocess.run(['git', '-C', str(repo), 'config', 'user.email', 'test@example.invalid'], check=True, capture_output=True)
    (repo / '.gitignore').write_text('/build/\n/dist-release/\n/runtime/\n/browser/\n', encoding='utf-8')
    (repo / 'agent').mkdir()
    (repo / 'agent' / 'sandbox_exec.py').write_text(
        f"_EXPECTED = '{'a' * 64}'\n",
        encoding='utf-8',
    )
    subprocess.run(['git', '-C', str(repo), 'add', '.gitignore', 'agent/sandbox_exec.py'], check=True, capture_output=True)
    subprocess.run(['git', '-C', str(repo), 'commit', '-m', 'init'], check=True, capture_output=True)


def _make_clean_core(base: Path) -> tuple[Path, Path]:
    core_dir = base / 'core'
    internal = core_dir / '_internal'
    (internal / 'agent' / 'ui' / 'dist').mkdir(parents=True)
    (internal / 'agent' / 'model-profiles.json').write_text(
        json.dumps({'version': 1, 'profiles': {}, 'models': {}, 'ignored_models': []}),
        encoding='utf-8',
    )
    (internal / 'agent' / 'creator-recommendations.json').write_text('{}\n', encoding='utf-8')
    (internal / 'agent' / 'template-provenance.json').write_text('[]\n', encoding='utf-8')
    (internal / 'agent' / 'ui' / 'dist' / 'v-agent.html').write_text('<html><body>clean</body></html>', encoding='utf-8')
    (internal / 'certifi').mkdir(parents=True)
    (internal / 'certifi' / 'cacert.pem').write_text('CA CERT', encoding='utf-8')
    (internal / 'ddgs' / 'engines').mkdir(parents=True)
    (internal / 'ddgs' / 'engines' / '__init__.py').write_text('', encoding='utf-8')
    (internal / 'browser' / 'chrome-headless-shell-win64').mkdir(parents=True)
    (internal / 'browser' / 'chrome-headless-shell-win64' / 'chrome.exe').write_bytes(b'MZ')
    exe = base / 'V-Agent.exe'
    exe.write_bytes(b'MZ-clean-binary')
    return core_dir, exe


class CleanReleaseBuildTests(unittest.TestCase):
    def test_ensure_clean_git_rejects_dirty_and_untracked_allows_ignored(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / 'repo'
            _init_temp_repo(repo)
            (repo / 'build').mkdir()
            (repo / 'build' / 'temp.txt').write_text('ignored', encoding='utf-8')
            sha = crb.ensure_clean_git(repo)
            self.assertEqual(len(sha), 40)

            (repo / 'stray.txt').write_text('untracked', encoding='utf-8')
            with self.assertRaises(SystemExit) as ctx:
                crb.ensure_clean_git(repo)
            self.assertIn('stray.txt', str(ctx.exception))
            (repo / 'stray.txt').unlink()

            (repo / 'agent' / 'sandbox_exec.py').write_text("_EXPECTED = 'dirty'\n", encoding='utf-8')
            with self.assertRaises(SystemExit):
                crb.ensure_clean_git(repo)

    def test_validate_and_stage_binaries_checks_hash_and_browser_profiles(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / 'src'
            wt = Path(tmp) / 'wt'
            (root / 'runtime' / 'mxc').mkdir(parents=True)
            (root / 'browser' / 'chrome-headless-shell-win64').mkdir(parents=True)
            (wt / 'agent').mkdir(parents=True)

            wxc_bytes = b'clean-wxc-binary'
            import hashlib
            digest = hashlib.sha256(wxc_bytes).hexdigest()
            (wt / 'agent' / 'sandbox_exec.py').write_text(f"_EXPECTED = '{digest}'\n", encoding='utf-8')
            (root / 'runtime' / 'mxc' / 'wxc-exec.exe').write_bytes(wxc_bytes)
            (root / 'runtime' / 'node.exe').write_bytes(b'node')
            (root / 'runtime' / 'extra-leak.txt').write_text('should not copy', encoding='utf-8')
            (root / 'browser' / 'chrome-headless-shell-win64' / 'chrome-headless-shell.exe').write_bytes(b'chrome')

            crb.validate_and_stage_binaries(root, wt)
            self.assertTrue((wt / 'runtime' / 'mxc' / 'wxc-exec.exe').is_file())
            self.assertTrue((wt / 'runtime' / 'node.exe').is_file())
            self.assertFalse((wt / 'runtime' / 'extra-leak.txt').exists())

            (root / 'browser' / 'chrome-headless-shell-win64' / 'Cookies').write_text('secret', encoding='utf-8')
            with self.assertRaises(SystemExit) as ctx:
                crb.validate_and_stage_binaries(root, wt)
            self.assertIn('Cookies', str(ctx.exception))
            (root / 'browser' / 'chrome-headless-shell-win64' / 'Cookies').unlink()

            (root / 'runtime' / 'mxc' / 'wxc-exec.exe').write_bytes(b'tampered')
            with self.assertRaises(SystemExit) as ctx:
                crb.validate_and_stage_binaries(root, wt)
            self.assertIn('SHA-256', str(ctx.exception))

    def test_verify_clean_release_output_catches_leaks_and_passes_when_clean(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            core_dir, exe = _make_clean_core(base)
            fake_home = Path(r'C:\Users\AliceTester')

            crb.verify_clean_release_output(core_dir, [exe], home_dir=fake_home)

            cases = [
                (core_dir / '_internal' / 'agent' / 'model-profiles.json',
                 json.dumps({'version': 1, 'profiles': {}, 'models': {'my-model': {}}, 'ignored_models': []})),
                (core_dir / '_internal' / 'agent' / 'creator-recommendations.json', '{"x": 1}'),
                (core_dir / '_internal' / 'agent' / 'template-provenance.json', '[{"a": 1}]'),
            ]
            for path, bad_text in cases:
                good = path.read_text(encoding='utf-8')
                path.write_text(bad_text, encoding='utf-8')
                with self.assertRaises(SystemExit):
                    crb.verify_clean_release_output(core_dir, [exe], home_dir=fake_home)
                path.write_text(good, encoding='utf-8')

            leak_pem = core_dir / '_internal' / 'update-signing-key.pem'
            leak_pem.write_text('PRIVATE', encoding='utf-8')
            with self.assertRaises(SystemExit):
                crb.verify_clean_release_output(core_dir, [exe], home_dir=fake_home)
            leak_pem.unlink()

            (core_dir / '_internal' / 'engines').mkdir()
            with self.assertRaises(SystemExit):
                crb.verify_clean_release_output(core_dir, [exe], home_dir=fake_home)
            (core_dir / '_internal' / 'engines').rmdir()

            exe.write_bytes(b'panic at C:\\Users\\AliceTester\\proj\\main.rs')
            with self.assertRaises(SystemExit):
                crb.verify_clean_release_output(core_dir, [exe], home_dir=fake_home)

            exe.write_bytes('C:\\Users\\AliceTester\\proj'.encode('utf-16le'))
            with self.assertRaises(SystemExit):
                crb.verify_clean_release_output(core_dir, [exe], home_dir=fake_home)

    def test_worktree_cleaned_up_even_when_build_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / 'repo'
            _init_temp_repo(repo)
            (repo / 'runtime' / 'mxc').mkdir(parents=True)
            (repo / 'browser' / 'chrome-headless-shell-win64').mkdir(parents=True)
            (repo / 'runtime' / 'mxc' / 'wxc-exec.exe').write_bytes(b'x')
            (repo / 'runtime' / 'node.exe').write_bytes(b'n')
            with patch.object(crb, 'validate_and_stage_binaries', side_effect=RuntimeError('boom')):
                with self.assertRaises(RuntimeError):
                    crb.build_from_clean_worktree(repo, Path(sys.executable))
            self.assertFalse((repo / 'build' / 'release-worktree').exists())
            wt_list = subprocess.check_output(['git', '-C', str(repo), 'worktree', 'list'], text=True)
            self.assertNotIn('release-worktree', wt_list)


if __name__ == '__main__':
    unittest.main()
