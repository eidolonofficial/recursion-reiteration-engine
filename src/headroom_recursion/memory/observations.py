"""Host-recorded tool observations with recoverable masking, never model assertions."""
from __future__ import annotations

import json
from ..compression import ContextLimitError
from .contracts import MemoryContractError as Error, bounded_text, digest, fields, integer, timestamp, wire


class ObservationLedger:
    def __init__(self, store, principal):
        self.store,self.principal=store,principal
        store._scope(principal)
        store.db.executescript('''
        CREATE TABLE IF NOT EXISTS observation(id TEXT PRIMARY KEY,owner TEXT,project TEXT,
          body TEXT NOT NULL,resolution TEXT);
        CREATE INDEX IF NOT EXISTS observations_scope ON observation(owner,project);
        ''')

    def record(self, label, output, *, status, revision, critical=False, exit_code=None, failed_tests=None, outcome=""):
        if exit_code is not None and (type(exit_code) is not int or not -2147483648<=exit_code<=2147483647):
            raise Error("invalid exit code")
        if failed_tests is not None:
            integer(failed_tests,"failed tests",0,1000000)
        bounded_text(outcome,"actionable outcome",1000,empty=True)
        if status=="success" and ((exit_code is not None and exit_code!=0) or (failed_tests is not None and failed_tests>0)):
            raise Error("success contradicts exit status or failed tests")
        bounded_text(label,'observation label',160)
        bounded_text(revision,'revision',200)
        if type(status) is not str or status not in {'success','failure','unknown'} or type(critical)is not bool:
            raise Error('host observation needs a valid status and critical flag')
        ref=self.store.add_source(self.principal,output)
        body={'label':label,'source':ref,'status':status,'revision':revision,'critical':critical,
              'created':timestamp(),'chars':len(output),'lines':len(output.splitlines()),
              'exit_code':exit_code,'failed_tests':failed_tests,'outcome':outcome,
              'authority':'host-recorded outcome, not a proof'}
        oid=digest(body)
        with self.store.transaction():
            self.store.db.execute('INSERT INTO observation VALUES(?,?,?,?,NULL)',
                (oid,*self.store._scope(self.principal),wire(body)))
        return oid

    def rows(self):
        out=[]
        for r in self.store.db.execute('SELECT * FROM observation WHERE owner=? AND project=? ORDER BY rowid',
                                      self.store._scope(self.principal)):
            body=json.loads(r['body'])
            if digest(body)!=r['id']:raise Error('observation integrity failure')
            self.store.source(self.principal,body['source'])
            if r['resolution'] is not None:
                self.store.source(self.principal,r['resolution'])
            out.append(dict(body,id=r['id'],resolved=bool(r['resolution']),resolution_source=r['resolution']))
        return out

    def resolve(self, observation_id, *, resolution_source):
        # Host must provide an actual source. A worker never receives this method.
        self.store.source(self.principal,resolution_source)
        with self.store.transaction():
            n=self.store.db.execute('UPDATE observation SET resolution=? WHERE id=? AND owner=? AND project=? AND resolution IS NULL',
                (resolution_source,observation_id,*self.store._scope(self.principal))).rowcount
            if n!=1:raise Error('observation unavailable or already resolved')

    def view(self, *, max_chars=6000, recent=2, max_items=8, revision=None):
        integer(max_chars,'observation budget',256,64000)
        integer(recent,'recent count',0,16);integer(max_items,'item cap',1,64)
        rows=self.rows()
        required=[r for r in rows if not r['resolved'] and (r['critical'] or r['status']!='success')]
        optional=[r for r in rows if r not in required][-max_items:]
        sources={};out=[];pins=[]
        def render():return wire({'observations':out,'omitted_count':len(rows)-len(out)})
        for r in required:
            text=self.store.source(self.principal,r['source'])
            item={k:r[k] for k in ('id','label','status','revision','source','authority','exit_code','failed_tests','outcome')}
            item.update(exact_output=text,masked=False,stale=None if revision is None else revision!=r['revision'])
            out.append(item);sources[r['source']]=text;pins.append(wire(item))
            if len(out)>max_items or len(render())>max_chars:
                raise ContextLimitError('unresolved tool evidence exceeds observation budget; not silently masked')
        for index,r in reversed(list(enumerate(optional))):
            if len(out)>=max_items:break
            text=self.store.source(self.principal,r['source'])
            item={k:r[k] for k in ('id','label','status','revision','source','chars','lines','resolved','resolution_source','authority','exit_code','failed_tests','outcome')}
            item.update(stale=None if revision is None else revision!=r['revision'],masked=True)
            if index>=len(optional)-recent and len(text)<=512:
                item.update(exact_output=text,masked=False)
            else:
                item['detail']='Bulk output archived; request exact source text before relying on details.'
            out.append(item)
            if len(render())>max_chars:
                out.pop();continue
            sources[r['source']]=text
            if r['resolution_source']:
                sources[r['resolution_source']]=self.store.source(self.principal,r['resolution_source'])
        return {'text':render(),'sources':sources,'required_pins':pins,'shown':len(out),'total':len(rows),
                'raw_chars':sum(len(self.store.source(self.principal,r['source'])) for r in rows)}
