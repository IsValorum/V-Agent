"""Assemble V-Agent's interface from agent/ui/ into agent/ui/dist/.

agent/ui/v-agent.html is the page skeleton. Each `/*@include <path>*/` line in it is replaced by the
file at agent/ui/<path>: the styles inside <style>, and the program parts, in order, inside one
<script>. The parts live by area in agent/ui/app/ (core, chat, models, settings, agent) and the styles in
agent/ui/styles/base/ (inside the page) and agent/ui/styles/panels/ (published as ui-panels.css). The parts share a single scope (one `initializeAgent()` program), which is why they are
assembled into the page instead of being loaded as separate scripts.

The result, agent/ui/dist/, is what both the core (http://127.0.0.1:19380) and the desktop app
serve. It is generated: edit the files in agent/ui/ and run this script again.
"""
from pathlib import Path
import json
import re
import shutil

ROOT = Path(__file__).resolve().parents[1]
UI = ROOT / 'agent' / 'ui'
DIST = UI / 'dist'
INCLUDE = re.compile(r'^\s*/\*@include ([\w./-]+)\*/\s*$')
# Files loaded on their own by the page (<link>/<script src>), published under /assets/ with the
# names the page uses.
ASSETS = {'ui-mcp.js': 'standalone/mcp.js',
          'ui-motion.js': 'standalone/motion.js', 'ui-i18n.js': 'standalone/i18n.js', 'locales.json': 'locales.json'}
LANGUAGES = ('en', 'pt', 'fr', 'de', 'ja', 'zh', 'ko', 'hi', 'id', 'vi', 'th', 'tr', 'ar')


def assemble():
    lines = []
    for line in (UI / 'v-agent.html').read_text(encoding='utf-8').split('\n'):
        match = INCLUDE.match(line)
        if not match:
            lines.append(line)
            continue
        part = (UI / match[1]).resolve()
        if not part.is_relative_to(UI.resolve()) or not part.is_file():
            raise SystemExit('Missing interface part: ' + match[1])
        lines.append(part.read_text(encoding='utf-8').rstrip('\n'))
    return '\n'.join(lines).rstrip('\n') + '\n'


# Stylesheets kept as numbered parts in one folder and published joined, in name order, as one file: the
# parts are successive layers of the same cascade, so their order is the order the rules apply in.
JOINED = {'ui-panels.css': 'styles/panels'}


def joined(folder):
    parts = sorted((UI / folder).glob('*.css'))
    if not parts:
        raise SystemExit('Missing interface parts: ' + folder)
    return '\n'.join(part.read_text(encoding='utf-8').rstrip('\n') for part in parts) + '\n'


def check_translations():
    catalog = json.loads((UI / 'locales.json').read_text(encoding='utf-8'))
    for phrase, translations in catalog.items():
        if any(not isinstance(translations.get(code), str) or not translations[code] for code in LANGUAGES):
            raise SystemExit('Incomplete translation: ' + phrase)
    return len(catalog)


def main():
    phrases = check_translations()
    page = assemble()
    if DIST.exists():
        shutil.rmtree(DIST)
    (DIST / 'assets').mkdir(parents=True)
    (DIST / 'v-agent.html').write_text(page, encoding='utf-8', newline='\n')
    for published, source in ASSETS.items():
        shutil.copy2(UI / source, DIST / 'assets' / published)
    for published, folder in JOINED.items():
        (DIST / 'assets' / published).write_text(joined(folder), encoding='utf-8', newline='\n')
    shutil.copy2(ROOT / 'docs' / 'VAL-Agent-Guide.html', DIST / 'guide.html')
    shutil.copytree(ROOT / 'agent' / 'assets' / 'branding', DIST / 'assets' / 'branding')
    print('Interface built in agent/ui/dist (%d translated phrases).' % phrases)


if __name__ == '__main__':
    main()
