"""Durable appearance storage; independent from model state and browser storage."""
import copy
import json
import math
import os
from pathlib import Path
import re
import tempfile
import threading
import time
import uuid

COLORS = ('accent','bg','panel','text','g1','g2','g3','codeBg','userBg')
RANGES = {'messageRadius':(0,36),'composerRadius':(0,40),'lineHeight':(130,210),'blur':(0,48),'alpha':(40,100),'composerAlpha':(40,100),'drawerAlpha':(60,100),'radius':(0,28),'strength':(0,100),'angle':(0,360),'backgroundBlur':(0,100),'outsideOpacity':(0,100),'textShadow':(0,100),'responseOpacity':(0,100),'responseBlur':(0,32),'responseRadius':(0,36),'grain':(0,30),'border':(0,35),'shadow':(0,100),'sidebarWidth':(200,340),'chatWidth':(560,1200),'fontSize':(12,20)}
ENUMS = {'gradient':('none','linear','radial','mesh'),'font':('system','rounded','mono'),'density':('compact','normal','airy')}
FIELDS = (*COLORS,*RANGES,*ENUMS,'showMark')
CONTROL_IDS = ('attach','modelBtn','responseBtn','ctxBtn','mcpBtn','scopeBtn','send')
DEFAULT_COMPOSER = {'left':list(CONTROL_IDS[:-1]),'right':['send'],'emptyRaised':True}
PATHS = {'mode','name','composerLayout'} | {mode+'.'+field for mode in ('night','day') for field in FIELDS}

def validate_composer(value):
    if value is None:return copy.deepcopy(DEFAULT_COMPOSER)
    if not isinstance(value,dict):raise ValueError('Distribución no válida.')
    left,right=value.get('left'),value.get('right')
    if not isinstance(left,list) or not isinstance(right,list):raise ValueError('Faltan los lados del cuadro de mensaje.')
    controls=left+right
    if len(controls)!=len(CONTROL_IDS) or any(not isinstance(key,str) for key in controls) or set(controls)!=set(CONTROL_IDS):
        raise ValueError('Los botones deben aparecer una sola vez.')
    if not isinstance(value.get('emptyRaised'),bool):raise ValueError('Posición del chat vacío no válida.')
    return {'left':left.copy(),'right':right.copy(),'emptyRaised':value['emptyRaised']}

def validate_theme(value):
    if not isinstance(value,dict) or value.get('mode') not in ('night','day'):
        raise ValueError('Tema no válido.')
    name=value.get('name')
    if not isinstance(name,str) or not 1<=len(name.strip())<=32:
        raise ValueError('El nombre debe tener entre 1 y 32 caracteres.')
    theme={'mode':value['mode'],'name':name.strip(),'visualVersion':2}
    theme['composerLayout']=validate_composer(value.get('composerLayout'))
    for mode in ('night','day'):
        source=value.get(mode)
        if not isinstance(source,dict):raise ValueError('Falta el modo '+mode+' del tema.')
        target={}
        for field in COLORS:
            color=source.get(field,({'codeBg':'#141a1e','userBg':'#263a34'} if mode=='night' else {'codeBg':'#f4f7f5','userBg':'#e2eee8'}).get(field))
            if not isinstance(color,str) or not re.fullmatch(r'#[0-9a-fA-F]{6}',color):raise ValueError('Color no válido: '+field)
            target[field]=color
        for field,(minimum,maximum) in RANGES.items():
            number=source.get(field,{'messageRadius':12,'composerRadius':24,'lineHeight':165,'textShadow':0,'responseOpacity':82,'responseBlur':8,'responseRadius':16,'outsideOpacity':70 if mode=='night' else 82}.get(field))
            if isinstance(number,bool) or not isinstance(number,(int,float)) or not math.isfinite(number) or not minimum<=number<=maximum:
                raise ValueError('Valor fuera de rango: '+field)
            target[field]=round(number)
        for field,choices in ENUMS.items():
            if source.get(field) not in choices:raise ValueError('Opción no válida: '+field)
            target[field]=source[field]
        if not isinstance(source.get('showMark'),bool):raise ValueError('Opción showMark no válida.')
        target['showMark']=source['showMark'];theme[mode]=target
    return theme

def atomic_json(path,value):
    path.parent.mkdir(parents=True,exist_ok=True)
    temporary=None
    try:
        with tempfile.NamedTemporaryFile(mode='w',encoding='utf-8',dir=path.parent,prefix='.'+path.name,suffix='.tmp',delete=False) as stream:
            temporary=Path(stream.name)
            json.dump(value,stream,ensure_ascii=False,indent=2);stream.write('\n');stream.flush();os.fsync(stream.fileno())
        os.replace(temporary,path)
    finally:
        if temporary is not None and temporary.exists():temporary.unlink(missing_ok=True)

class AppearanceStore:
    def __init__(self,path):
        self.path=Path(path);self.backup=self.path.with_suffix(self.path.suffix+'.bak');self.lock=threading.Lock()

    def _read(self):
        broken=[]
        for path in (self.path,self.backup):
            if not path.exists():continue
            try:
                record=json.loads(path.read_text(encoding='utf-8-sig'))
                record['theme']=validate_theme(record['theme'])
                if not isinstance(record.get('revision'),int) or record['revision']<1:raise ValueError('Invalid revision')
                record['clients']={key:value for key,value in (record.get('clients') or {}).items() if isinstance(key,str) and isinstance(value,int) and not isinstance(value,bool) and value>0} if isinstance(record.get('clients'),dict) else {}
                return record,bool(broken),broken
            except (OSError,ValueError,KeyError,TypeError):broken.append(path)
        return None,False,broken

    @staticmethod
    def _public(record,recovered=False,broken=False):
        return {'theme':copy.deepcopy(record['theme']) if record else None,'revision':record['revision'] if record else 0,
                'updated_at_ms':record.get('updated_at_ms') if record else None,'recovered':recovered,'recovery_needed':bool(broken and not record)}

    def get(self,client_id=None):
        with self.lock:
            record,recovered,broken=self._read()
            return {**self._public(record,recovered,broken),"last_sequence":record["clients"].get(client_id,0) if record else 0}

    def save(self,body):
        if not isinstance(body,dict):raise ValueError('Solicitud no válida.')
        theme=validate_theme(body.get('theme'))
        changes=body.get('changed')
        if not isinstance(changes,list) or len(changes)>len(PATHS) or any(not isinstance(path,str) or path not in PATHS for path in changes):
            raise ValueError('Campos de tema no válidos.')
        client=body.get('client_id');sequence=body.get('sequence')
        if not isinstance(client,str) or not re.fullmatch(r'[A-Za-z0-9_-]{16,80}',client):raise ValueError('Identificador no válido.')
        if isinstance(sequence,bool) or not isinstance(sequence,int) or not 1<=sequence<=2**53-1:raise ValueError('Secuencia no válida.')
        with self.lock:
            previous,recovered,broken=self._read()
            if previous and (body.get('seed') or sequence<=previous['clients'].get(client,0)):
                return {**self._public(previous,recovered),'ignored':True}
            if previous:
                merged=copy.deepcopy(previous['theme'])
                for path in set(changes):
                    if '.' in path:
                        mode,field=path.split('.');merged[mode][field]=theme[mode][field]
                    else:merged[path]=theme[path]
            else:merged=theme
            clients=copy.deepcopy(previous['clients']) if previous else {};clients.pop(client,None);clients[client]=sequence
            clients=dict(list(clients.items())[-64:])
            record={'version':1,'revision':previous['revision']+1 if previous else 1,'updated_at_ms':int(time.time()*1000),'theme':merged,'clients':clients}
            # Preserve unreadable files before recovering with a valid saved/local theme.
            for path in broken:
                quarantine=path.with_name(path.name+'.corrupt-'+time.strftime('%Y%m%d-%H%M%S')+'-'+uuid.uuid4().hex[:6])
                path.replace(quarantine)
            if previous:atomic_json(self.backup,previous)
            atomic_json(self.path,record)
            return self._public(record)
