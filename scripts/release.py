"""Maintainer tool: signing key and signed update manifests for V-Agent releases.

  python scripts/release.py --init-key
      Create the Ed25519 signing key (once). The private key is stored OUTSIDE the project, in
      %USERPROFILE%/.v-agent/update-signing-key.pem, and its public half is written into
      agent/app_updates.py. Back the private key up somewhere safe: without it no update can be
      published, and anyone who has it can publish updates.

  python scripts/release.py --components FOLDER --revision N [--notes "text"]
      Minor update (MCP servers, tool descriptions...) for the current app version without a new
      installer. FOLDER holds the changed files (only names allowed in agent/components.py). Writes
      v-agent-components.json and .sig into FOLDER; upload the files and both to a GitHub release
      tagged components-<version>-r<N>.

  python scripts/release.py --sign path/to/V-Agent_1.0.1_x64-setup.exe [--notes "text"]
      Write v-agent-update.json and v-agent-update.json.sig next to the installer. Upload the
      installer and both files to a GitHub release of the repository set in agent/app_updates.py.
"""
import argparse
import base64
import hashlib
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
UPDATES = ROOT / 'agent' / 'app_updates.py'
KEY = Path.home() / '.v-agent' / 'update-signing-key.pem'


def load_private():
    from cryptography.hazmat.primitives import serialization
    if not KEY.is_file():
        sys.exit('No signing key. Run: python scripts/release.py --init-key')
    return serialization.load_pem_private_key(KEY.read_bytes(), password=None)


def public_b64(private):
    from cryptography.hazmat.primitives import serialization
    raw = private.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    return base64.b64encode(raw).decode('ascii')


def init_key():
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    if KEY.exists():
        private = load_private()
        print('Signing key already exists:', KEY)
    else:
        KEY.parent.mkdir(parents=True, exist_ok=True)
        private = Ed25519PrivateKey.generate()
        KEY.write_bytes(private.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                              serialization.NoEncryption()))
        print('Created signing key:', KEY)
    source = UPDATES.read_text(encoding='utf-8')
    updated = re.sub(r"PUBLIC_KEY = '[^']*'", "PUBLIC_KEY = '%s'" % public_b64(private), source, count=1)
    UPDATES.write_text(updated, encoding='utf-8')
    print('Public key embedded in', UPDATES.relative_to(ROOT))


def sign(installer, notes):
    sys.path.insert(0, str(ROOT / 'agent'))
    source = UPDATES.read_text(encoding='utf-8')
    version = re.search(r"VERSION = '([^']+)'", source)[1]
    repository = re.search(r"REPOSITORY = '([^']*)'", source)[1]
    if not repository:
        sys.exit('Set REPOSITORY = "owner/repo" in agent/app_updates.py before publishing.')
    private = load_private()
    if public_b64(private) not in source:
        sys.exit('The embedded public key does not match your private key. Run --init-key.')
    installer = Path(installer).resolve()
    expected = 'V-Agent_%s_x64-setup.exe' % version
    if installer.name != expected:
        sys.exit('Installer name must be %s (version from app_updates.py).' % expected)
    data = installer.read_bytes()
    manifest = {'product': 'V-Agent', 'version': version, 'repository': repository, 'notes': notes or '',
                'installer': {'name': installer.name, 'size': len(data), 'sha256': hashlib.sha256(data).hexdigest()}}
    body = json.dumps(manifest, ensure_ascii=False, indent=2).encode('utf-8')
    (installer.parent / 'v-agent-update.json').write_bytes(body)
    (installer.parent / 'v-agent-update.json.sig').write_text(base64.b64encode(private.sign(body)).decode('ascii'), encoding='ascii')
    print('Signed manifest written next to', installer.name)


def sign_components(folder, revision, notes):
    sys.path[:0] = [str(ROOT / 'agent'), str(ROOT)]
    from components import ALLOWED
    source = UPDATES.read_text(encoding='utf-8')
    version = re.search(r"VERSION = '([^']+)'", source)[1]
    private = load_private()
    if public_b64(private) not in source:
        sys.exit('The embedded public key does not match your private key. Run --init-key.')
    folder = Path(folder).resolve()
    files = [p for p in sorted(folder.iterdir()) if p.is_file() and not p.name.startswith('v-agent-components.json')]
    bad = [p.name for p in files if p.name not in ALLOWED]
    if bad or not files:
        sys.exit('Only these files can be shipped as components: %s. Not allowed: %s' % (', '.join(sorted(ALLOWED)), ', '.join(bad) or 'none given'))
    manifest = {'product': 'V-Agent', 'channel': 'components', 'app_version': version, 'revision': int(revision), 'notes': notes or '',
                'files': [{'name': p.name, 'size': p.stat().st_size, 'sha256': hashlib.sha256(p.read_bytes()).hexdigest()} for p in files]}
    body = json.dumps(manifest, ensure_ascii=False, indent=2).encode('utf-8')
    (folder / 'v-agent-components.json').write_bytes(body)
    (folder / 'v-agent-components.json.sig').write_text(base64.b64encode(private.sign(body)).decode('ascii'), encoding='ascii')
    print('Signed %d component(s), revision %s for V-Agent %s. Tag the release: components-%s-r%s' % (len(files), revision, version, version, revision))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--init-key', action='store_true')
    parser.add_argument('--sign')
    parser.add_argument('--notes', default='')
    parser.add_argument('--components')
    parser.add_argument('--revision', type=int)
    args = parser.parse_args()
    if args.init_key:
        init_key()
    elif args.sign:
        sign(args.sign, args.notes)
    elif args.components:
        if not args.revision:sys.exit('--revision N is required (higher than the last published one).')
        sign_components(args.components, args.revision, args.notes)
    else:
        parser.print_help()
