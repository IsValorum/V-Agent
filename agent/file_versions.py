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
    # Every write used to keep a full copy forever: the index grew without limit with large or often edited files.
    KEEP=100                 # versions per file (history lists 100)
    MAX_BYTES=32*2**20       # a larger file is not copied
    def capture(self, path, workspace):
        path,workspace=self.identity(path,workspace);target=Path(path)
        try:
            if target.is_file() and target.stat().st_size>self.MAX_BYTES:return None
        except OSError:return None
        content=target.read_bytes() if target.is_file() else b''
        ident=secrets.token_hex(16)
        with self.connect() as db:
            db.execute('INSERT INTO revisions VALUES(?,?,?,?,?,?)',(ident,workspace,path,time.time(),content,int(target.is_file())))
            db.execute('DELETE FROM revisions WHERE path=? AND workspace=? AND id NOT IN (SELECT id FROM revisions WHERE path=? AND workspace=? ORDER BY created DESC LIMIT ?)',
                       (path,workspace,path,workspace,self.KEEP))
        return ident
    def history(self, path, workspace):
        """Saved states of a file, newest first, each described so a model can pick the right one."""
        path,workspace=self.identity(path,workspace)
        with self.connect() as db:
            rows=db.execute('SELECT id,created,content,present FROM revisions WHERE path=? AND workspace=? ORDER BY created DESC LIMIT 100',(path,workspace)).fetchall()
        versions=[]
        for ident,created,content,present in rows:
            entry={'id':ident,'created':created,'bytes':len(content),'existed':bool(present)}
            if present:entry['preview']=content[:240].decode('utf-8',errors='replace')
            else:entry['state']='the file did not exist yet; restoring this deletes the file'
            versions.append(entry)
        return versions
    def describe(self, path, workspace):
        """History for a model: current content, versions with previews, and how to choose."""
        current=Path(path)
        return {'current':current.read_bytes()[:240].decode('utf-8',errors='replace') if current.is_file() else None,
                'versions':[{k:v for k,v in entry.items() if k!='created'} for entry in self.history(path,workspace)],
                'note':'Each version is how the file was before a change, newest first. Compare the previews with the content you want back and pass that id as revision.'}
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
