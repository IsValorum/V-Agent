"""Build the official V-Agent Windows installer inside a clean temporary Git worktree.

Workflow:
1. Refuse to build if the Git working tree has uncommitted or untracked non-ignored changes.
2. Check out HEAD into a clean temporary worktree under ``build/release-worktree``.
3. Validate and copy only the required ignored binaries (``wxc-exec.exe`` verified by SHA-256,
   ``node.exe``, and ``browser/chrome-headless-shell-win64`` verified free of profile data).
4. Assemble the UI, generate clean release data and notices, build ``core`` with PyInstaller
   (``V_AGENT_RELEASE=1``), and build the Tauri NSIS installer.
5. Verify the built core, UI bundle, and executables contain no personal data, user paths,
   private keys, models, seeds, or browser profile files before publishing to ``dist-release/``.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
VCVARS64 = Path(r'C:\Program Files (x86)\Microsoft Visual Studio\2022\BuildTools\VC\Auxiliary\Build\vcvars64.bat')

_PROFILE_ARTIFACT_NAMES = {
    'bookmarks',
    'bookmarks.bak',
    'cookies',
    'cookies-journal',
    'history',
    'history-journal',
    'local state',
    'login data',
    'login data-journal',
    'preferences',
    'secure preferences',
    'top sites',
    'visited links',
    'web data',
}
_FORBIDDEN_BROWSER_DIRS = {'user data'}
_FORBIDDEN_ROOT_DIRS = {'seeds', 'engines', 'models', 'conversations'}
_FORBIDDEN_FILES = {'sessions.sqlite3'}
_FORBIDDEN_SUFFIXES = {'.gguf', '.dpapi', '.key'}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open('rb') as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def _expected_wxc_hash(repo_root: Path) -> str:
    sandbox_file = repo_root / 'agent' / 'sandbox_exec.py'
    match = re.search(r"_EXPECTED\s*=\s*['\"]([0-9a-fA-F]{64})['\"]", sandbox_file.read_text(encoding='utf-8'))
    if not match:
        raise RuntimeError(f'Could not read _EXPECTED SHA-256 from {sandbox_file}')
    return match.group(1).lower()


def _force_remove_tree(path: Path) -> None:
    if not path.exists():
        return

    def _on_rm_error(func, target, _exc):
        os.chmod(target, stat.S_IWRITE)
        func(target)

    shutil.rmtree(path, onexc=_on_rm_error)


def ensure_clean_git(repo_root: Path) -> str:
    """Fail if the working tree has modified, staged, or untracked non-ignored files."""
    status = subprocess.run(
        ['git', '-C', str(repo_root), 'status', '--porcelain'],
        capture_output=True,
        text=True,
        encoding='utf-8',
    )
    if status.returncode != 0:
        raise SystemExit(f'Failed to inspect git status in {repo_root}: {status.stderr.strip()}')
    dirty_lines = [line for line in status.stdout.splitlines() if line.strip()]
    if dirty_lines:
        preview = '\n  '.join(dirty_lines[:20])
        more = f'\n  ... and {len(dirty_lines) - 20} more' if len(dirty_lines) > 20 else ''
        raise SystemExit(
            'Refusing release build: Git working tree is not clean. Commit or stash changes first:\n'
            f'  {preview}{more}'
        )
    rev = subprocess.run(
        ['git', '-C', str(repo_root), 'rev-parse', 'HEAD'],
        capture_output=True,
        text=True,
        encoding='utf-8',
    )
    if rev.returncode != 0:
        raise SystemExit(f'Failed to resolve HEAD in {repo_root}: {rev.stderr.strip()}')
    return rev.stdout.strip()


def _scan_browser_dir_clean(browser_dir: Path) -> list[str]:
    findings = []
    for item in browser_dir.rglob('*'):
        name = item.name.lower()
        if item.is_dir() and name in _FORBIDDEN_BROWSER_DIRS:
            findings.append(f'forbidden browser directory: {item}')
        elif item.is_file() and name in _PROFILE_ARTIFACT_NAMES:
            findings.append(f'browser profile file: {item}')
    return findings


def validate_and_stage_binaries(src_root: Path, worktree: Path) -> None:
    """Validate required ignored runtime/browser binaries and copy only clean pieces."""
    wxc_src = src_root / 'runtime' / 'mxc' / 'wxc-exec.exe'
    if not wxc_src.is_file():
        raise SystemExit(f'Missing required binary: {wxc_src}')
    expected_hash = _expected_wxc_hash(worktree)
    actual_hash = _sha256(wxc_src).lower()
    if actual_hash != expected_hash:
        raise SystemExit(
            f'Refusing release build: {wxc_src} SHA-256 ({actual_hash}) does not match {expected_hash}'
        )

    node_src = src_root / 'runtime' / 'node.exe'
    if not node_src.is_file():
        raise SystemExit(f'Missing required binary: {node_src}')

    browser_src = src_root / 'browser' / 'chrome-headless-shell-win64'
    if not browser_src.is_dir():
        raise SystemExit(f'Missing required headless browser directory: {browser_src}')
    browser_findings = _scan_browser_dir_clean(browser_src)
    if browser_findings:
        raise SystemExit('Refusing release build; browser directory is not clean:\n  ' + '\n  '.join(browser_findings[:10]))

    (worktree / 'runtime' / 'mxc').mkdir(parents=True, exist_ok=True)
    shutil.copy2(wxc_src, worktree / 'runtime' / 'mxc' / 'wxc-exec.exe')
    mxc_license = src_root / 'runtime' / 'mxc' / 'LICENSE.md'
    if mxc_license.is_file():
        shutil.copy2(mxc_license, worktree / 'runtime' / 'mxc' / 'LICENSE.md')
    shutil.copy2(node_src, worktree / 'runtime' / 'node.exe')

    (worktree / 'browser').mkdir(parents=True, exist_ok=True)
    shutil.copytree(browser_src, worktree / 'browser' / 'chrome-headless-shell-win64')


def _is_allowed_pem(path: Path) -> bool:
    parts_lower = [part.lower() for part in path.parts]
    return path.name.lower() == 'cacert.pem' and 'certifi' in parts_lower


def verify_clean_release_output(core_dir: Path, exe_paths: list[Path], home_dir: Path | None = None) -> None:
    """Verify the built core folder, UI bundle, and executables contain no personal or dev data."""
    if not core_dir.is_dir():
        raise SystemExit(f'Missing built core directory: {core_dir}')
    internal = core_dir / '_internal'
    if not internal.is_dir():
        raise SystemExit(f'Missing PyInstaller _internal directory: {internal}')

    errors: list[str] = []
    for base in (core_dir, internal, internal / 'agent'):
        for name in sorted(_FORBIDDEN_ROOT_DIRS):
            candidate = base / name
            if candidate.exists():
                errors.append(f'Forbidden directory in bundle: {candidate}')

    for item in core_dir.rglob('*'):
        if item.is_dir():
            continue
        low_name = item.name.lower()
        if low_name in _FORBIDDEN_FILES or item.suffix.lower() in _FORBIDDEN_SUFFIXES:
            errors.append(f'Forbidden file in bundle: {item}')
        elif item.suffix.lower() == '.pem' and not _is_allowed_pem(item):
            errors.append(f'Unexpected .pem key/certificate file in bundle: {item}')

    profiles_path = internal / 'agent' / 'model-profiles.json'
    if not profiles_path.is_file():
        errors.append(f'Missing {profiles_path}')
    else:
        profiles_data = json.loads(profiles_path.read_text(encoding='utf-8'))
        if profiles_data.get('models') != {} or profiles_data.get('ignored_models') != []:
            errors.append(f'Non-empty models/ignored_models in {profiles_path}')

    recs_path = internal / 'agent' / 'creator-recommendations.json'
    if not recs_path.is_file() or json.loads(recs_path.read_text(encoding='utf-8')) != {}:
        errors.append(f'creator-recommendations.json missing or non-empty: {recs_path}')

    prov_path = internal / 'agent' / 'template-provenance.json'
    if not prov_path.is_file() or json.loads(prov_path.read_text(encoding='utf-8')) != []:
        errors.append(f'template-provenance.json missing or non-empty: {prov_path}')

    browser_bundle = internal / 'browser' / 'chrome-headless-shell-win64'
    if browser_bundle.is_dir():
        errors.extend(_scan_browser_dir_clean(browser_bundle))

    home = home_dir or Path.home()
    username = home.name
    leak_patterns: list[tuple[str, re.Pattern[bytes]]] = [
        ('signing-key reference', re.compile(rb'update-signing-key', re.I)),
    ]
    if username:
        user_bytes = re.escape(username.encode('utf-8'))
        leak_patterns.append(('user home path (ASCII)', re.compile(rb'Users[\\/]+' + user_bytes + rb'(?:[\\/\x00"\']|$)', re.I)))
        user_utf16 = re.escape(username.encode('utf-16le'))
        u16_prefix = b'U\x00s\x00e\x00r\x00s\x00'
        leak_patterns.append(('user home path (UTF-16LE)', re.compile(u16_prefix + b'[\\\\/]\x00' + user_utf16, re.I)))

    scan_targets = [p for p in exe_paths if p.is_file()]
    ui_dist = internal / 'agent' / 'ui' / 'dist'
    if ui_dist.is_dir():
        scan_targets.extend(p for p in ui_dist.rglob('*') if p.is_file() and p.suffix.lower() in {'.html', '.js', '.css', '.json'})

    for target in scan_targets:
        data = target.read_bytes()
        for label, rx in leak_patterns:
            match = rx.search(data)
            if match:
                snippet = match.group(0).decode('latin1', 'replace')
                errors.append(f'{label} found in {target}: {snippet!r}')

    if errors:
        raise SystemExit('Clean release verification failed:\n  ' + '\n  '.join(errors[:25]))


def _run_checked(cmd: list[str], cwd: Path, env: dict[str, str] | None = None) -> None:
    print('>', ' '.join(cmd), flush=True)
    result = subprocess.run(cmd, cwd=str(cwd), env=env)
    if result.returncode != 0:
        raise SystemExit(f'Command exited with code {result.returncode}: {" ".join(cmd)}')


def _run_tauri_nsis(worktree: Path, env: dict[str, str]) -> None:
    desktop_dir = worktree / 'desktop'
    tauri_cmd = 'npx --yes @tauri-apps/cli@2 build --bundles nsis'
    if shutil.which('cl.exe', path=env.get('PATH')):
        _run_checked(['cmd', '/c', tauri_cmd], cwd=desktop_dir, env=env)
        return
    if not VCVARS64.is_file():
        raise SystemExit(f'Missing Visual Studio Build Tools environment script: {VCVARS64}')
    _run_checked(['cmd', '/c', f'call "{VCVARS64}" && {tauri_cmd}'], cwd=desktop_dir, env=env)


def _cleanup_worktree(repo_root: Path, worktree: Path) -> None:
    if worktree.exists():
        subprocess.run(
            ['git', '-C', str(repo_root), 'worktree', 'remove', '--force', str(worktree)],
            capture_output=True,
            text=True,
        )
    _force_remove_tree(worktree)
    subprocess.run(['git', '-C', str(repo_root), 'worktree', 'prune'], capture_output=True, text=True)


def build_from_clean_worktree(repo_root: Path, python_exe: Path) -> Path:
    """Create a clean detached worktree at HEAD, build the release installer, verify, and publish."""
    head_sha = ensure_clean_git(repo_root)
    worktree = repo_root / 'build' / 'release-worktree'
    _cleanup_worktree(repo_root, worktree)
    worktree.parent.mkdir(parents=True, exist_ok=True)

    print(f'Staging clean temporary worktree at {head_sha[:7]} -> {worktree}', flush=True)
    _run_checked(['git', '-C', str(repo_root), 'worktree', 'add', '--detach', str(worktree), head_sha], cwd=repo_root)

    try:
        validate_and_stage_binaries(repo_root, worktree)

        base_env = os.environ.copy()
        cargo_home = repo_root / '.cargo'
        base_env['CARGO_HOME'] = str(cargo_home)
        base_env['CARGO_BUILD_JOBS'] = base_env.get('CARGO_BUILD_JOBS', '6')
        rust_bin = base_env.get('V_AGENT_RUST_BIN', '').strip()
        if rust_bin:
            base_env['PATH'] = rust_bin + os.pathsep + base_env.get('PATH', '')

        py = str(python_exe)
        _run_checked([py, 'scripts/build-ui.py'], cwd=worktree, env=base_env)
        _run_checked([py, 'scripts/prepare_release.py'], cwd=worktree, env=base_env)
        _run_checked([py, 'scripts/third_party_notices.py'], cwd=worktree, env=base_env)

        pyinstaller_env = base_env.copy()
        pyinstaller_env['V_AGENT_RELEASE'] = '1'
        _run_checked(
            [py, '-m', 'PyInstaller', 'scripts/core.spec', '--noconfirm', '--distpath', 'dist-release', '--workpath', 'build/core-release'],
            cwd=worktree,
            env=pyinstaller_env,
        )

        tauri_env = base_env.copy()
        remap = f'--remap-path-prefix={worktree}=/v-agent-src --remap-path-prefix={cargo_home}=/cargo'
        existing_rustflags = tauri_env.get('RUSTFLAGS', '').strip()
        tauri_env['RUSTFLAGS'] = f'{existing_rustflags} {remap}'.strip()
        _run_tauri_nsis(worktree, tauri_env)

        nsis_dir = worktree / 'desktop' / 'src-tauri' / 'target' / 'release' / 'bundle' / 'nsis'
        installers = sorted(nsis_dir.glob('V-Agent_*_x64-setup.exe'))
        if len(installers) != 1:
            raise SystemExit(f'Expected 1 NSIS installer in {nsis_dir}, found: {[p.name for p in installers]}')
        built_installer = installers[0]
        built_core = worktree / 'dist-release' / 'core'
        built_tauri_exe = worktree / 'desktop' / 'src-tauri' / 'target' / 'release' / 'V-Agent.exe'

        verify_clean_release_output(
            built_core,
            [built_tauri_exe, built_core / 'strata-core.exe', built_core / '_internal' / 'runtime' / 'mxc' / 'wxc-exec.exe'],
        )
        print('Clean release verification passed.', flush=True)

        dist_release = repo_root / 'dist-release'
        dist_release.mkdir(parents=True, exist_ok=True)
        _force_remove_tree(dist_release / 'core')
        for stale in list(dist_release.glob('V-Agent_*_x64-setup.exe')) + list(dist_release.glob('v-agent-update.json*')):
            stale.unlink(missing_ok=True)

        shutil.copytree(built_core, dist_release / 'core')
        out_installer = dist_release / built_installer.name
        shutil.copy2(built_installer, out_installer)
        print(f'Verified clean installer ready: {out_installer}', flush=True)
        return out_installer
    finally:
        _cleanup_worktree(repo_root, worktree)


def main() -> int:
    parser = argparse.ArgumentParser(description='Build and verify a clean V-Agent release installer from HEAD.')
    parser.add_argument('--verify-only', action='store_true', help='Only verify an existing dist-release/core bundle.')
    args = parser.parse_args()

    if args.verify_only:
        dist_core = ROOT / 'dist-release' / 'core'
        exes = [
            ROOT / 'desktop' / 'src-tauri' / 'target' / 'release' / 'V-Agent.exe',
            dist_core / 'strata-core.exe',
            dist_core / '_internal' / 'runtime' / 'mxc' / 'wxc-exec.exe',
        ]
        verify_clean_release_output(dist_core, exes)
        print('Verified existing dist-release/core is clean.')
        return 0

    python_exe = ROOT / '.venv' / 'Scripts' / 'python.exe'
    if not python_exe.is_file():
        python_exe = Path(sys.executable)
    build_from_clean_worktree(ROOT, python_exe)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
