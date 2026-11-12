"""Check what is really published on GitHub, the way installed copies of V-Agent will see it.

    .venv\\Scripts\\python scripts\\quality\\verify_release.py [--previous 1.0.4] [--installer]

- App update: the highest release's signed manifest (v-agent-update.json + .sig) is downloaded and
  validated exactly as the previous version validates it (Ed25519 signature, product, installer name,
  checksum, size, newer version), and the installer asset must match the signed size. `--installer`
  also downloads the installer and checks its SHA-256 (several hundred MB).
- Minor updates: the newest components-<version>-rN release for this version is found, verified,
  downloaded and applied through the real components channel into a throw-away data folder, and
  every applied file is compared with its signed checksum.
- Tampering: a manifest changed by one byte, or a signature from another manifest, is refused.

Needs the internet; reads only public GitHub data and writes only to a temporary folder.
"""
import argparse
import hashlib
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for stream in (sys.stdout, sys.stderr):
    stream.reconfigure(encoding='utf-8', errors='replace')
DATA = tempfile.mkdtemp(prefix='va-release-check-')
os.environ['STRATA_AGENT_DATA'] = DATA
sys.path[:0] = [str(ROOT / 'agent'), str(ROOT)]
import app_updates  # noqa: E402
import components  # noqa: E402

rows = []


def check(name, ok, detail=''):
    rows.append({'engine': 'release', 'check': name, 'status': 'pass' if ok else 'fail', 'detail': str(detail)[:300]})
    print(f"  {'OK  ' if ok else 'FAIL'} {name}" + (f' — {detail}' if detail else ''))
    return ok


def refused(function, *args):
    try:
        function(*args)
        return False
    except ValueError:
        return True


def app_release(previous, installer):
    updates = app_updates.AppUpdates()
    releases = json.loads(updates._get('https://api.github.com/repos/%s/releases?per_page=30' % updates.repository, 2**21))
    apps = [r for r in releases if not r.get('draft') and not r.get('prerelease')
            and not str(r.get('tag_name', '')).startswith('components-')]
    release = max(apps, key=lambda r: app_updates.parse_version(str(r['tag_name']).lstrip('vV')))
    assets = {a['name']: a for a in release.get('assets') or []}
    check(f"latest app release {release['tag_name']} has a signed manifest",
          app_updates.MANIFEST in assets and app_updates.MANIFEST + '.sig' in assets, sorted(assets))
    manifest = updates._get(assets[app_updates.MANIFEST]['browser_download_url'], 64 * 1024)
    signature = updates._get(assets[app_updates.MANIFEST + '.sig']['browser_download_url'], 4096).decode('ascii')
    data = app_updates.validate_manifest(manifest, signature, previous)
    check(f'the manifest validates as V-Agent {previous} validates it', data['newer'] and
          data['version'] == release['tag_name'].lstrip('vV'), f"version {data['version']}, newer than {previous}")
    asset = assets.get(data['installer']['name'])
    check('the installer on GitHub has the signed name and size', bool(asset) and asset['size'] == data['installer']['size'],
          f"{data['installer']['name']} · {data['installer']['size']:,} bytes")
    check('a manifest changed by one byte is refused', refused(app_updates.validate_manifest, manifest[:-2] + b' ' + manifest[-1:], signature, previous))
    if installer and asset:
        digest = hashlib.sha256()
        request = app_updates.urllib.request.Request(asset['browser_download_url'], headers={'User-Agent': app_updates.USER_AGENT})
        with app_updates.urllib.request.urlopen(request, timeout=60) as response:
            for block in iter(lambda: response.read(1 << 20), b''):
                digest.update(block)
        check('the downloaded installer matches the signed SHA-256', digest.hexdigest() == data['installer']['sha256'])
    return manifest, signature


def minor_updates(app_signature):
    channel = components.Components()
    state = channel.check()
    available = state.get('available')
    if not available:
        check(f'minor updates for {app_updates.VERSION}', True, 'none published for this version (nothing to verify)')
        return
    check(f"minor update r{available['revision']} for {app_updates.VERSION} is found and verified", not state.get('error'),
          f"{len(available['files'])} file(s): {', '.join(f['name'] for f in available['files'])}")
    manifest = available['manifest'].encode('utf-8')
    check('a component manifest with a signature from another manifest is refused', refused(components.validate, manifest, app_signature))
    check('a component manifest for another version is refused', refused(components.validate, manifest, available['signature'], '0.0.1'))
    channel.apply()
    applied = components.ROOT / ('r%d' % available['revision'])
    mismatched = [f['name'] for f in available['files']
                  if hashlib.sha256((applied / f['name']).read_bytes()).hexdigest() != f['sha256']]
    check('applied through the real channel; every file matches its signed checksum', applied.is_dir() and not mismatched,
          mismatched or f'applied to a temporary folder ({applied.name})')


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--previous', default='1.0.4', help='validate as this installed version would')
    parser.add_argument('--installer', action='store_true', help='also download the installer and check its hash')
    parser.add_argument('--report', help='write the results as JSON here')
    args = parser.parse_args()
    try:
        _, signature = app_release(args.previous, args.installer)
        minor_updates(signature)
    except Exception as error:  # a network or GitHub failure is a failed check, with its reason
        check('release verification completed', False, f'{type(error).__name__}: {error}')
    finally:
        shutil.rmtree(DATA, ignore_errors=True)
    if args.report:
        Path(args.report).parent.mkdir(parents=True, exist_ok=True)
        Path(args.report).write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding='utf-8')
    sys.exit(1 if any(r['status'] == 'fail' for r in rows) else 0)


if __name__ == '__main__':
    main()
