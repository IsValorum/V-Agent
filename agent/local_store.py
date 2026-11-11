"""Local persistence services usable by web, CLI or future desktop clients."""
import copy
from contextlib import contextmanager
import json
import os
from pathlib import Path
import queue
import secrets
import sqlite3
import threading
import time
from access_policy import conversation_id
from runtime_paths import DATA_ROOT
from ui_preferences import atomic_json

DATA = Path(os.environ.get('STRATA_AGENT_DATA') or DATA_ROOT).resolve()

class Conflict(ValueError):pass

class Sessions:
    def __init__(self, root=DATA):
        self.root=Path(root);self.root.mkdir(parents=True,exist_ok=True)
        self.db=self.root/'sessions.sqlite3'
        with self.connect() as db:
            db.executescript('PRAGMA journal_mode=WAL; CREATE TABLE IF NOT EXISTS chats(id TEXT PRIMARY KEY,revision INTEGER NOT NULL,body TEXT NOT NULL,deleted INTEGER NOT NULL DEFAULT 0);')
    @contextmanager
    def connect(self):
        db=sqlite3.connect(self.db,timeout=15)
        try:
            db.execute('PRAGMA synchronous=FULL')
            with db:yield db
        finally:db.close()
    def list(self):
        with self.connect() as db:
            return [dict(json.loads(body),revision=revision) for revision,body in db.execute('SELECT revision,body FROM chats WHERE deleted=0')]
    def get(self, ident):
        with self.connect() as db:row=db.execute('SELECT revision,body FROM chats WHERE id=? AND deleted=0',(ident,)).fetchone()
        return dict(json.loads(row[1]),revision=row[0]) if row else None
    def save(self, chat, expected=None, importing=False, api_fallback=False):
        chat=copy.deepcopy(chat);ident=conversation_id(chat.get('id'))
        if not isinstance(chat.get('messages'),list):raise ValueError('Mensajes no válidos.')
        chat.pop('revision',None)
        chat.pop('_source',None)
        if api_fallback:chat['_source']='api_fallback'
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row=db.execute('SELECT revision,body,deleted FROM chats WHERE id=?',(ident,)).fetchone()
            if importing and row:
                old=json.loads(row[1])
                if not row[2] and old.get('_source')=='api_fallback' and chat.get('ts',0)>=old.get('ts',0):expected=row[0]
                else:return dict(old,revision=row[0]) if not row[2] else None
            if row and (row[2] or expected!=row[0]):raise Conflict('El chat cambió en otra ventana. Conserva esta copia y vuelve a abrirlo.')
            if not row and expected not in (None,0):raise Conflict('Revisión no válida.')
            revision=(row[0] if row else 0)+1
            db.execute('INSERT OR REPLACE INTO chats VALUES(?,?,?,0)',(ident,revision,json.dumps(chat,ensure_ascii=False)))
            return dict(chat,revision=revision)
    def delete(self, ident, expected):
        conversation_id(ident)
        with self.connect() as db:
            cursor=db.execute('UPDATE chats SET deleted=1,revision=revision+1 WHERE id=? AND revision=? AND deleted=0',(ident,expected))
            if not cursor.rowcount:raise Conflict('El chat cambió antes de borrarlo.')
    def recover_runs(self, run_id=None):
        """Recover completed/interrupted output only over the exact originating revision."""
        folder=self.root/'runs'
        if run_id is not None and (not isinstance(run_id,str) or len(run_id)!=32 or any(c not in '0123456789abcdef' for c in run_id)):
            raise ValueError('Invalid run ID.')
        records=[folder/run_id/'meta.json'] if run_id else sorted(folder.glob('*/meta.json'))
        for meta in records:
            try:
                record=json.loads(meta.read_text(encoding='utf-8'))
                if record.get('acknowledged') or record.get('pid')==os.getpid() and record.get('status')=='running':continue
                chat=self.get(record['conversation_id'])
                if not chat or chat['revision']!=record.get('revision'):
                    record['acknowledged']=True;atomic_json(meta,record);continue
                reply={'role':'assistant','content':'','reasoning_content':'','run_id':record['id'],'status':'stopped'}
                traces={}
                for line in (meta.parent/'events.sse').read_text(encoding='utf-8',errors='replace').splitlines():
                    if not line.startswith('data:'):continue
                    try:event=json.loads(line[5:])
                    except ValueError:continue
                    kind=event.get('type')
                    if kind in ('content','reasoning'):reply['content' if kind=='content' else 'reasoning_content']+=event.get('text','')
                    elif kind in ('content_fixed','reasoning_fixed'):reply['content' if kind=='content_fixed' else 'reasoning_content']=event.get('text','')
                    elif kind in ('tool','tool_draft','tool_state','tool_result'):
                        trace=traces.setdefault(event['id'],{})
                        if kind=='tool_draft':trace['draftText']=trace.get('draftText','')+event.get('delta','')
                        trace.update({k:v for k,v in event.items() if k not in ('type','delta')})
                    elif kind=='done':
                        reply['content']=event.get('content',reply['content'])
                        if not reply['reasoning_content']:reply['reasoning_content']=event.get('reasoning_content','')
                        reply.pop('status',None)
                    elif kind=='usage':reply['usage']=event.get('usage') or {}
                    if isinstance(event.get('usage'),dict):reply['usage']=event['usage']
                    timings=event.get('timings')
                    if isinstance(timings,dict):
                        rates={key:timings.get(source) for key,source in [('decode','predicted_per_second'),('prefill','prompt_per_second')] if isinstance(timings.get(source),(int,float)) and not isinstance(timings.get(source),bool) and 0<timings[source]<1e9}
                        if rates:reply['performance']={**reply.get('performance',{}),**rates}
                    for choice in event.get('choices',[]):
                        delta=choice.get('delta') or {}
                        reply['content']+=delta.get('content') or '';reply['reasoning_content']+=delta.get('reasoning_content') or ''
                        if choice.get('finish_reason') in ('stop','tool_calls'):reply.pop('status',None)
                if traces:
                    for trace in traces.values():
                        if trace.get('status') in ('drafting','validating','running'):trace['status']='interrupted'
                    reply['tool_trace']=list(traces.values())
                reply['model']=record.get('model')
                if record.get('model_name'):reply['model_name']=record['model_name']
                if reply.get('usage') and record.get('context_limit'):reply['usage']['limit']=record['context_limit']
                if reply['content'] or reply['reasoning_content'] or traces:
                    chat['messages'].append(reply);chat['last_run']=record['id'];self.save(chat,chat['revision'],api_fallback=chat.get('_source')=='api_fallback')
                record['acknowledged']=True;atomic_json(meta,record)
            except (OSError,ValueError,KeyError):continue

class RunJournal:
    def __init__(self, body, sessions):
        self.id=secrets.token_hex(16);self.root=sessions.root/'runs'/self.id;self.root.mkdir(parents=True)
        with sessions.connect() as db:row=db.execute('SELECT revision FROM chats WHERE id=? AND deleted=0',(body['conversation_id'],)).fetchone()
        if row is None:
            messages=body.get('messages') or []
            first=next((str(m.get('content','')) for m in messages if m.get('role')=='user'),'Chat')
            saved=sessions.save({'id':body['conversation_id'],'messages':messages,'title':first[:48],'ts':int(time.time()*1000)},api_fallback=True)
            row=(saved['revision'],)
        self.meta={'id':self.id,'conversation_id':body['conversation_id'],'revision':row[0] if row else None,
                   'pid':os.getpid(),'status':'running','model':body.get('model'),'model_name':body.get('model_name'),
                   'context_limit':body.get('context_limit'),'created':time.time()}
        atomic_json(self.root/'meta.json',self.meta);atomic_json(self.root/'request.json',body)
        self.queue=queue.Queue(256);self.error=None
        self.thread=threading.Thread(target=self._write,daemon=True);self.thread.start()
    def _write(self):
        try:
            with (self.root/'events.sse').open('ab',buffering=65536) as file:
                last=time.monotonic()
                while True:
                    try:item=self.queue.get(timeout=.5)
                    except queue.Empty:file.flush();continue
                    if item is None:break
                    file.write(item)
                    if time.monotonic()-last>1:file.flush();last=time.monotonic()
                file.flush();os.fsync(file.fileno())
        except OSError as error:self.error=str(error)
    def append(self, data):
        while self.thread.is_alive():
            try:self.queue.put(data,timeout=.2);return
            except queue.Full:continue
        raise OSError(self.error or 'Local run journal stopped.')
    def close(self, status):
        if self.thread.is_alive():self.queue.put(None);self.thread.join(10)
        self.meta['status']=status;self.meta['error']=self.error;atomic_json(self.root/'meta.json',self.meta)

SESSIONS=Sessions()
