"""Receipt persistence and offered-version retries, without neural inference."""
import json
from dataclasses import replace
from test_private_memory import Fixture, MemoryStore, MemorySession, MemoryModels, E, CallResult

class WriteReceiptTests(Fixture):
    def proposal(self,summary='Use supplier_id + transaction_id, NOT transaction_id alone.'):
        return {'items':[{'key':'policy','summary':summary,'kind':'constraint','tags':[]}]}
    def test_empty_write_stays_pending_after_reopen(self):
        session=self.session(writer='test')
        user='Correction: use supplier_id + transaction_id, NOT transaction_id alone.'
        self.assertEqual(session.write_turn(user,'Acknowledged.',send=self.sender({'items':[]})),())
        ref=session.last_write['id']
        self.assertEqual(session.last_write['state'],'pending')
        with MemoryStore(self.path) as store:
            current=MemorySession(store,self.p,models=MemoryModels(writer='test'))
            self.assertEqual(store.pending_writes(self.p)[0]['id'],ref)
            found=current.retrieve('supplier_id transaction_id',plan_queries=False)
            self.assertIn(user,found.text)
            self.assertIn(session.last_write['interaction'],found.source_refs)
    def test_committed_receipt_is_idempotent(self):
        session=self.session(writer='test');calls=[]
        def send(**q):calls.append(q);return CallResult(json.dumps(self.proposal()))
        first=session.write_turn('Correct supplier policy.','Acknowledged.',send=send)
        second=session.write_turn('Correct supplier policy.','Acknowledged.',send=send)
        self.assertEqual(first,second);self.assertEqual(len(calls),1)
        self.assertEqual(session.last_write['state'],'committed')
        self.assertEqual(self.s.pending_writes(self.p),[])
    def test_retry_reoffers_current_head_before_inference(self):
        old=self.write('policy','Policy: transaction_id is globally unique.')
        session=self.session(writer='test')
        self.assertEqual(session.write_turn('Correct policy: supplier_id + transaction_id.','Acknowledged.',send=self.sender(self.proposal())),())
        self.assertEqual(self.s.head(self.p,'policy')['id'],old)
        pending=session.last_write['id']
        def send(**q):
            heads=json.loads(q['user'])['heads']
            self.assertEqual([(h['key'],h['id']) for h in heads],[('policy',old)])
            return CallResult(json.dumps(self.proposal()))
        refs=session.retry_write(pending,send=send)
        self.assertEqual(len(refs),1)
        self.assertEqual(self.s.get(self.p,refs[0])['supersedes'],old)
        self.assertEqual(session.last_write['state'],'committed')
    def test_concurrent_head_change_keeps_write_pending(self):
        old=self.write('policy','Old supplier policy.')
        session=self.session(writer='test')
        session.write_turn('Correct supplier policy.','Acknowledged.',send=self.sender({'items':[]}))
        pending=session.last_write['id'];changed=[]
        def send(**q):
            self.assertEqual(json.loads(q['user'])['heads'][0]['id'],old)
            changed.append(self.write('policy','Concurrent host update.',expected=old))
            return CallResult(json.dumps(self.proposal()))
        self.assertEqual(session.retry_write(pending,send=send),())
        self.assertEqual(session.last_write['state'],'pending')
        self.assertEqual(self.s.head(self.p,'policy')['id'],changed[0])
        self.assertEqual(self.s.get(self.p,old)['summary'],'Old supplier policy.')
    def test_pending_write_is_principal_bound(self):
        session=self.session(writer='test')
        session.write_turn('Correct supplier policy.','Acknowledged.',send=self.sender({'items':[]}))
        other=MemorySession(self.s,self.other,models=MemoryModels(writer='test'))
        with self.assertRaises(E):other.retry_write(session.last_write['id'],send=self.sender(self.proposal()))
        self.assertEqual(self.s.pending_writes(self.other),[])
    def test_oversized_writer_packet_keeps_exact_interaction(self):
        session=self.session(writer='test');calls=[]
        self.assertEqual(session.write_turn('u'*4000,'r'*4000,send=lambda **q:calls.append(q)),())
        self.assertEqual(calls,[])
        receipt=self.s.write_intent(self.p,session.last_write['id'])
        self.assertEqual(receipt['user'],'u'*4000);self.assertEqual(receipt['accepted'],'r'*4000)
        self.assertEqual(receipt['state'],'pending')
    def test_pending_capacity_does_not_evict(self):
        self.s.policy=replace(self.s.policy,max_pending=1)
        session=self.session(writer='test')
        session.write_turn('first','ack',send=self.sender({'items':[]}));ref=session.last_write['id']
        with self.assertRaises(E):session.write_turn('second','ack',send=self.sender({'items':[]}))
        self.assertEqual(self.s.pending_writes(self.p)[0]['id'],ref)
    def test_empty_store_and_explicit_lookup_skip_planner(self):
        session=self.session(controller='test');calls=[]
        session.retrieve('supplier',send=lambda **q:calls.append(q))
        self.assertEqual(calls,[])
        self.write('policy','supplier transaction identity')
        found=session.retrieve('supplier',send=lambda **q:calls.append(q),plan_queries=False)
        self.assertEqual(calls,[]);self.assertEqual(len(found.records),1)
        with self.assertRaises(TypeError):session.retrieve('supplier',plan_queries=1)
    def test_nonexistent_model_tags_do_not_hide_current_head(self):
        ref=self.write('policy','supplier transaction identity')
        session=self.session(controller='test')
        plan={'queries':[{'text':'supplier transaction identity','tags':['invented-tag'],'after':None,'before':None}]}
        found=session.retrieve('supplier transaction identity',send=self.sender(plan))
        self.assertEqual([r['id'] for r in found.records],[ref])
    def test_tag_fallback_never_relaxes_time_or_user_scope(self):
        self.write('policy','supplier transaction identity',created='2026-01-01T00:00:00Z')
        session=self.session(controller='test')
        plan={'queries':[{'text':'supplier transaction identity','tags':['invented-tag'],
                          'after':'2050-01-01T00:00:00Z','before':None}]}
        self.assertEqual(session.retrieve('supplier',send=self.sender(plan)).records,())
        other=MemorySession(self.s,self.other,models=MemoryModels(controller='test'))
        self.assertEqual(other.retrieve('supplier',send=self.sender(plan)).records,())
    def test_writer_cannot_supply_authority_or_expected_version(self):
        session=self.session(writer='test');proposal=self.proposal()
        proposal['items'][0]['expected']='invented'
        self.assertEqual(session.write_turn('policy correction','ack',send=self.sender(proposal)),())
        self.assertEqual(session.last_write['state'],'pending')
        self.assertIsNone(self.s.head(self.p,'policy'))
    def test_receipt_integrity_is_checked(self):
        session=self.session(writer='test')
        session.write_turn('policy correction','ack',send=self.sender({'items':[]}))
        self.s.db.execute("UPDATE write_intent SET state='committed' WHERE id=?",(session.last_write['id'],))
        with self.assertRaises(E):self.s.audit()
