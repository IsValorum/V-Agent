"""Stage clean, personal-data-free files for the official V-Agent build.

The developer checkout keeps its own model profiles, seeds and engines. The release build instead
uses the empty data written here (build/release-data), so installers never carry anyone's models,
preferences, regions or MCP settings. Engines are not bundled: V-Agent downloads the official build
that matches the user's hardware on first run.
"""
import json
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'build' / 'release-data'


def main():
    if OUT.exists():
        shutil.rmtree(OUT)
    (OUT / 'agent').mkdir(parents=True)
    profiles = json.loads((ROOT / 'agent' / 'model-profiles.json').read_text(encoding='utf-8'))
    clean = {'version': profiles.get('version', 1), 'profiles': profiles['profiles'], 'models': {}, 'ignored_models': []}
    (OUT / 'agent' / 'model-profiles.json').write_text(json.dumps(clean, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    (OUT / 'agent' / 'creator-recommendations.json').write_text('{}\n', encoding='utf-8')
    (OUT / 'agent' / 'template-provenance.json').write_text('[]\n', encoding='utf-8')
    # Only the runtime pieces that are not engines: process isolation and Node.js for JS checks.
    runtime = OUT / 'runtime'
    shutil.copytree(ROOT / 'runtime' / 'mxc', runtime / 'mxc')
    if (ROOT / 'runtime' / 'node.exe').is_file():
        shutil.copy2(ROOT / 'runtime' / 'node.exe', runtime / 'node.exe')
    print('Release data staged in', OUT.relative_to(ROOT))


if __name__ == '__main__':
    main()
