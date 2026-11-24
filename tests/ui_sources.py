"""Interface sources for tests, by file name: the parts live by area in agent/ui/app/<area>/.

The old agent/ui/app/shell.js was split into several parts (settings hub, composer menu, client preferences,
agent controls and modes, engines and updates, window chrome); asking for "shell.js" returns them joined in
the order the page includes them, so a test that searched the old file still finds the same text.
"""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
UI = ROOT / 'agent' / 'ui'
_INCLUDE = re.compile(r'^\s*/\*@include (app/[\w./-]+\.js)\*/\s*$', re.M)
SHELL_PARTS = ('settings/settings-hub.js', 'chat/composer-menu.js', 'settings/client-preferences.js',
               'agent/agent-controls.js', 'agent/agent-modes.js', 'models/engines-and-updates.js',
               'core/window-chrome.js')


def ui_path(name):
    """agent/ui/app/<area>/<name> for a bare file name such as 'composer.js'."""
    found = sorted((UI / 'app').rglob(Path(name).name))
    if len(found) != 1:
        raise FileNotFoundError(f'{name}: {len(found)} interface files with that name')
    return found[0]


def ui_source(name):
    if Path(name).name == 'shell.js':
        return '\n'.join((UI / 'app' / part).read_text(encoding='utf-8').rstrip('\n') for part in SHELL_PARTS) + '\n'
    return ui_path(name).read_text(encoding='utf-8')


def program_order():
    """The program parts in the order the page includes them."""
    return _INCLUDE.findall((UI / 'v-agent.html').read_text(encoding='utf-8'))


def ui_stylesheet(name):
    """'panels.css' or 'base.css': the numbered parts in agent/ui/styles/<name without .css>/, joined in order."""
    folder = UI / 'styles' / Path(name).stem
    return '\n'.join(part.read_text(encoding='utf-8').rstrip('\n') for part in sorted(folder.glob('*.css'))) + '\n'
