"""Private, versioned advisory memory; sources are retained, never summarized away.

Only trusted host code receives this handle. Principal checks are application
boundaries, not protection against an attacker with filesystem or Python access.
No vector index, shared graph, model download, or inference client is installed.
"""
from __future__ import annotations
from contextlib import contextmanager
from pathlib import Path
import json
import os
import sqlite3
from .contracts import (MemoryContractError as Error, MemoryPolicy, Principal,
                        KINDS, bounded_text, digest, fields, tags, timestamp, wire)


class MemoryStore:
    def __init__(self, path, *, policy=MemoryPolicy()):
        if not isinstance(policy, MemoryPolicy):
            raise Error("MemoryPolicy required")
        self.path, self.policy = Path(path), policy
        if self.path.is_symlink() or any(p.is_symlink() for p in self.path.parents):
            raise Error("memory path must not traverse symlinks")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(self.path, timeout=10, isolation_level=None)
        self.db.row_factory = sqlite3.Row
        try:
            tables = {r[0] for r in self.db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            if tables:
                if 'meta' not in tables:
                    raise Error("not a memory database; refusing to modify it")
                row = self.db.execute("SELECT value FROM meta WHERE key='schema'").fetchone()
                if not row or row[0] != 'private-delta-v1':
                    raise Error("memory schema mismatch; explicit migration required")
            os.chmod(self.path, 0o600)
            self.db.execute("PRAGMA foreign_keys=ON")
            self.db.execute("PRAGMA synchronous=FULL")
            self.db.executescript("""
            CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT NOT NULL);
            INSERT OR IGNORE INTO meta VALUES('schema','private-delta-v1');
            CREATE TABLE IF NOT EXISTS source(owner TEXT, project TEXT, ref TEXT, text TEXT NOT NULL,
                PRIMARY KEY(owner,project,ref));
            CREATE TABLE IF NOT EXISTS entry(id TEXT PRIMARY KEY, owner TEXT, project TEXT,
                topic TEXT, version INTEGER, body TEXT NOT NULL, active INTEGER NOT NULL,
                invalidated INTEGER NOT NULL DEFAULT 0, used INTEGER NOT NULL DEFAULT 0,
                touched INTEGER NOT NULL DEFAULT 0, UNIQUE(owner,project,topic,version));
            CREATE TABLE IF NOT EXISTS head(owner TEXT,project TEXT,topic TEXT,ref TEXT NOT NULL,
                PRIMARY KEY(owner,project,topic), FOREIGN KEY(ref) REFERENCES entry(id));
            CREATE TABLE IF NOT EXISTS dependency(child TEXT,parent TEXT,
                PRIMARY KEY(child,parent), FOREIGN KEY(child) REFERENCES entry(id),
                FOREIGN KEY(parent) REFERENCES entry(id));
            CREATE TABLE IF NOT EXISTS pending(owner TEXT,project TEXT,ref TEXT,
                PRIMARY KEY(owner,project,ref), FOREIGN KEY(ref) REFERENCES entry(id));
            CREATE TABLE IF NOT EXISTS write_intent(id TEXT PRIMARY KEY,owner TEXT,project TEXT,
                body TEXT NOT NULL,state TEXT NOT NULL,reason TEXT NOT NULL,entries TEXT NOT NULL);
            CREATE INDEX IF NOT EXISTS write_scope ON write_intent(owner,project,state);
            CREATE TABLE IF NOT EXISTS job(id TEXT PRIMARY KEY,owner TEXT,project TEXT,
                body TEXT NOT NULL,state TEXT NOT NULL,draft TEXT);
            CREATE TABLE IF NOT EXISTS retirement(ref TEXT PRIMARY KEY,owner TEXT,project TEXT,resolution TEXT);
            CREATE TABLE IF NOT EXISTS approval(job TEXT PRIMARY KEY,draft_hash TEXT,approval_id TEXT);
            CREATE INDEX IF NOT EXISTS entries_scope ON entry(owner,project,active);
            CREATE INDEX IF NOT EXISTS reverse_dependencies ON dependency(parent);
            """)
            import uuid
            with self.transaction():
                self.db.execute("INSERT OR IGNORE INTO meta VALUES('instance',?)", (uuid.uuid4().hex,))
            self.identity = self.db.execute("SELECT value FROM meta WHERE key='instance'").fetchone()[0]
            bounded_text(self.identity, 'database identity', 64)
            self.audit()
        except BaseException:
            self.db.close()
            raise

    def stage_write(self, principal, user, response, sources):
        """Durable receipt before inference; acknowledgment is not indexed memory."""
        bounded_text(user,'user interaction',4000,empty=True)
        bounded_text(response,'accepted interaction',4000,empty=True)
        if type(sources) not in (tuple,list) or not 1<=len(sources)<=8 or len(set(sources))!=len(sources):
            raise Error('invalid write sources')
        for ref in sources:self.source(principal,ref)
        interaction=self.add_source(principal,wire({'user':user,'accepted':response}))
        body={'owner':principal.user,'project':principal.project,'interaction':interaction,'sources':list(sources)}
        ref=digest(body)
        with self.transaction():
            if not self.db.execute('SELECT id FROM write_intent WHERE id=?',(ref,)).fetchone():
                counts=self.db.execute("SELECT count(*),sum(state='pending') FROM write_intent WHERE owner=? AND project=?",self._scope(principal)).fetchone()
                if counts[0]>=self.policy.max_records or (counts[1] or 0)>=self.policy.max_pending:
                    raise Error('write receipt capacity reached; sources retained')
                self.db.execute('INSERT INTO write_intent VALUES(?,?,?,?,?,?,?)',
                    (ref,*self._scope(principal),wire(body),'pending','awaiting writer','[]'))
        return self.write_intent(principal,ref)

    def write_intent(self, principal, ref):
        row=self.db.execute('SELECT * FROM write_intent WHERE owner=? AND project=? AND id=?',(*self._scope(principal),ref)).fetchone()
        if row is None:raise Error('write receipt unavailable')
        body=json.loads(row['body'])
        fields(body,{'owner','project','interaction','sources'})
        bounded_text(row['reason'],'write reason',300,empty=True)
        if digest(body)!=ref or (body['owner'],body['project'])!=self._scope(principal):raise Error('write receipt integrity failure')
        interaction=json.loads(self.source(principal,body['interaction']))
        for source in body['sources']:self.source(principal,source)
        entries=json.loads(row['entries'])
        if (row['state'] not in {'pending','committed'} or type(entries) is not list
                or any(type(e) is not str for e in entries) or len(set(entries))!=len(entries)
                or (row['state']=='committed')!=bool(entries)):
            raise Error('invalid write receipt state')
        for entry in entries:
            item=self.get(principal,entry)
            if not set(body['sources'])<=set(item['sources']):raise Error('write receipt source mismatch')
        return dict(body,id=ref,state=row['state'],reason=row['reason'],entry_refs=entries,**interaction)

    def finish_write(self, principal, ref, *, entries=(), reason=''):
        bounded_text(reason,'write reason',300,empty=True)
        with self.transaction():
            current=self.write_intent(principal,ref)
            if current['state']=='committed':return current
            if type(entries) not in (tuple,list) or len(entries)>self.policy.max_writes or len(set(entries))!=len(entries):
                raise Error('invalid committed memory references')
            for entry in entries:
                row=self.get(principal,entry)
                if not set(current['sources'])<=set(row['sources']):raise Error('write source mismatch')
            self.db.execute('UPDATE write_intent SET state=?,reason=?,entries=? WHERE id=?',
                ('committed' if entries else 'pending',reason,wire(list(entries)),ref))
        return self.write_intent(principal,ref)

    def pending_writes(self, principal, *, limit=16):
        if type(limit) is not int or not 1<=limit<=64:raise Error('invalid pending write limit')
        rows=self.db.execute("SELECT id FROM write_intent WHERE owner=? AND project=? AND state='pending' ORDER BY rowid DESC LIMIT ?",(*self._scope(principal),limit)).fetchall()
        return [self.write_intent(principal,r[0]) for r in rows]


    def close(self):
        self.db.close()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()

    @contextmanager
    def transaction(self):
        # Savepoints let a reviewed consolidation and its version writes commit atomically.
        import uuid
        nested=self.db.in_transaction
        name='mem_'+uuid.uuid4().hex
        self.db.execute('SAVEPOINT '+name if nested else 'BEGIN IMMEDIATE')
        try:
            yield
            self.db.execute('RELEASE SAVEPOINT '+name if nested else 'COMMIT')
        except BaseException:
            if nested:
                self.db.execute('ROLLBACK TO SAVEPOINT '+name)
                self.db.execute('RELEASE SAVEPOINT '+name)
            else:
                self.db.execute('ROLLBACK')
            raise

    @staticmethod
    def _scope(principal):
        if not isinstance(principal, Principal):
            raise Error("a host-bound principal is required")
        return principal.user, principal.project

    def add_source(self, principal, text):
        owner, project = self._scope(principal)
        bounded_text(text, "source", self.policy.max_source_chars, empty=True)
        ref = digest({"text": text})
        with self.transaction():
            old = self.db.execute("SELECT text FROM source WHERE owner=? AND project=? AND ref=?",
                                  (owner, project, ref)).fetchone()
            if old:
                if old[0] != text:
                    raise Error("source integrity failure")
                return ref
            used = self.db.execute("SELECT COALESCE(SUM(length(CAST(text AS BLOB))),0) FROM source WHERE owner=? AND project=?",
                                   (owner, project)).fetchone()[0]
            if used + len(text.encode('utf-8')) > self.policy.max_archive_bytes:
                raise Error("source capacity reached; evidence was not evicted")
            self.db.execute("INSERT INTO source VALUES(?,?,?,?)", (owner, project, ref, text))
        return ref

    def source(self, principal, ref):
        owner, project = self._scope(principal)
        bounded_text(ref, 'source reference', 64)
        row = self.db.execute("SELECT text FROM source WHERE owner=? AND project=? AND ref=?",
                              (owner, project, ref)).fetchone()
        if not row or digest({'text': row[0]}) != ref:
            raise Error('source unavailable or corrupt')
        return row[0]

    def _entry(self, row):
        body = json.loads(row['body'])
        if digest(body) != row['id'] or body.get('authority') != 'advisory':
            raise Error('memory integrity failure')
        if (body['owner'],body['project'],body['key'],body['version']) != (row['owner'],row['project'],row['topic'],row['version']):
            raise Error('memory metadata integrity failure')
        return dict(body, id=row['id'], active=bool(row['active']),
                    invalidated=bool(row['invalidated']), uses=row['used'], touched=row['touched'])

    def get(self, principal, ref):
        row = self.db.execute('SELECT * FROM entry WHERE owner=? AND project=? AND id=?',
                              (*self._scope(principal), ref)).fetchone()
        if row is None:
            raise Error('memory unavailable')
        return self._entry(row)

    def head(self, principal, key):
        row = self.db.execute('SELECT ref FROM head WHERE owner=? AND project=? AND topic=?',
                              (*self._scope(principal), key)).fetchone()
        return self.get(principal, row[0]) if row else None

    def _invalidate(self, principal, ref, *, include_self=False):
        todo = [ref]; seen = set()
        while todo:
            parent = todo.pop()
            if parent in seen:
                continue
            seen.add(parent)
            self.get(principal, parent)
            if parent != ref or include_self:
                self.db.execute('UPDATE entry SET invalidated=1,active=0 WHERE id=?', (parent,))
            todo.extend(r[0] for r in self.db.execute('SELECT child FROM dependency WHERE parent=?', (parent,)))

    def retire(self, principal, key, *, expected, resolution_source):
        self.source(principal, resolution_source)
        with self.transaction():
            old = self.head(principal, key)
            if not old or old['id'] != expected or old['invalidated']:
                raise Error('stale memory retirement')
            self._invalidate(principal, expected, include_self=True)
            self.db.execute("INSERT INTO retirement VALUES(?,?,?,?)", (expected,*self._scope(principal),resolution_source))

    def write(self, principal, *, key, summary, kind, sources, item_tags=(),
              expected=None, created=None, pinned=False, dependencies=()):
        return self.write_batch(principal, [dict(key=key,summary=summary,kind=kind,
            sources=sources,tags=item_tags,expected=expected,created=created,pinned=pinned,
            dependencies=dependencies)])[0]

    def write_batch(self, principal, items):
        owner, project = self._scope(principal)
        if type(items) is not list or not 1 <= len(items) <= self.policy.max_writes:
            raise Error('invalid memory write count')
        checked = []
        for item in items:
            fields(item, {'key','summary','kind','sources','tags','expected','created','pinned','dependencies'})
            bounded_text(item['key'], 'key', 160)
            bounded_text(item['summary'], 'summary', self.policy.summary_chars)
            if type(item['kind']) is not str or item['kind'] not in KINDS or type(item['pinned']) is not bool:
                raise Error('invalid kind or pin')
            if item['expected'] is not None:
                bounded_text(item['expected'], 'expected revision', 64)
            for name, lo, hi in (('sources',1,8),('dependencies',0,16)):
                vals = item[name]
                if type(vals) not in (list,tuple) or not lo <= len(vals) <= hi or any(type(v) is not str for v in vals) or len(set(vals)) != len(vals):
                    raise Error('invalid source/dependency references')
            for ref in item['sources']:
                self.source(principal, ref)
            checked.append(dict(item,tags=list(tags(item['tags'])),sources=list(item['sources']),
                                dependencies=list(item['dependencies']),created=timestamp(item['created'])))
        if len({i['key'] for i in checked}) != len(checked):
            raise Error('duplicate write key')
        result = []
        with self.transaction():
            for item in checked:
                prior = self.head(principal, item['key'])
                actual = prior['id'] if prior else None
                if actual != item['expected']:
                    raise Error('stale memory version')
                same = prior and all(prior[k] == item[k] for k in ('summary','kind','sources','tags','pinned','dependencies'))
                if prior and prior['pinned'] and not prior['invalidated'] and not same:
                    raise Error('pinned memory requires explicit host retirement')
                if prior and item['created'] < prior['created']:
                    raise Error('memory time cannot move backwards')
                for ref in item['dependencies']:
                    dep = self.get(principal, ref)
                    head = self.head(principal, dep['key'])
                    if dep['key'] == item['key'] or dep['invalidated'] or not head or head['id'] != ref:
                        raise Error('stale or self-referential prerequisite')
                if same and not prior['invalidated']:
                    result.append(actual)
                    continue
                count = self.db.execute('SELECT count(*) FROM entry WHERE owner=? AND project=?', (owner,project)).fetchone()[0]
                if count >= self.policy.max_records:
                    raise Error('history capacity reached; originals were not deleted')
                body = {k:item[k] for k in ('key','summary','kind','sources','tags','pinned','dependencies','created')}
                body.update(owner=owner,project=project,version=prior['version']+1 if prior else 1,
                            supersedes=actual,authority='advisory')
                ref = digest(body)
                if actual:
                    self._invalidate(principal, actual)
                    self.db.execute('UPDATE entry SET active=0 WHERE id=?', (actual,))
                self.db.execute('INSERT INTO entry(id,owner,project,topic,version,body,active) VALUES(?,?,?,?,?,?,1)',
                                (ref,owner,project,item['key'],body['version'],wire(body)))
                for parent in item['dependencies']:
                    self.db.execute('INSERT INTO dependency VALUES(?,?)', (ref,parent))
                self.db.execute('INSERT INTO head VALUES(?,?,?,?) ON CONFLICT(owner,project,topic) DO UPDATE SET ref=excluded.ref',
                                (owner,project,item['key'],ref))
                if self.policy.allow_private_consolidation:
                    pending = self.pending_count(principal)
                    if pending < self.policy.max_pending:
                        self.db.execute('INSERT OR IGNORE INTO pending VALUES(?,?,?)', (owner,project,ref))
                result.append(ref)
            rows = self.db.execute('SELECT * FROM entry WHERE owner=? AND project=? AND active=1 ORDER BY used,touched,rowid', (owner,project)).fetchall()
            excess = len(rows)-self.policy.capacity
            for row in rows:
                if excess <= 0:
                    break
                if not self._entry(row)['pinned']:
                    self.db.execute('UPDATE entry SET active=0 WHERE id=?', (row['id'],))
                    excess -= 1
            if excess > 0:
                raise Error('pinned memory exceeds capacity; batch rolled back')
            # A later edit in this same batch may invalidate an earlier dependent.
            if any(self.get(principal, ref)['invalidated'] for ref in result):
                raise Error('batch changed a prerequisite; write prerequisites first')
        return result

    def candidates(self, principal, *, item_tags=(), after=None, before=None):
        wanted = tags(item_tags)
        after = timestamp(after) if after is not None else None
        before = timestamp(before) if before is not None else None
        if after and before and after > before:
            raise Error('inverted temporal window')
        rows = self.db.execute('SELECT * FROM entry WHERE owner=? AND project=?' +
            ('' if before else ' AND active=1') + ' ORDER BY version DESC,rowid DESC', self._scope(principal))
        seen = set(); result = []
        for row in rows:
            item = self._entry(row)
            if before and item['created'] > before:
                continue
            if item['key'] in seen:
                continue
            seen.add(item['key'])
            if item['invalidated'] or (after and item['created'] < after):
                continue
            if set(wanted) <= set(item['tags']):
                result.append(item)
        return result

    def touch(self, principal, refs):
        with self.transaction():
            tick = self.db.execute('SELECT COALESCE(MAX(touched),0)+1 FROM entry').fetchone()[0]
            for ref in refs:
                self.get(principal, ref)
                self.db.execute('UPDATE entry SET used=used+1,touched=? WHERE id=? AND owner=? AND project=?',
                                (tick,ref,*self._scope(principal)))

    def pending_count(self, principal):
        return self.db.execute('SELECT count(*) FROM pending WHERE owner=? AND project=?', self._scope(principal)).fetchone()[0]

    def pending_entries(self, principal):
        # Removing stale queue pointers does not remove any source or version.
        with self.transaction():
            self.db.execute('''DELETE FROM pending WHERE owner=? AND project=? AND
                (NOT EXISTS (SELECT 1 FROM head WHERE head.owner=pending.owner
                  AND head.project=pending.project AND head.ref=pending.ref)
                 OR EXISTS (SELECT 1 FROM entry WHERE entry.id=pending.ref AND entry.invalidated=1))''',
                self._scope(principal))
            rows=self.db.execute('SELECT ref FROM pending WHERE owner=? AND project=? ORDER BY rowid LIMIT ?',
                                (*self._scope(principal),self.policy.batch_size)).fetchall()
            return [self.get(principal,r[0]) for r in rows]

    def reserve_batch(self, principal, *, refs=None):
        if not self.policy.allow_private_consolidation:
            return None
        import uuid
        with self.transaction():
            jobs=self.db.execute('SELECT count(*) FROM job WHERE owner=? AND project=?',self._scope(principal)).fetchone()[0]
            if jobs>=self.policy.max_records:
                raise Error('consolidation job history capacity reached')
            entries=self.pending_entries(principal)
            if refs is not None:
                if (type(refs) is not tuple or not refs or len(refs)>self.policy.batch_size or
                        any(type(r) is not str for r in refs) or len(set(refs))!=len(refs)):
                    raise Error('invalid selected consolidation batch')
                offered={e['id']:e for e in entries}
                if not set(refs)<=set(offered):raise Error('stale or unoffered consolidation batch')
                entries=[offered[r] for r in refs]
            if not entries:return None
            heads = {e['key']:self.head(principal,e['key'])['id'] for e in entries}
            body = {'entries':[e['id'] for e in entries], 'heads':heads}
            jid = uuid.uuid4().hex
            self.db.execute("INSERT INTO job VALUES(?,?,?,?,'reserved',NULL)", (jid,*self._scope(principal),wire(body)))
            for e in entries:
                self.db.execute('DELETE FROM pending WHERE owner=? AND project=? AND ref=?', (*self._scope(principal),e['id']))
        return {'id':jid,'entries':entries,'heads':heads}

    def stage(self, principal, job_id, draft):
        # Staging is private advice only. Host applies separately via write_batch.
        fields(draft, {'items'})
        if type(draft['items']) is not list or len(draft['items']) > self.policy.max_writes:
            raise Error('invalid consolidation count')
        row = self.db.execute('SELECT * FROM job WHERE id=? AND owner=? AND project=?', (job_id,*self._scope(principal))).fetchone()
        if not row or row['state'] != 'reserved':
            raise Error('job unavailable or consumed')
        body = json.loads(row['body'])
        for item in draft['items']:
            fields(item, {'key','summary','kind','tags','entries'})
            bounded_text(item['key'],'key',160)
            bounded_text(item['summary'],'summary',self.policy.summary_chars)
            if type(item['kind']) is not str or item['kind'] not in KINDS:
                raise Error('invalid consolidation kind')
            tags(item['tags'])
            refs = item['entries']
            if type(refs) is not list or not refs or len(refs)>8 or any(type(r) is not str for r in refs) or len(set(refs))!=len(refs) or not set(refs)<=set(body['entries']):
                raise Error('consolidator cited unoffered memory')
            for ref in refs:
                entry = self.get(principal,ref)
                if entry['invalidated'] or self.head(principal,entry['key'])['id'] != ref:
                    raise Error('consolidator cited stale memory')
        if len({i['key'] for i in draft['items']}) != len(draft['items']):
            raise Error('duplicate consolidation key')
        with self.transaction():
            changed = self.db.execute("UPDATE job SET state='review',draft=? WHERE id=? AND owner=? AND project=? AND state='reserved'",
                (wire(draft),job_id,*self._scope(principal))).rowcount
            if changed != 1:
                raise Error('job concurrently consumed')
        return digest(draft)

    def fail_job(self, principal, job_id):
        with self.transaction():
            self.db.execute("UPDATE job SET state='failed' WHERE id=? AND owner=? AND project=? AND state='reserved'", (job_id,*self._scope(principal)))

    def apply_consolidation(self, principal, job_id, draft_hash, *, approve, approval_id):
        """Trusted host review only; no model receives this method or the database.

        Application is atomic with optimistic checks on all offered heads. The
        reviewer accepts semantic changes, not verification or shared publication.
        """
        bounded_text(approval_id,'approval identity',200)
        if not callable(approve):
            raise Error('host reviewer required')
        row=self.db.execute('SELECT * FROM job WHERE id=? AND owner=? AND project=?',
                            (job_id,*self._scope(principal))).fetchone()
        if not row or row['state']!='review':
            raise Error('no reviewable private consolidation')
        draft=json.loads(row['draft'])
        if digest(draft)!=draft_hash or approve(json.loads(wire(draft))) is not True:
            raise Error('private consolidation approval failed')
        batch=json.loads(row['body'])
        with self.transaction():
            current=self.db.execute('SELECT * FROM job WHERE id=?',(job_id,)).fetchone()
            if current['state']!='review' or current['draft']!=row['draft'] or current['body']!=row['body']:
                raise Error('stale consolidation approval')
            for key,ref in batch['heads'].items():
                head=self.head(principal,key)
                if not head or head['id']!=ref or head['invalidated']:
                    raise Error('memory changed after consolidation was reserved')
            items=[]
            for item in draft['items']:
                entries=[self.get(principal,ref) for ref in item['entries']]
                if any(e['invalidated'] or self.head(principal,e['key'])['id']!=e['id'] for e in entries):
                    raise Error('stale consolidation prerequisite')
                target=self.head(principal,item['key'])
                if target and batch['heads'].get(item['key'])!=target['id']:
                    raise Error('target head was not offered')
                sources=list(dict.fromkeys(ref for e in entries for ref in e['sources']))
                deps=list(dict.fromkeys([e['id'] for e in entries if e['key']!=item['key']] +
                                        (target['dependencies'] if target else [])))
                items.append(dict(key=item['key'],summary=item['summary'],kind=item['kind'],tags=item['tags'],
                    sources=sources,dependencies=deps,expected=target['id'] if target else None,
                    pinned=target['pinned'] if target else False,created=None))
            refs=self.write_batch(principal,items) if items else []
            self.db.execute('INSERT INTO approval VALUES(?,?,?)',(job_id,draft_hash,approval_id))
            self.db.execute("UPDATE job SET state='applied' WHERE id=?",(job_id,))
        return tuple(refs)

    def audit(self):
        if self.db.execute('PRAGMA quick_check').fetchone()[0] != 'ok' or self.db.execute('PRAGMA foreign_key_check').fetchone():
            raise Error('database integrity failure')
        for row in self.db.execute('SELECT * FROM source'):
            if digest({'text':row['text']}) != row['ref']:
                raise Error('source integrity failure')
        for row in self.db.execute('SELECT * FROM entry'):
            item = self._entry(row)
            principal = Principal(row['owner'],row['project'])
            for ref in item['sources']:
                self.source(principal,ref)
            actual = {r[0] for r in self.db.execute('SELECT parent FROM dependency WHERE child=?',(row['id'],))}
            if actual != set(item['dependencies']):
                raise Error('dependency integrity failure')
            for ref in actual:
                dep = self.get(principal,ref)
                if item['active'] and (dep['invalidated'] or self.head(principal,dep['key'])['id'] != ref):
                    raise Error('active memory has stale dependencies')
        for row in self.db.execute('SELECT * FROM head'):
            item = self.get(Principal(row['owner'],row['project']),row['ref'])
            if item['key'] != row['topic']:
                raise Error('memory head integrity failure')
        for row in self.db.execute('SELECT * FROM retirement'):
            principal=Principal(row['owner'],row['project'])
            self.source(principal,row['resolution'])
            if not self.get(principal,row['ref'])['invalidated']:
                raise Error('retirement integrity failure')
        for row in self.db.execute('SELECT id,owner,project FROM write_intent'):
            self.write_intent(Principal(row['owner'],row['project']),row['id'])
        return True
