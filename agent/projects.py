"""Local project selection shared by the UI, API and signed MCP workers."""
import json
import os
from pathlib import Path
import threading
import uuid
from access_policy import AccessPolicy, conversation_id


class ProjectStore:
    def __init__(self, path=None):
        self.path=Path(path or Path(os.environ.get('STRATA_AGENT_DATA',Path(__file__).parent))/'projects.json')
        self.lock=threading.RLock()

    def _read(self):
        if not self.path.exists():return {'version':1,'projects':[],'conversations':{}}
        data=json.loads(self.path.read_text(encoding='utf-8'))
        if not isinstance(data.get('projects'),list) or not isinstance(data.get('conversations'),dict):
            raise ValueError('El registro de proyectos no es válido; no se ha reemplazado.')
        return data

    def snapshot(self,chat_id=None):
        with self.lock:
            data=self._read();selected=data['conversations'].get(conversation_id(chat_id)) if chat_id else None
            return {'projects':data['projects'],'selected':selected,'conversations':data['conversations']}

    def select(self,chat_id,project_id=None,path=None):
        chat_id=conversation_id(chat_id)
        with self.lock:
            data=self._read()
            if path:
                root=Path(os.path.abspath(os.path.expanduser(path)))
                if not root.is_dir():raise ValueError('La carpeta del proyecto no existe.')
                AccessPolicy._check_links(root)
                project=next((p for p in data['projects'] if os.path.normcase(p['path'])==os.path.normcase(str(root))),None)
                if not project:
                    if len(data['projects'])>=128:raise ValueError('El registro admite hasta 128 proyectos.')
                    project={'id':uuid.uuid4().hex,'name':root.name or str(root),'path':str(root)}
                    data['projects'].append(project)
                project_id=project['id']
            if project_id and not any(p['id']==project_id for p in data['projects']):raise ValueError('Proyecto desconocido.')
            if project_id:data['conversations'][chat_id]=project_id
            else:data['conversations'].pop(chat_id,None)
            from model_import import _atomic_json
            self.path.parent.mkdir(parents=True,exist_ok=True);_atomic_json(self.path,data)
            return {'projects':data['projects'],'selected':project_id}

    def remove(self,project_id):
        with self.lock:
            data=self._read();before=len(data['projects'])
            data['projects']=[p for p in data['projects'] if p['id']!=project_id]
            if len(data['projects'])==before:raise ValueError('Proyecto desconocido.')
            data['conversations']={key:value for key,value in data['conversations'].items() if value!=project_id}
            from model_import import _atomic_json
            _atomic_json(self.path,data)
            return self.snapshot(None)
    def workspace(self,policy,chat_id):
        data=self.snapshot(chat_id)
        project=next((p for p in data['projects'] if p['id']==data['selected']),None)
        if not project:return policy.for_conversation(chat_id)
        root=Path(project['path'])
        if not root.is_dir():raise ValueError('La carpeta del proyecto ya no está disponible. Elige otra carpeta.')
        return AccessPolicy(root)


PROJECTS=ProjectStore()
