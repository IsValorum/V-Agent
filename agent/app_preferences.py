"""Local client preferences, independent from models and appearance."""
import json
from pathlib import Path
import threading
import time
import uuid
from runtime_paths import SETTINGS_ROOT
from ui_preferences import atomic_json

LANGUAGES=('es','en','pt','fr','de')

class AppPreferences:
    def __init__(self,path=None):
        self.path=Path(path) if path else SETTINGS_ROOT/'app-preferences.json'
        self.backup=self.path.with_suffix(self.path.suffix+'.bak')
        self.lock=threading.RLock()
    def _read(self):
        broken=[]
        for path in (self.path,self.backup):
            try:
                data=json.loads(path.read_text(encoding='utf8'))
                if not isinstance(data,dict):raise ValueError('Invalid preferences')
                return data,broken
            except FileNotFoundError:continue
            except (OSError,ValueError):broken.append(path)
        return {},broken
    def get(self):
        with self.lock:
            data,_=self._read()
            language=data.get('language') if isinstance(data,dict) else None
            duration=data.get('animation_ms') if isinstance(data,dict) else None
            return {'language':language if language in LANGUAGES else 'es',
                    'agent_profile':data.get('agent_profile','balanced') if isinstance(data,dict) and data.get('agent_profile','balanced') in ('light','balanced','advanced') else 'balanced',
                    'windows':data.get('windows',{}) if isinstance(data,dict) else {},
                    'decoration':data.get('decoration',{}) if isinstance(data,dict) else {},
                    'animation_ms':duration if type(duration) is int and 100<=duration<=1600 else 620,
                    'tour_done':data.get('tour_done') is True if isinstance(data,dict) else False}
    def save(self,body):
        if not isinstance(body,dict) or not body or set(body)-{'language','animation_ms','agent_profile','decoration','windows','tour_done'}:
            raise ValueError('Preferencia no admitida.')
        if 'language' in body and body['language'] not in LANGUAGES:raise ValueError('Idioma no admitido.')
        if 'tour_done' in body and type(body['tour_done']) is not bool:raise ValueError('Invalid tutorial state.')
        if 'animation_ms' in body and (type(body['animation_ms']) is not int or not 100<=body['animation_ms']<=1600):
            raise ValueError('Duración no admitida.')
        if 'agent_profile' in body and body['agent_profile'] not in ('light','balanced','advanced'):raise ValueError('Perfil no admitido.')
        if 'windows' in body:
            windows=body['windows']
            if not isinstance(windows,dict) or len(windows)>12:raise ValueError('Invalid window settings.')
            for key,box in windows.items():
                if key not in ('settings','model','tools','project','import','console','browser') or not isinstance(box,dict) or set(box)!={'width','height'}:raise ValueError('Invalid window.')
                if any(type(v) is not int or not 160<=v<=5000 for v in box.values()):raise ValueError('Invalid window size.')
        if 'decoration' in body:
            d=body['decoration']
            if not isinstance(d,dict) or set(d)-{'style','intensity','color','palette','logo','motif','background','version','amoled','logoSize','appIcon','showGreeting','paletteThemes','uiStyle','buttonStyle'}:raise ValueError('Invalid decoration.')
            if d.get('style') != 'none' or type(d.get('intensity')) is not int or not 0<=d['intensity']<=100:raise ValueError('Invalid decoration.')
            palettes=('gold','silver','jade','blue','rose','ruby','violet','ivory')
            for key,values in [('palette',(*palettes,'custom')),('logo',palettes),('appIcon',('follow',*palettes)),('motif',('corners','rays','steps')),('background',('collection','wallpaper'))]:
                if key in d and d[key] not in values:raise ValueError('Invalid decoration option: '+key)
            if 'version' in d and (type(d['version']) is not int or d['version']!=2):raise ValueError('Invalid decoration version.')
            if 'showGreeting' in d and type(d['showGreeting']) is not bool:raise ValueError('Invalid greeting setting.')
            if 'uiStyle' in d and d['uiStyle'] not in ('glass','soft','deco'):raise ValueError('Invalid interface style.')
            if 'buttonStyle' in d and d['buttonStyle'] not in ('tint','outline'):raise ValueError('Invalid button style.')
            if 'amoled' in d and type(d['amoled']) is not bool:raise ValueError('Invalid AMOLED setting.')
            if 'logoSize' in d and (type(d['logoSize']) is not int or not 64<=d['logoSize']<=360):raise ValueError('Invalid logo size.')
            import re
            if not re.fullmatch(r'#[0-9a-fA-F]{6}',str(d.get('color',''))):raise ValueError('Invalid color.')
            if 'paletteThemes' in d:
                themes=d['paletteThemes']; color_keys={'accent','bg','panel','text','codeBg','userBg','g1','g2','g3'}
                if not isinstance(themes,dict) or set(themes)-set(palettes):raise ValueError('Invalid saved palettes.')
                for modes in themes.values():
                    if not isinstance(modes,dict) or set(modes)!={'night','day'}:raise ValueError('Invalid palette modes.')
                    for values in modes.values():
                        if not isinstance(values,dict) or set(values)!=color_keys|{'gradient','strength'}:raise ValueError('Invalid palette colors.')
                        if any(not isinstance(values[k],str) or not re.fullmatch(r'#[0-9a-fA-F]{6}',values[k]) for k in color_keys):raise ValueError('Invalid palette color.')
                        if values['gradient'] not in ('none','linear','radial','mesh') or type(values['strength']) is not int or not 0<=values['strength']<=100:raise ValueError('Invalid palette gradient.')
        with self.lock:
            self.path.parent.mkdir(parents=True,exist_ok=True)
            previous,broken=self._read()
            merged={**self.get(),**body}
            if 'windows' in body:merged['windows']={**(previous.get('windows') if isinstance(previous.get('windows'),dict) else {}),**body['windows']}
            for path in broken:
                if path.exists():path.replace(path.with_name(path.name+'.corrupt-'+time.strftime('%Y%m%d-%H%M%S')+'-'+uuid.uuid4().hex[:6]))
            if previous:atomic_json(self.backup,previous)
            atomic_json(self.path,merged)
            return self.get()
