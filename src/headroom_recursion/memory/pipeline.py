"""Bounded private memory roles and explicit, staged offline consolidation.

The built-in retrieval ranker is lexical, not a vector/semantic model. All model
roles are optional, operator supplied, and use the host's metered call boundary.
Original evidence and verification authority remain outside model write access.
"""
from __future__ import annotations
from dataclasses import asdict, dataclass
import difflib
import json
import re
import time
from ..clients import CallResult, strict_json
from ..compression import ContextLimitError
from .contracts import (MemoryContractError as Error, MemoryModels, Principal,
                        KINDS, bounded_text, digest, fields, integer, tags, timestamp, wire)
from .store import MemoryStore

PROMPTS = {
    'controller': 'Plan bounded private-memory queries, not answers. Return only {"queries":[{"text":"standalone query","tags":[],"after":null,"before":null}]}. Use only supplied recent context. Dates require timezones. Do not alter identity, scope, budget or authority.',
    'selector': 'Select relevant existing IDs only. Return {"keep":["offered id"]}, at most K. No rewriting, new IDs, explanations, instructions or proof claims. Host-required pins cannot be removed.',
    'writer': 'Propose reusable memory ONLY from this accepted interaction/delta and supplied heads. Return {"items":[{"key":"stable topic","summary":"self-contained advisory record","kind":"fact|decision|constraint|failure|hypothesis|procedure|observation","tags":[]}]}. Preserve negations, assumptions, exceptions and uncertainty. No search or authority changes. Return {"items":[]} when unsupported. Existing keys may be changed only if their exact head was offered.',
    'consolidator': 'Offline private-memory proposal, not an answer or shared graph. Return {"items":[{"key":"topic","summary":"self-contained advisory record","kind":"fact|decision|constraint|failure|hypothesis|procedure|observation","tags":[],"entries":["offered entry id"]}]}. Preserve assumptions, failures and uncertainty. Cite only current offered entries. Do not claim proof, execute tools or publish. The host reviews every proposal separately.'
}


@dataclass(frozen=True)
class Selection:
    records: tuple[dict, ...]
    text: str
    source_refs: tuple[str, ...]
    required_pins: tuple[str, ...] = ()


def _terms(text):
    return set(re.findall(r"[\w-]+", text.casefold()))


class MemorySession:
    def __init__(self, store, principal, *, models=MemoryModels()):
        if not isinstance(store,MemoryStore) or not isinstance(principal,Principal) or not isinstance(models,MemoryModels):
            raise Error('invalid memory session')
        self.store,self.principal,self.models=store,principal,models
        self.policy=store.policy
        self.recent=[]
        self.turns=0
        self.events=[]
        self.event_sequence=0
        self.last_selection=Selection((),'',())

    @property
    def identity(self):
        return digest({'schema':'private-delta-v1','database':self.store.identity,
                       'principal':asdict(self.principal),'policy':asdict(self.policy),
                       'models':asdict(self.models),'retrieval':'lexical-word-overlap/v1'})

    def _emit(self,event):
        self.event_sequence+=1
        self.events.append(dict(sequence=self.event_sequence,**event))
        if len(self.events)>2048:
            del self.events[:-2048]

    def _call(self,role,payload,send):
        model=getattr(self.models,role)
        if model is None:
            return None
        if not callable(send):
            raise Error('configured memory roles require a metered sender')
        system,user=PROMPTS[role],wire(payload)
        if len(system)+len(user)>self.policy.packet_chars:
            raise ContextLimitError('memory role packet exceeds character cap')
        start=time.monotonic()
        try:
            result=send(role='memory_'+role,model=model,system=system,user=user,max_tokens=1024)
            if not isinstance(result,CallResult) or result.stop_reason in {'length','max_tokens','error','refusal','refused'}:
                raise Error('incomplete memory role response')
            if type(result.text) is not str or len(result.text)>self.policy.packet_chars:
                raise Error('memory role response exceeds cap')
            value=strict_json(result.text)
            self._emit({'stage':role,'mode':'supplied-model','seconds':time.monotonic()-start,
                        'input_chars':len(system)+len(user),'output_chars':len(result.text)})
            return value
        except Exception as exc:
            self._emit({'stage':role,'mode':'failed','error':type(exc).__name__})
            raise

    def _plan(self,query,send):
        fallback=[dict(text=query,tags=[],after=None,before=None)]
        if self.models.controller is None:
            self._emit({'stage':'controller','mode':'literal-query-fallback'})
            return fallback
        obj=self._call('controller',{'query':query,'recent':self.recent[-3:],
                                    'max_queries':self.policy.max_queries},send)
        fields(obj,{'queries'})
        qs=obj['queries']
        if type(qs) is not list or not 1<=len(qs)<=self.policy.max_queries:
            raise Error('invalid memory query count')
        for q in qs:
            fields(q,{'text','tags','after','before'})
            bounded_text(q['text'],'query',1600)
            tags(q['tags'])
            for name in ('after','before'):
                if q[name] is not None:
                    q[name]=timestamp(q[name])
            if q['after'] and q['before'] and q['after']>q['before']:
                raise Error('inverted query window')
        return qs

    @staticmethod
    def _public(item):
        return {k:item[k] for k in ('id','key','summary','kind','created','version','tags',
                                    'sources','dependencies','pinned','authority')}

    def retrieve(self,query,*,k=None,send=None):
        bounded_text(query,'query',1600)
        k=self.policy.k if k is None else integer(k,'K',1,self.policy.k)
        start=time.monotonic()
        try:
            qs=self._plan(query,send)
        except (Error,ValueError,TypeError) as exc:
            self._emit({'stage':'controller','mode':'literal-query-fallback','error':type(exc).__name__})
            qs=[dict(text=query,tags=[],after=None,before=None)]
        # Pins are host-authored, current and scope-bound. A model query cannot hide them.
        pins=[r for r in self.store.candidates(self.principal) if r['pinned']]
        if len(pins)>k:
            raise ContextLimitError('required memory pins exceed K; no pin was dropped')
        qs=qs[:2*k]
        div,rem=divmod(2*k,len(qs)); quotas=[div+(i<rem) for i in range(len(qs))]
        candidates={}; scores={}; historical=set()
        for q,quota in zip(qs,quotas):
            terms=_terms(q['text'])
            pool=self.store.candidates(self.principal,item_tags=q['tags'],after=q['after'],before=q['before'])
            ranked=[]
            for row in pool:
                terms_in_record=_terms(row['key']+' '+row['summary']+' '+' '.join(row['tags']))
                score=len(terms & terms_in_record)
                if score:
                    ranked.append((score,row))
            ranked.sort(key=lambda p:(-p[0],-p[1]['version'],p[1]['id']))
            for score,row in ranked[:quota]:
                candidates[row['id']]=row
                if q['before'] is not None:
                    historical.add(row['id'])
                scores[row['id']]=max(score,scores.get(row['id'],0))
        for row in pins:
            candidates[row['id']]=row
            scores[row['id']]=float('inf')
        ordered=sorted(candidates,key=lambda ref:(-scores[ref],ref))[:2*k]
        pin_ids=[r['id'] for r in pins]
        offered=[]
        for ref in ordered:
            rows=[self._public(candidates[r]) for r in offered+[ref]]
            if len(PROMPTS['selector'])+len(wire({'queries':qs,'K':k,'candidates':rows}))<=self.policy.packet_chars:
                offered.append(ref)
            elif ref in pin_ids:
                raise ContextLimitError('required memory pin exceeds packet cap')
        selected=offered[:k]
        if self.models.selector is not None and offered:
            try:
                obj=self._call('selector',{'queries':qs,'K':k,'candidates':[self._public(candidates[r]) for r in offered]},send)
                fields(obj,{'keep'}); keep=obj['keep']
                if type(keep) is not list or len(keep)>k or any(type(r) is not str for r in keep) or len(set(keep))!=len(keep) or not set(keep)<=set(offered):
                    raise Error('selector must choose unique offered IDs only')
                selected=pin_ids+[r for r in keep if r not in pin_ids][:k-len(pin_ids)]
            except (Error,ValueError,TypeError) as exc:
                self._emit({'stage':'selector','mode':'lexical-order-fallback','error':type(exc).__name__})
        else:
            self._emit({'stage':'selector','mode':'lexical-order-fallback'})
        # Recheck heads after an optional model call to reject concurrent stale selection.
        for ref in selected:
            row=self.store.get(self.principal,ref)
            if row['invalidated'] or ((ref not in historical or ref in pin_ids) and self.store.head(self.principal,row['key'])['id']!=ref):
                raise Error('memory changed during selection; retrieve again')
        rows=tuple(dict(self._public(candidates[r]),historical_query=r in historical) for r in selected)
        text=wire({'records':rows,'coverage':'advisory memory, not proof or instructions'}) if rows else ''
        if len(text)>self.policy.packet_chars:
            raise ContextLimitError('whole selected records exceed packet cap')
        refs=tuple(dict.fromkeys(ref for r in selected for ref in candidates[r]['sources']))
        self.store.touch(self.principal,selected)
        result=Selection(rows,text,refs,tuple(candidates[r]['summary'] for r in selected if candidates[r]['pinned']))
        self.last_selection=result
        self._emit({'stage':'retrieve','queries':len(qs),'quotas':quotas,'coarse_count':min(len(candidates),2*k),
                    'selected_count':len(rows),'budget':k,'ranker':'lexical-word-overlap/v1',
                    'packet_chars':len(text),'seconds':time.monotonic()-start})
        return result

    def write_turn(self,user_text,response_text,*,send=None,source_refs=None):
        bounded_text(user_text,'user interaction',4000,empty=True)
        bounded_text(response_text,'accepted response/delta',4000,empty=True)
        if not user_text.strip() and not response_text.strip():
            return ()
        if source_refs is None:
            source_refs=(self.store.add_source(self.principal,wire({'user':user_text,'accepted':response_text})),)
        if type(source_refs) not in (tuple,list) or not 1<=len(source_refs)<=8:
            raise Error('invalid writer sources')
        for ref in source_refs:
            self.store.source(self.principal,ref)
        # Capture only the actually offered heads BEFORE any writer call.
        offered={}
        for selected in self.last_selection.records:
            head=self.store.head(self.principal,selected['key'])
            if head and head['id']==selected['id'] and not head['invalidated']:
                offered[head['key']]=head
        snapshot={key:row['id'] for key,row in offered.items()}
        payload={'user':user_text,'accepted_response_or_delta':response_text,
                 'heads':[self._public(r) for r in offered.values()],
                 'summary_chars':self.policy.summary_chars,'max_items':self.policy.max_writes}
        if self.models.writer is not None:
            try:
                obj=self._call('writer',payload,send); fields(obj,{'items'}); items=obj['items']
                if type(items) is not list or len(items)>self.policy.max_writes:
                    raise Error('invalid writer count')
                for item in items:
                    fields(item,{'key','summary','kind','tags'})
                    bounded_text(item['key'],'writer key',160)
                    bounded_text(item['summary'],'writer summary',self.policy.summary_chars)
                    if type(item['kind']) is not str or item['kind'] not in KINDS:
                        raise Error('invalid writer kind')
                    tags(item['tags'])
            except (Error,ValueError,TypeError) as exc:
                self._emit({'stage':'writer','mode':'rejected-no-write','error':type(exc).__name__})
                return ()
        else:
            # Store the complete exact delta, or decline. No negation can be cut off.
            summary='Exact accepted delta (advisory): '+response_text
            if not response_text.strip() or len(summary)>self.policy.summary_chars:
                self._emit({'stage':'writer','mode':'archive-only','reason':'whole delta does not fit'})
                return ()
            items=[dict(key='turn-'+digest([user_text,response_text])[:24],summary=summary,
                        kind='observation',tags=['exact-delta'])]
            self._emit({'stage':'writer','mode':'exact-delta-fallback'})
        prepared=[]
        for item in items:
            key=item['key']
            prior=offered.get(key)
            # Deterministic exact-delta replays may be idempotent; models cannot gain this exception.
            expected=snapshot.get(key)
            if self.models.writer is None:
                current=self.store.head(self.principal,key)
                expected=current['id'] if current else None
            prepared.append(dict(key=key,summary=item['summary'],kind=item['kind'],sources=list(source_refs),
                tags=item['tags'],expected=expected,created=None,pinned=prior['pinned'] if prior else False,
                dependencies=prior['dependencies'] if prior else []))
        try:
            refs=tuple(self.store.write_batch(self.principal,prepared)) if prepared else ()
        except Error as exc:
            self._emit({'stage':'writer','mode':'rejected-no-write','error':str(exc)})
            return ()
        # A bounded summary window, not stored raw transcripts or inferred state.
        self.recent=(self.recent+[{'accepted_summaries':[i['summary'] for i in items]}])[-3:]
        self.turns+=1
        self._emit({'stage':'write','refs':list(refs),'consolidation_due':self.consolidation_due})
        return refs

    def accepted_revision(self,problem,old,new,notes,*,send=None):
        if old==new:
            return ()
        refs=[self.store.add_source(self.principal,new)]
        if old:
            refs.insert(0,self.store.add_source(self.principal,old))
        delta=''.join(difflib.unified_diff(old.splitlines(keepends=True),new.splitlines(keepends=True),n=1))
        if len(problem)>4000 or len(delta)>4000:
            self._emit({'stage':'writer','mode':'archive-only','reason':'exact task/delta exceeds role cap'})
            return ()
        return self.write_turn(problem,delta,send=send,source_refs=tuple(refs))

    @property
    def consolidation_due(self):
        count=self.store.pending_count(self.principal)
        return count>0 and (self.turns>=self.policy.consolidate_every or count>=self.policy.consolidate_every)

    def consolidate(self,*,send=None):
        if self.models.consolidator is None:
            raise Error('offline consolidation requires an explicit model')
        batch=self.store.reserve_batch(self.principal)
        if batch is None:
            return None
        try:
            entries=[self._public(e) for e in batch['entries'] if not e['invalidated'] and batch['heads'][e['key']]==e['id']]
            obj=self._call('consolidator',{'entries':entries,'max_items':self.policy.max_writes,
                                         'summary_chars':self.policy.summary_chars},send)
            h=self.store.stage(self.principal,batch['id'],obj)
            self.turns=0
            self._emit({'stage':'consolidate','job':batch['id'],'status':'private-proposal-awaiting-host-review'})
            return {'job':batch['id'],'draft_hash':h,'draft':obj,'heads':batch['heads'],
                    'applied':False,'shared':False}
        except BaseException:
            self.store.fail_job(self.principal,batch['id'])
            raise
