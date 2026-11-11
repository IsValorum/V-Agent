"""Immutable local file revisions; no git dependency or model-generated restore code."""
import difflib
from contextlib import contextmanager
import os
from pathlib import Path
import secrets
import sqlite3
import tempfile
import time
from local_store import DATA

class FileVersions:
    def __init__(self, root=DATA/'versions'):
        self.root=Path(root);self.root.mkdir(parents=True,exist_ok=True)
        self.db=self.root/'index.sqlite3'
        with self.connect() as db:
            db.executescript('PRAGMA journal_mode=WAL; CREATE TABLE IF NOT EXISTS revisions(id TEXT PRIMARY KEY,workspace TEXT,path TEXT,created REAL,content BLOB,present INTEGER);')
    @contextmanager
    def connect(self):
        db=sqlite3.connect(self.db,timeout=15)
        try:
            with db:yield db
        finally:db.close()
    def identity(self, path, workspace):return os.path.normcase(str(Path(path).resolve())),os.path.normcase(str(Path(workspace).resolve()))
    def capture(self, path, workspace):
        path,workspace=self.identity(path,workspace);target=Path(path)
        content=target.read_bytes() if target.exists() else b''
        ident=secrets.token_hex(16)
        with self.connect() as db:db.execute('INSERT INTO revisions VALUES(?,?,?,?,?,?)',(ident,workspace,path,time.time(),content,int(target.exists())))
        return ident
    def history(self, path, workspace):
        path,workspace=self.identity(path,workspace)
        with self.connect() as db:return [{'id':row[0],'created':row[1],'bytes':row[2],'existed':bool(row[3])} for row in db.execute('SELECT id,created,length(content),present FROM revisions WHERE path=? AND workspace=? ORDER BY created DESC LIMIT 100',(path,workspace))]
    def restore(self, path, workspace, revision=None):
        original=path;path,workspace=self.identity(path,workspace)
        with self.connect() as db:
            row=db.execute('SELECT id,content,present FROM revisions WHERE path=? AND workspace=? '+('AND id=? ' if revision else '')+'ORDER BY created DESC LIMIT 1',(path,workspace,revision) if revision else (path,workspace)).fetchone()
        if not row:raise ValueError('No hay una versión anterior para este archivo en esta conversación.')
        current=Path(path).read_bytes() if Path(path).exists() else b''
        self.capture(path,workspace)
        if not row[2]:
            Path(path).unlink(missing_ok=True)
        else:
            Path(path).parent.mkdir(parents=True,exist_ok=True)
            with tempfile.NamedTemporaryFile(dir=Path(path).parent,delete=False) as file:
                temporary=file.name;file.write(row[1]);file.flush();os.fsync(file.fileno())
            try:os.replace(temporary,path)
            finally:
                if os.path.exists(temporary):os.unlink(temporary)
        return {'restored':row[0],'path':str(original),'diff':'\n'.join(difflib.unified_diff(current.decode('utf-8',errors='replace').splitlines(),row[1].decode('utf-8',errors='replace').splitlines(),fromfile='before',tofile='restored'))[:6000]}

VERSIONS=FileVersions()
