"""Long-session packet pressure must not truncate evidence or lose pending work."""
import json
from dataclasses import replace
from test_private_memory import Fixture, E, CallResult, ContextLimitError
from headroom_recursion.memory.pipeline import PROMPTS
from headroom_recursion.tool_catalog import ToolCatalog

class WholePacketTests(Fixture):
    def test_recent_window_is_selected_as_whole_summaries(self):
        self.write("controller-input","evidence for a nonempty lookup")
        session=self.session(controller='supplied')
        summaries=['summary '+str(i)+' '+('x'*730)+' DO NOT ACCEPT.' for i in range(12)]
        session.recent=[{'accepted_summaries':summaries[i:i+4]} for i in range(0,12,4)]
        sent=[]
        def send(**q):
            sent.append(q)
            return CallResult('{"queries":[{"text":"evidence","tags":[],"after":null,"before":null}]}')
        session.retrieve('evidence',send=send)
        self.assertEqual(len(sent),1)
        self.assertLessEqual(len(sent[0]['system'])+len(sent[0]['user']),session.policy.packet_chars)
        selected=[s for r in json.loads(sent[0]['user'])['recent'] for s in r['accepted_summaries']]
        self.assertGreater(len(selected),0);self.assertLess(len(selected),12)
        self.assertTrue(all(s in summaries and s.endswith('DO NOT ACCEPT.') for s in selected))
        self.assertEqual(session.recent[0]['accepted_summaries'],summaries[:4])

    def test_large_writer_interaction_archived_without_model_call(self):
        session=self.session(writer='supplied');calls=[]
        out=session.write_turn('x'*4000,'y'*4000,send=lambda **q:calls.append(q))
        self.assertEqual(out,());self.assertEqual(calls,[])
        self.assertTrue(any('y'*4000 in r[0] for r in self.s.db.execute('SELECT text FROM source')))

    def test_writer_head_packet_is_bounded_without_partial_records(self):
        for i in range(5):self.write('topic'+str(i),'evidence '+('x'*720)+' DO NOT FORGET.')
        session=self.session(writer='supplied');session.retrieve('evidence');sent=[]
        def send(**q):
            sent.append(q);return CallResult('{"items":[]}')
        session.write_turn('task '+'x'*2600,'response '+'y'*2300,send=send)
        self.assertEqual(len(sent),1)
        self.assertLessEqual(len(sent[0]['system'])+len(sent[0]['user']),self.s.policy.packet_chars)
        heads=json.loads(sent[0]['user'])['heads']
        self.assertGreater(len(heads),0);self.assertLess(len(heads),5)
        self.assertTrue(all(h['summary'].endswith('DO NOT FORGET.') for h in heads))

    def test_consolidation_queues_only_the_whole_records_offered(self):
        refs=[self.write(str(i),'entry '+str(i)+' '+('x'*740)) for i in range(16)]
        session=self.session(consolidator='supplied');sent=[]
        def send(**q):sent.append(q);return CallResult('{"items":[]}')
        proposal=session.consolidate(send=send)
        offered=json.loads(sent[0]['user'])['entries'];n=len(offered)
        self.assertGreater(n,0);self.assertLess(n,16)
        self.assertLessEqual(len(sent[0]['system'])+len(sent[0]['user']),self.s.policy.packet_chars)
        self.assertEqual(self.s.pending_count(self.p),16-n)
        self.assertEqual(set(proposal['heads']),{e['key'] for e in offered})
        self.assertTrue(all(self.s.get(self.p,r)['summary'] for r in refs))

    def test_stale_queue_entries_are_retired_not_sources(self):
        old=self.write('a','old evidence');new=self.write('a','new evidence',expected=old)
        entries=self.s.pending_entries(self.p)
        self.assertEqual([e['id'] for e in entries],[new]);self.assertEqual(self.s.pending_count(self.p),1)
        self.assertEqual(self.s.get(self.p,old)['summary'],'old evidence')

    def test_selected_reservation_checks_current_heads(self):
        old=self.write('a','old evidence');self.s.pending_entries(self.p)
        new=self.write('a','new evidence',expected=old)
        with self.assertRaises(E):self.s.reserve_batch(self.p,refs=(old,))
        self.assertIn(new,[e['id'] for e in self.s.pending_entries(self.p)])
        self.assertEqual(self.s.db.execute('SELECT count(*) FROM job').fetchone()[0],0)

    def test_impossible_consolidation_packet_keeps_queue(self):
        self.write(summary='full source evidence '+('x'*700))
        session=self.session(consolidator='supplied')
        session.policy=replace(session.policy,packet_chars=256)
        with self.assertRaises(ContextLimitError):session.consolidate(send=self.sender({'items':[]}))
        self.assertEqual(self.s.pending_count(self.p),1)
        self.assertEqual(self.s.db.execute('SELECT count(*) FROM job').fetchone()[0],0)

    def test_catalog_does_not_fill_budget_with_irrelevant_tools(self):
        catalog=ToolCatalog([dict(name='read_file',description='Read project source files',input_schema={})])
        self.assertEqual(catalog.discover('unrelated-zebra'),[])
        self.assertEqual(catalog.discover('!'),[])
        self.assertEqual(catalog.discover('source')[0]['name'],'read_file')
