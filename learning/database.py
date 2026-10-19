"""SQLite migrations, bounded transactions and recoverable local backups."""
from contextlib import contextmanager,closing
import json
import os
from pathlib import Path
import re
import sqlite3
import time
import uuid

SCHEMA_VERSION=1
TABLES=('category_policies','scene_features','editing_decisions','effect_candidates','reviewed_examples','user_feedback',
    'caption_preferences','quality_reviews','training_datasets','model_registry','model_evaluations','inference_receipts','privacy_preferences')


def location():
    explicit=os.getenv('OPENSHORTS_LEARNING_DIR')
    if explicit:return Path(explicit)
    library=os.getenv('OPENSHORTS_LIBRARY')
    return Path(library)/'learning' if library else Path(os.environ.get('LOCALAPPDATA',Path.home()/'.local/share'))/'OpenShorts'/'learning'


def payload(value,max_size=262144):
    raw=json.dumps(value,sort_keys=True,allow_nan=False,separators=(',',':'))
    if len(raw)>max_size or re.search(r'AIza[\w-]{20,}|AQ\.[\w-]{20,}|Bearer\s|api[_-]?key',raw,re.I):raise ValueError('Unsafe or oversized learning data')
    return raw


class Store:
    def __init__(self,root=None):
        self.root=Path(root) if root else location();self.root.mkdir(parents=True,exist_ok=True)
        self.path=self.root/'editing-knowledge.sqlite3'
        self.initialize()

    @contextmanager
    def connect(self):
        db=sqlite3.connect(self.path,timeout=10)
        db.row_factory=sqlite3.Row
        try:
            db.execute('PRAGMA foreign_keys=ON');db.execute('PRAGMA busy_timeout=10000')
            yield db
            db.commit()
        except BaseException:db.rollback();raise
        finally:db.close()

    def initialize(self):
        try:
            with self.connect() as db:
                if db.execute('PRAGMA quick_check').fetchone()[0]!='ok':raise sqlite3.DatabaseError('Integrity check failed')
                db.execute('PRAGMA journal_mode=WAL')
                version=db.execute('PRAGMA user_version').fetchone()[0]
                if version>SCHEMA_VERSION:raise ValueError('Newer learning database requires newer runtime')
                db.execute('BEGIN IMMEDIATE')
                db.execute('CREATE TABLE IF NOT EXISTS schema_migrations(version INTEGER PRIMARY KEY, applied REAL NOT NULL)')
                db.execute('CREATE TABLE IF NOT EXISTS scene_features(id TEXT PRIMARY KEY,source_group TEXT NOT NULL,project_ref TEXT NOT NULL,scene_ref TEXT NOT NULL,category TEXT NOT NULL,feature_version INTEGER NOT NULL,data TEXT NOT NULL,created REAL NOT NULL)')
                for table in TABLES:
                    if table=='scene_features':continue
                    db.execute(f'CREATE TABLE IF NOT EXISTS {table}(id TEXT PRIMARY KEY,scene_id TEXT REFERENCES scene_features(id) ON DELETE CASCADE,category TEXT NOT NULL DEFAULT \'\',status TEXT NOT NULL DEFAULT \'unreviewed\',data TEXT NOT NULL,created REAL NOT NULL)')
                    db.execute(f'CREATE INDEX IF NOT EXISTS idx_{table}_lookup ON {table}(category,status,created)')
                db.execute('CREATE INDEX IF NOT EXISTS idx_scene_group ON scene_features(source_group,category)')
                db.execute('INSERT OR IGNORE INTO schema_migrations VALUES(?,?)',(SCHEMA_VERSION,time.time()))
                db.execute(f'PRAGMA user_version={SCHEMA_VERSION}')
        except sqlite3.DatabaseError as exc:
            # Busy, read-only and disk errors are not corruption. In particular,
            # never rename a healthy database held by another worker.
            code=getattr(exc,'sqlite_errorcode',None)
            if code is not None and (code & 255) not in (sqlite3.SQLITE_CORRUPT,sqlite3.SQLITE_NOTADB):raise
            if code is None and str(exc)!='Integrity check failed':raise
            # Never overwrite corrupt customer data. Preserve it for diagnosis,
            # then restore only an integrity-checked SQLite backup if available.
            target=self.root/f'corrupt-{uuid.uuid4().hex}.sqlite3'
            if self.path.exists():self.path.replace(target)
            for suffix in ('-wal','-shm'):
                side=Path(str(self.path)+suffix)
                if side.exists():side.replace(Path(str(target)+suffix))
            backup=self.root/'knowledge-backup.sqlite3'
            if backup.is_file():
                try:
                    with closing(sqlite3.connect(backup)) as old:
                        if old.execute('PRAGMA quick_check').fetchone()[0]=='ok':
                            with closing(sqlite3.connect(self.path)) as new:old.backup(new)
                except sqlite3.DatabaseError:
                    backup.replace(self.root/f'corrupt-backup-{uuid.uuid4().hex}.sqlite3')
            self.initialize()

    def put(self,table,identity,data,*,scene=None,category='',status='unreviewed',db=None):
        if table not in TABLES or table=='scene_features':raise ValueError('Invalid entity')
        # Versioned dataset snapshots contain bounded numeric features, and can
        # legitimately exceed the per-feedback record limit at training scale.
        args=(identity,scene,category,status,payload(data,32*1024*1024 if table=='training_datasets' else 262144),time.time())
        query=f'INSERT INTO {table} VALUES(?,?,?,?,?,?) ON CONFLICT(id) DO NOTHING'
        if db is not None:return db.execute(query,args).rowcount
        with self.connect() as connection:return connection.execute(query,args).rowcount

    def rows(self,table,where='',args=(),limit=10000):
        if table not in TABLES:raise ValueError('Invalid entity')
        if where not in ('','status=?','id=?','category=?','scene_id=?'):raise ValueError('Invalid lookup')
        with self.connect() as db:
            return [dict(r)|{'data':json.loads(r['data'])} for r in db.execute(f'SELECT * FROM {table}'+(' WHERE '+where if where else '')+' ORDER BY created,id LIMIT ?',(*args,min(10000,limit)))]

    def backup(self):
        temporary=self.root/f'backup-{uuid.uuid4().hex}.tmp'
        with self.connect() as db,closing(sqlite3.connect(temporary)) as dest:db.backup(dest)
        temporary.replace(self.root/'knowledge-backup.sqlite3')

    def integrity(self):
        with self.connect() as db:return db.execute('PRAGMA quick_check').fetchone()[0]=='ok' and not db.execute('PRAGMA foreign_key_check').fetchall()

    def preferences(self):
        rows=self.rows('privacy_preferences','id=?',('local',))
        value=rows[0]['data'] if rows else dict(collect=True,retrieval=True,inference=False,retention_days=365,upload=False)
        self.validate_privacy(value)
        return value

    @staticmethod
    def validate_privacy(value):
        if not isinstance(value,dict) or set(value)!={'collect','retrieval','inference','retention_days','upload'} or any(type(value[k]) is not bool for k in ('collect','retrieval','inference','upload')) or value['upload'] or type(value['retention_days']) is not int or not 1<=value['retention_days']<=3650:raise ValueError('Invalid local privacy settings')

    def privacy(self,value):
        self.validate_privacy(value)
        with self.connect() as db:
            db.execute('DELETE FROM privacy_preferences WHERE id=?',('local',));self.put('privacy_preferences','local',value,db=db)

    def purge(self):
        cutoff=time.time()-self.preferences()['retention_days']*86400
        with self.connect() as db:
            removed=db.execute('DELETE FROM scene_features WHERE created<?',(cutoff,)).rowcount
            # Category corrections have no scene FK. Apply the same user-selected
            # retention policy without touching unrelated feedback.
            for row in db.execute('SELECT id,data FROM user_feedback WHERE scene_id IS NULL AND created<?',(cutoff,)).fetchall():
                try:owned=json.loads(row['data']).get('task')=='category-classification'
                except (ValueError,AttributeError):owned=False
                if owned:
                    db.execute('DELETE FROM user_feedback WHERE id=?',(row['id'],));removed+=1
            for table in ('training_datasets','inference_receipts'):db.execute(f'DELETE FROM {table} WHERE created<?',(cutoff,))
            for row in db.execute('SELECT id,data FROM editing_decisions WHERE scene_id IS NULL AND created<?',(cutoff,)).fetchall():
                try:owned=json.loads(row['data']).get('task')=='smart-split'
                except (ValueError,AttributeError):owned=False
                if owned:
                    db.execute('DELETE FROM editing_decisions WHERE id=?',(row['id'],));removed+=1
        # Refresh backups after retention so expired feedback cannot resurrect.
        backup=self.root/'knowledge-backup.sqlite3'
        if removed or not backup.exists() or time.time()-backup.stat().st_mtime>86400:self.backup()

    def delete_history(self):
        with self.connect() as db:
            for table in reversed(TABLES):
                if table!='privacy_preferences':db.execute(f'DELETE FROM {table}')
        for path in self.root.iterdir():
            owned=path.name=='knowledge-backup.sqlite3' or re.fullmatch(r'model-[0-9a-f]{64}\.(?:json|tmp)|backup-[0-9a-f]{32}\.tmp|corrupt-(?:backup-)?[0-9a-f]{32}\.sqlite3(?:-wal|-shm)?',path.name)
            if owned and path.is_file():path.unlink()
        with self.connect() as db:db.execute('PRAGMA wal_checkpoint(TRUNCATE)');db.execute('VACUUM')
