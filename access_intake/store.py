"""SQLite authority: short transactions, fenced attempts and independent history."""
import contextlib
import copy
import hashlib
import json
import os
import sqlite3
import time
import uuid
from pathlib import Path


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',',':'), ensure_ascii=False)


class Store:
    def __init__(self, path, clock=None, lease_seconds=180):
        self.path=Path(path).resolve()
        self.path.parent.mkdir(parents=True,exist_ok=True)
        self.clock=clock or time.time
        self.lease_seconds=lease_seconds
        with self.connection() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS documents(document_id TEXT PRIMARY KEY, target INTEGER NOT NULL);
                CREATE TABLE IF NOT EXISTS attempts(
                  id INTEGER PRIMARY KEY AUTOINCREMENT, document_id TEXT NOT NULL,
                  generation INTEGER NOT NULL, source BLOB NOT NULL, source_sha256 TEXT NOT NULL,
                  fingerprint TEXT NOT NULL, config TEXT NOT NULL, metadata TEXT NOT NULL,
                  state TEXT NOT NULL DEFAULT 'queued', token INTEGER NOT NULL DEFAULT 0,
                  lease_until REAL NOT NULL DEFAULT 0, created REAL NOT NULL, result TEXT,
                  UNIQUE(document_id,generation));
                CREATE TABLE IF NOT EXISTS events(id INTEGER PRIMARY KEY AUTOINCREMENT,
                  attempt_id INTEGER, event TEXT NOT NULL, occurred REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS counters(name TEXT PRIMARY KEY, value INTEGER NOT NULL);
            ''')

    @contextlib.contextmanager
    def connection(self, write=False):
        db=sqlite3.connect(self.path,timeout=10)
        db.row_factory=sqlite3.Row
        try:
            if write: db.execute('BEGIN IMMEDIATE')
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    def event(self,db,attempt_id,event):
        db.execute('INSERT INTO events(attempt_id,event,occurred) VALUES(?,?,?)',(attempt_id,event,self.clock()))

    def accept(self,source,config,force=False):
        fingerprint=hashlib.sha256(canonical(config['processing']).encode()).hexdigest()
        with self.connection(True) as db:
            doc=db.execute('SELECT target FROM documents WHERE document_id=?',(source.document_id,)).fetchone()
            if doc:
                previous=db.execute('SELECT * FROM attempts WHERE document_id=? AND generation=?',
                                    (source.document_id,doc['target'])).fetchone()
                if not force and previous['source_sha256']==source.source_sha256 and previous['fingerprint']==fingerprint:
                    return previous['id'],False
                generation=doc['target']+1
                db.execute("UPDATE attempts SET state='superseded' WHERE document_id=? AND state='queued'",(source.document_id,))
                db.execute('UPDATE documents SET target=? WHERE document_id=?',(generation,source.document_id))
            else:
                generation=1
                db.execute('INSERT INTO documents VALUES(?,?)',(source.document_id,generation))
            cursor=db.execute('''INSERT INTO attempts(document_id,generation,source,source_sha256,fingerprint,config,metadata,created)
                                 VALUES(?,?,?,?,?,?,?,?)''',
                              (source.document_id,generation,source.raw,source.source_sha256,fingerprint,
                               canonical(config),canonical(source.metadata),self.clock()))
            self.event(db,cursor.lastrowid,'accepted')
            return cursor.lastrowid,True

    def claim(self,attempt_id=None):
        with self.connection(True) as db:
            sql="""SELECT a.* FROM attempts a JOIN documents d ON d.document_id=a.document_id AND d.target=a.generation
                     WHERE (a.state='queued' OR (a.state='running' AND a.lease_until<=?))"""
            params=[self.clock()]
            if attempt_id is not None:
                sql+=' AND a.id=?'
                params.append(attempt_id)
            row=db.execute(sql+' ORDER BY a.id LIMIT 1',params).fetchone()
            if not row: return None
            db.execute("UPDATE attempts SET state='running',token=token+1,lease_until=? WHERE id=?",
                       (self.clock()+self.lease_seconds,row['id']))
            self.event(db,row['id'],'reclaimed' if row['state']=='running' else 'claimed')
            return dict(db.execute('SELECT * FROM attempts WHERE id=?',(row['id'],)).fetchone())

    def heartbeat(self,attempt_id,token):
        with self.connection(True) as db:
            cursor=db.execute("""UPDATE attempts SET lease_until=? WHERE id=? AND token=? AND state='running'
                                  AND lease_until>? AND EXISTS(SELECT 1 FROM documents d
                                  WHERE d.document_id=attempts.document_id AND d.target=attempts.generation)""",
                              (self.clock()+self.lease_seconds,attempt_id,token,self.clock()))
            return cursor.rowcount==1

    def finish(self,attempt_id,token,result):
        with self.connection(True) as db:
            row=db.execute('SELECT * FROM attempts WHERE id=?',(attempt_id,)).fetchone()
            if not row or row['token']!=token or row['state']!='running' or row['lease_until']<=self.clock(): return False
            target=db.execute('SELECT target FROM documents WHERE document_id=?',(row['document_id'],)).fetchone()['target']
            state='superseded' if target!=row['generation'] else ('failed' if result['status']=='error' else 'succeeded')
            result=copy.deepcopy(result)
            config=json.loads(row['config'])
            result.update(document_id=row['document_id'],source_sha256=row['source_sha256'],attempt_id=row['id'],
                          target_generation=row['generation'],processing_fingerprint=row['fingerprint'],
                          policy_version=config['processing']['policy_sha256'],configuration=config,
                          processing_state=state,metadata=json.loads(row['metadata']))
            db.execute('UPDATE attempts SET state=?,result=? WHERE id=?',(state,canonical(result),attempt_id))
            self.event(db,attempt_id,state)
            return True

    def get(self,attempt_id):
        with self.connection() as db:
            row=db.execute('SELECT * FROM attempts WHERE id=?',(attempt_id,)).fetchone()
            if not row: raise KeyError('Unknown attempt.')
            return dict(row)

    def _current(self,db):
        rows=db.execute('''SELECT a.* FROM attempts a JOIN documents d
                           ON d.document_id=a.document_id AND d.target=a.generation ORDER BY a.document_id''').fetchall()
        result=[]
        for row in rows:
            if row['result']:
                record=json.loads(row['result'])
            else:
                record={'document_id':row['document_id'],'source_sha256':row['source_sha256'],
                        'attempt_id':row['id'],'target_generation':row['generation'],
                        'processing_state':row['state'],'metadata':json.loads(row['metadata']),
                        'extraction':None,'status':None,'owner':None,'next_action':None,'error':None}
                prior=db.execute('SELECT result FROM attempts WHERE document_id=? AND id<? AND result IS NOT NULL ORDER BY id DESC LIMIT 1',
                                 (row['document_id'],row['id'])).fetchone()
                record['previous']=json.loads(prior['result']) if prior else None
            result.append(record)
        return result

    def current(self):
        with self.connection() as db:
            db.execute('BEGIN')
            return self._current(db)

    def inspect(self,document_id):
        return next((row for row in self.current() if row['document_id']==document_id),None)

    def history(self,document_id):
        with self.connection() as db:
            rows=db.execute('SELECT * FROM attempts WHERE document_id=? ORDER BY id',(document_id,)).fetchall()
            return [{'attempt_id':r['id'],'target_generation':r['generation'],'processing_state':r['state'],
                     'source_sha256':r['source_sha256'],'processing_fingerprint':r['fingerprint'],
                     'created':r['created'],'configuration':json.loads(r['config']),
                     'result':json.loads(r['result']) if r['result'] else None} for r in rows]

    def events(self):
        with self.connection() as db: return [dict(row) for row in db.execute('SELECT * FROM events ORDER BY id')]

    def export(self,output,before_publish=None):
        """Build an immutable matched snapshot; publish one pointer, never two files."""
        output=Path(output).resolve()
        with self.connection(True) as db:
            rows=self._current(db)
            unfinished=[r['document_id'] for r in rows if r['processing_state'] in ('queued','running')]
            if unfinished: raise ValueError('Cannot export unfinished current targets: '+', '.join(unfinished))
            db.execute("INSERT OR IGNORE INTO counters VALUES('export',0)")
            db.execute("UPDATE counters SET value=value+1 WHERE name='export'")
            sequence=db.execute("SELECT value FROM counters WHERE name='export'").fetchone()['value']
            current_ids={r['attempt_id'] for r in rows}
            history=[json.loads(r['result']) for r in db.execute('SELECT id,result FROM attempts WHERE result IS NOT NULL ORDER BY id')
                     if r['id'] not in current_ids]
        directory=output/'.generations'/f'{sequence:08d}'
        directory.mkdir(parents=True,exist_ok=False)
        projection=['document_id','source_sha256','attempt_id','target_generation','status','owner','next_action',
                    'error','response_source','processing_fingerprint','policy_version','processing_state']
        manifest={'generation':sequence,'as_of':self.clock(),'document_count':len(rows),
                  'origin':'snapshot of terminal current attempts; inspect the database for live pending work'}
        files={'extractions.jsonl':''.join(canonical(r)+'\n' for r in rows),
               'queue.json':json.dumps([{k:r[k] for k in projection} for r in rows],indent=2)+'\n',
               'history.jsonl':''.join(canonical(r)+'\n' for r in history),
               'manifest.json':json.dumps(manifest,indent=2)+'\n'}
        for name,text in files.items():
            with (directory/name).open('w',encoding='utf-8') as handle:
                handle.write(text)
                handle.flush()
                os.fsync(handle.fileno())
        if before_publish: before_publish()
        with self.connection(True) as db:
            current=output/'current'
            if current.exists():
                published=json.loads((current/'manifest.json').read_text())
                if published['generation']>sequence: raise ValueError('A newer snapshot is already published.')
            for name in files:
                link=output/name
                if os.path.lexists(link):
                    if not link.is_symlink() or os.readlink(link)!='current/'+name:
                        raise ValueError('Output path already contains an unrelated file: '+name)
                else: link.symlink_to('current/'+name)
            temp=output/('.current-'+uuid.uuid4().hex)
            temp.symlink_to(Path('.generations')/directory.name,target_is_directory=True)
            os.replace(temp,current)
            fd=os.open(output,os.O_RDONLY|os.O_DIRECTORY)
            try: os.fsync(fd)
            finally: os.close(fd)
            self.event(db,None,'exported')
        return manifest
