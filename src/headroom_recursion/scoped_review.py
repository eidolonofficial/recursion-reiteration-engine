"""Incremental exact-record checking with dependency invalidation.

This is NOT summary-only LLM judging. The host declares record/checker coverage.
A receipt certifies a check of exact statements and their dependency closure, not
an entire proof or a universal research target. Whole-candidate judging stays the
default in the existing recurrence.
"""
from __future__ import annotations
from dataclasses import dataclass
import copy
from typing import Callable
from .memory.contracts import MemoryContractError as Error, bounded_text, digest, wire


@dataclass(frozen=True)
class ReviewRecord:
    key: str
    statement: str
    assumptions: tuple[str,...] = ()
    dependencies: tuple[str,...] = ()
    evidence: str = ''
    evidence_class: str = 'finite'

    def __post_init__(self):
        bounded_text(self.key,'record key',128)
        bounded_text(self.statement,'exact statement',100000)
        bounded_text(self.evidence,'evidence',1000000,empty=True)
        for name in ('assumptions','dependencies'):
            value=getattr(self,name)
            if type(value)is not tuple or any(type(v)is not str or not v for v in value):raise Error('invalid review relationships')
            if len(value)>128 or len(set(value))!=len(value):raise Error('duplicate or excessive review relationships')
        if self.evidence_class not in {'finite','empirical','formal','heuristic'}:raise Error('invalid evidence class')


@dataclass(frozen=True)
class Reviewer:
    identity: str
    evidence_class: str
    check: Callable

    def __post_init__(self):
        bounded_text(self.identity,'reviewer identity',200)
        if self.evidence_class not in {'finite','empirical','formal','heuristic'} or not callable(self.check):
            raise Error('invalid host reviewer')


class ReviewGraph:
    def __init__(self, *, scope: str, max_closure_chars=1000000):
        self.scope=bounded_text(scope,'review scope',200)
        if type(max_closure_chars)is not int or max_closure_chars<1:raise Error('invalid review budget')
        self.limit=max_closure_chars
        self.records={};self.checkers={};self.receipts={};self.events=[]
        self.generations={};self.generation=0

    def register(self, record: ReviewRecord, reviewer: Reviewer):
        if not isinstance(record,ReviewRecord) or not isinstance(reviewer,Reviewer) or record.evidence_class!=reviewer.evidence_class:
            raise Error('review scope/class mismatch')
        old=self.records.get(record.key);old_checker=self.checkers.get(record.key)
        self.records[record.key]=record;self.checkers[record.key]=reviewer
        try:self.closure(record.key)
        except BaseException:
            if old is None:self.records.pop(record.key);self.checkers.pop(record.key)
            else:self.records[record.key]=old;self.checkers[record.key]=old_checker
            raise
        # Object identity matters as well as the version string during this process.
        if old!=record or old_checker is None or old_checker.identity!=reviewer.identity or old_checker.check is not reviewer.check:
            self.generation+=1
            self.generations[record.key]=self.generation
            self.invalidate(record.key)

    def closure(self,key):
        seen=set(); visiting=set();result=[]
        def visit(k):
            if k in visiting:raise Error('review dependency cycle')
            if k in seen:return
            if k not in self.records:raise Error('missing exact review dependency')
            if len(visiting)>=256:raise Error("review dependency depth exceeds 256")
            visiting.add(k)
            for parent in self.records[k].dependencies:visit(parent)
            visiting.remove(k);seen.add(k);result.append(self.records[k])
        visit(key)
        if sum(len(wire(r.__dict__)) for r in result)>self.limit:raise Error('exact review closure exceeds limit')
        return tuple(result)

    def fingerprint(self,key):
        return digest({'scope':self.scope,'closure':[r.__dict__ for r in self.closure(key)],
                       'checkers':[(self.checkers[r.key].identity,self.generations.get(r.key,0)) for r in self.closure(key)]})

    def invalidate(self,key):
        affected={key};changed=True
        while changed:
            before=len(affected)
            affected.update(k for k,r in self.records.items() if set(r.dependencies)&affected)
            changed=len(affected)!=before
        for k in affected:self.receipts.pop(k,None)
        self.events.append({'event':'invalidated','records':sorted(affected)})

    def review(self,key):
        closure=self.closure(key)
        # Revalidate exact dependency receipts before using a cached descendant.
        for r in closure:
            h=self.fingerprint(r.key)
            prior=self.receipts.get(r.key)
            if prior and prior['input']==h:
                self.verify_receipt(prior)
                continue
            checker=self.checkers[r.key]
            try:passed=checker.check(r,self.closure(r.key))
            except Exception as exc:
                self.invalidate(r.key)
                raise Error('scoped verifier failed') from exc
            if self.fingerprint(r.key)!=h:
                self.invalidate(r.key);raise Error("record changed during verification")
            if type(passed)is not bool or not passed:
                self.invalidate(r.key);raise Error('scoped verifier rejected')
            receipt={'scope':self.scope,'record':r.key,'input':h,'verifier':checker.identity,
                     'evidence_class':r.evidence_class,'covers':[p.key for p in self.closure(r.key)],
                     'coverage':'exact declared record and dependencies only','settles_target':False}
            receipt['id']=digest(receipt)
            self.receipts[r.key]=receipt
            self.events.append({'event':'checked','record':r.key,'closure_chars':sum(len(wire(p.__dict__)) for p in self.closure(r.key))})
        return copy.deepcopy(self.receipts[key])

    def verify_receipt(self,receipt):
        if type(receipt)is not dict or receipt.get('record')not in self.receipts:raise Error('unissued scoped receipt')
        known=self.receipts[receipt['record']]
        body={k:v for k,v in receipt.items() if k!='id'}
        if receipt.get('id')!=digest(body) or receipt.get('settles_target') is not False or receipt!=known or receipt['input']!=self.fingerprint(receipt['record']):raise Error('forged or stale receipt')
        return True
