"""Per-model user settings, separate from creator sources and engine lifecycle."""
import copy
import json
import math
from pathlib import Path
import threading
from ui_preferences import atomic_json

from runtime_paths import SETTINGS_ROOT,CONFIG_ROOT,SOURCE_ROOT
BASE = SETTINGS_ROOT
RANGES = {'temperature':(0,2),'top_p':(0,1),'top_k':(0,1000),'min_p':(0,1),
          'repetition_penalty':(.8,2),'presence_penalty':(-2,2),'frequency_penalty':(-2,2),
          'max_tokens':(0,262144),'seed':(0,2147483647)}

class ModelPreferences:
    def __init__(self, path=BASE/'model-preferences.json'):
        self.path = Path(path)
        self.lock = threading.RLock()
        self.load_error = None
        try:
            self.records = json.loads(self.path.read_text(encoding='utf-8')) if self.path.exists() else {}
            if not isinstance(self.records,dict) or any(not isinstance(value,dict) for value in self.records.values()):
                raise ValueError('Formato de preferencias no válido.')
        except (OSError,ValueError) as error:
            self.records = {}
            self.load_error = str(error)
        # The user's copy is created on first start; before that (fresh clone, tests) use the bundled one.
        source = CONFIG_ROOT/'agent/creator-recommendations.json'
        if not source.is_file():source = SOURCE_ROOT/'agent/creator-recommendations.json'
        self.creators = json.loads(source.read_text(encoding='utf-8'))

    def load(self, model):
        with self.lock:
            return copy.deepcopy((self.records.get(model) or {}).get('load') or {})

    def get(self, model, baseline):
        with self.lock:
            creator = self.creators.get(model, {'sampling':{},'kind':'unpublished','label':'Sin recomendación pública verificada'})
            default = copy.deepcopy(baseline)
            default['sampling'].update(creator['sampling'])
            default['effort'] = creator.get('effort',default['effort'])
            # Existing explicit user preference: protect repeated code syntax.
            default['sampling']['repetition_penalty'] = 1.0
            saved = copy.deepcopy(self.records.get(model, {}))
            result = {**default, **saved, 'sampling':{**default['sampling'],**saved.get('sampling',{})}}
            return {**result, 'creator':copy.deepcopy(creator), 'saved':bool(saved), 'storage_warning':self.load_error}

    def save(self, model, settings):
        if not isinstance(settings,dict):raise ValueError('Ajustes no válidos.')
        allowed = {'sampling','effort','rounds','context','kv','load','draft'}
        if set(settings)-allowed:raise ValueError('Ajuste desconocido.')
        with self.lock:
            entry = copy.deepcopy(self.records.get(model, {}))
            for key,value in settings.items():
                if key=='load':
                    from load_settings import validate
                    entry[key]=validate(value,entry.get(key))
                elif key=='draft':
                    from draft_models import validate
                    entry[key]=validate(value,entry.get(key))
                elif key=='sampling':
                    if not isinstance(value,dict) or set(value)-RANGES.keys():raise ValueError('Muestreo no válido.')
                    for name,number in value.items():
                        low,high = RANGES[name]
                        if isinstance(number,bool) or not isinstance(number,(int,float)) or not math.isfinite(number) or not low<=number<=high:raise ValueError('Valor fuera de rango: '+name)
                        if name in ('top_k','seed','max_tokens') and int(number)!=number:raise ValueError('Valor entero requerido: '+name)
                    entry[key] = {**entry.get(key,{}),**value}
                elif key=='kv':
                    from kv_settings import FORMATS
                    if not isinstance(value,str) or value not in FORMATS:raise ValueError('Formato KV no válido.')
                    entry[key] = value
                elif key=='effort':
                    if value not in ('default','none','think','minimal','low','medium','high','xhigh'):raise ValueError('Razonamiento no válido.')
                    entry[key] = value
                else:
                    low,high = (2048,262144) if key=='context' else (2,100)
                    if type(value) is not int or not low<=value<=high:raise ValueError('Valor fuera de rango: '+key)
                    entry[key] = value
            records = {**self.records,model:entry}
            if self.load_error and self.path.exists():
                backup = self.path.with_suffix('.invalid.json')
                if not backup.exists():backup.write_bytes(self.path.read_bytes())
            atomic_json(self.path,records)
            self.records = records
            self.load_error = None
            return copy.deepcopy(entry)

STORE = ModelPreferences()
