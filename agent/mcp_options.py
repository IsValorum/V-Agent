"""User-owned MCP defaults. Read by workers, never appended to model prompts."""
import copy
import json
from pathlib import Path
import threading
from runtime_paths import SETTINGS_ROOT
from ui_preferences import atomic_json

# (default, minimum, maximum) or (default, allowed values).
SCHEMA = {
    'duckduckgo': {
        'region': ('wt-wt', ('wt-wt','sv-es','us-en','uk-en','es-es','mx-es','ar-es','de-de','fr-fr','br-pt','pt-pt','jp-jp')),
        'language': ('auto', ('auto','en','es','pt','fr','de','ja')),
        'timelimit': ('', ('','d','w','m','y')),
        'safesearch': ('moderate', ('on','moderate','off')),
        'count': (5, 1, 10), 'filter_ads': (True, bool),
        'timeout': (10, 5, 30), 'visit_tokens': (1500, 0, 1000000),
        'include_links': (True, bool), 'include_tables': (True, bool),
        'max_result_chars': (0, 0, 1000000),
    },
    'pc': {'command_timeout': (60, 5, 300), 'max_result_chars': (8000, 1000, 1000000)},
    'hf': {'command_timeout': (60, 5, 300), 'max_result_chars': (12000, 1000, 1000000)},
    'documents': {
        'extract_mode': ('auto', ('auto', 'markdown', 'text', 'tables')),
        'max_pages': (0, 0, 5000),
        'max_chars': (24000, 0, 1000000),
        'include_tables': (True, bool),
        'ocr_scanned': (True, bool),
        'include_metadata': (True, bool),
    },
}

def defaults():
    return {server:{key:rule[0] for key,rule in fields.items()} for server,fields in SCHEMA.items()}

def validate(body):
    if not isinstance(body,dict) or set(body)-set(SCHEMA): raise ValueError('Unknown MCP configuration.')
    for server,fields in body.items():
        if not isinstance(fields,dict) or set(fields)-set(SCHEMA[server]): raise ValueError('Unknown MCP option.')
        for key,value in fields.items():
            rule=SCHEMA[server][key]
            valid=(type(value) is int and rule[1]<=value<=rule[2]) if len(rule)==3 else (type(value) is bool if rule[1] is bool else isinstance(value,str) and value in rule[1])
            if not valid: raise ValueError('Invalid MCP option: '+server+'.'+key)
    return body

class MCPOptions:
    def __init__(self,path=None):
        self.path=Path(path) if path is not None else SETTINGS_ROOT/'mcp-options.json'
        self.lock=threading.RLock();self.signature=None;self.cached=defaults()
    def get(self):
        with self.lock:
            try:
                stat=self.path.stat();signature=(stat.st_mtime_ns,stat.st_size)
                if signature!=self.signature:
                    body=validate(json.loads(self.path.read_text(encoding='utf8')))
                    self.cached=defaults()
                    for server,fields in body.items(): self.cached[server].update(fields)
                    self.signature=signature
            except (OSError,ValueError,TypeError):
                self.cached=defaults();self.signature=None
            return copy.deepcopy(self.cached)
    def save(self,body):
        validate(body)
        with self.lock:
            settings=self.get()
            for server,fields in body.items(): settings[server].update(fields)
            atomic_json(self.path,settings);self.signature=None
            return self.get()

OPTIONS=MCPOptions()
def options(server): return OPTIONS.get().get(server,{})
