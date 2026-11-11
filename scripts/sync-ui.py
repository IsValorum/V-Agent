"""Synchronize maintained UI modules with the legacy single-file interface."""
from pathlib import Path
import json

ROOT=Path(__file__).resolve().parents[1]
target=ROOT/'agent/index.html'
source=target.read_text(encoding='utf8')
begin=source.index('function syncEngineVersions(){')
end=source.index("let modelSection='load';",begin)
controls=(ROOT/'agent/engine_controls.js').read_text(encoding='utf8')
controls=controls.replace("let activeEngine='strata',engineSnapshot=null;\n",'',1)
source=source[:begin]+controls+'\n'+source[end:]
begin=source.index('// VAL-SHELL-BEGIN')
end=source.index('// VAL-SHELL-END',begin)+len('// VAL-SHELL-END')
shell=(ROOT/'agent/ui-shell.js').read_text(encoding='utf8')
source=source[:begin]+'// VAL-SHELL-BEGIN\n'+shell+'\n// VAL-SHELL-END'+source[end:]

def inject(source,name,path,after):
    marker='// VAL-'+name+'-BEGIN'
    end_marker='// VAL-'+name+'-END'
    body=(ROOT/'agent'/path).read_text(encoding='utf8')
    if marker in source:
        begin=source.index(marker)
        end=source.index(end_marker,begin)+len(end_marker)
        return source[:begin]+marker+'\n'+body+'\n'+end_marker+source[end:]
    return source.replace(after,after+'\n'+marker+'\n'+body+'\n'+end_marker,1)

source=inject(source,'WINDOWS','floating-windows.js','// VAL-SHELL-END')
source=inject(source,'TOOLS','ui-tools.js','// VAL-WINDOWS-END')
source=inject(source,'ART-DECO','ui-palette.js','// VAL-TOOLS-END')
source=inject(source,'LOAD-SETTINGS','ui-load-settings.js','// VAL-ART-DECO-END')
source=inject(source,'PLUGINS','ui-plugins.js','// VAL-LOAD-SETTINGS-END')
source=inject(source,'TOUR','ui-tour.js','// VAL-PLUGINS-END')
source=inject(source,'MODELS','ui-models.js','// VAL-TOUR-END')
catalog=json.loads((ROOT/'agent/locales.json').read_text(encoding='utf8'))
for phrase,translations in catalog.items():
    if any(not isinstance(translations.get(code),str) or not translations[code] for code in ('en','pt','fr','de')):
        raise ValueError('Incomplete translation: '+phrase)
if source!=target.read_text(encoding='utf8'):target.write_text(source,encoding='utf8')
desktop=ROOT/'desktop/web'
assets=desktop/'assets'
assets.mkdir(parents=True,exist_ok=True)
(desktop/'index.html').write_text(source,encoding='utf8')
guide=ROOT/'docs/VAL-Agent-Guide.html'
if guide.is_file():
    (ROOT/'agent/guide.html').write_text(guide.read_text(encoding='utf8'),encoding='utf8')
    (desktop/'guide.html').write_text(guide.read_text(encoding='utf8'),encoding='utf8')
for name in ('ui-panels.css','ui-mcp.js','ui-motion.js','ui-i18n.js','locales.json'):
    (assets/name).write_text((ROOT/'agent'/name).read_text(encoding='utf8'),encoding='utf8')
import shutil
shutil.copytree(ROOT/'agent/assets/branding',assets/'branding',dirs_exist_ok=True)
print(f'UI synchronized; {len(catalog)} translated phrases. Tauri web assets updated.')
