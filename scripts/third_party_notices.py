"""Write THIRD-PARTY-NOTICES.md: the components bundled in V-Agent and their licenses.

Python packages are read from the build environment's metadata; the native components are listed
explicitly. Engines (llama.cpp, Strata, Strata Rust) and models are NOT bundled: V-Agent downloads
them from their official channels on the user's request, under their own licenses.
"""
from importlib import metadata
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
NATIVE = [
    ('Python', 'Python Software Foundation License', 'https://www.python.org/'),
    ('PyInstaller bootloader', 'GPL-2.0 with the bootloader exception (allows distributing bundled apps under any license)', 'https://pyinstaller.org/'),
    ('Tauri', 'MIT OR Apache-2.0', 'https://tauri.app/'),
    ('Microsoft Edge WebView2 Runtime (installed separately by Windows)', 'Microsoft Software License Terms', 'https://developer.microsoft.com/microsoft-edge/webview2/'),
    ('Chrome Headless Shell (browser/, used to check pages)', 'BSD-3-Clause and others, see browser/*/LICENSE.headless_shell', 'https://developer.chrome.com/'),
    ('Node.js (runtime/node.exe, used for JavaScript syntax checks)', 'MIT', 'https://nodejs.org/'),
    ('Microsoft MXC process isolation (runtime/mxc)', 'MIT, see runtime/mxc/LICENSE.md', 'https://github.com/microsoft/'),
]
SKIP = {'pip', 'setuptools', 'wheel', 'pyinstaller', 'pyinstaller-hooks-contrib', 'altgraph', 'pefile', 'pywin32-ctypes'}


def license_of(dist):
    meta = dist.metadata
    expression = meta.get('License-Expression')
    if expression:
        return expression
    classifiers = [c.split('::')[-1].strip() for c in meta.get_all('Classifier') or [] if c.startswith('License ::')]
    if classifiers:
        return ', '.join(dict.fromkeys(classifiers))
    value = (meta.get('License') or '').strip().splitlines()
    return value[0][:80] if value and value[0] else 'See package metadata'


def main():
    rows = []
    for dist in sorted(metadata.distributions(), key=lambda d: (d.metadata.get('Name') or '').lower()):
        name = dist.metadata.get('Name')
        if not name or name.lower() in SKIP:
            continue
        rows.append('| %s | %s | %s |' % (name, dist.version, license_of(dist).replace('|', '/')))
    text = ['# Third-party notices', '',
            'V-Agent is licensed under the Apache License 2.0 (see LICENSE). It bundles the components below,',
            'each under its own license. Engines (llama.cpp, Strata, Strata Rust) and models are not bundled;',
            'V-Agent downloads them from their official sources only when the user asks, under their own licenses.', '',
            '## Native components', '', '| Component | License | Website |', '|---|---|---|']
    text += ['| %s | %s | %s |' % row for row in NATIVE]
    text += ['', '## Python packages', '', '| Package | Version | License |', '|---|---|---|'] + rows + ['']
    (ROOT / 'THIRD-PARTY-NOTICES.md').write_text('\n'.join(text), encoding='utf-8')
    print('THIRD-PARTY-NOTICES.md:', len(rows), 'Python packages')


if __name__ == '__main__':
    main()
