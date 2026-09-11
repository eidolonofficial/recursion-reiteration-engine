"""Budgeted proposer capability. The evaluator's storage handle is never a tool input.

The public view has no receipt/output accessor. Confirmation closes generation.
Operator-authored summaries may be selected, but the selector cannot rewrite them.
"""
from __future__ import annotations
from dataclasses import dataclass
import re
from .types import FoldError, Proposal, canonical, data, decode, digest, integer


def _words(s):
    return set(re.findall(r"\w{3,}", s.casefold()))


@dataclass
class Packet:
    text: str
    _sources: dict[str,bytes]
    max_read_bytes: int = 8192

    def read(self, ref: str, start: int = 0, end: int | None = None) -> str:
        """Only exact, offered PUBLIC bytes. No unrestricted store/hash lookup."""
        digest("source",ref)
        if ref not in self._sources:
            raise FoldError("source not granted by this packet capability")
        raw = self._sources[ref]
        integer("start",start,0,len(raw))
        if end is None:
            end = min(len(raw),start+self.max_read_bytes)
        integer("end",end,start,len(raw))
        if end-start > self.max_read_bytes:
            raise FoldError("bounded source-read size exceeded")
        # Byte ranges are explicit here; the Headroom workspace itself uses
        # character offsets. These two wire protocols are deliberately distinct.
        try:
            return raw[start:end].decode("utf-8")
        except UnicodeError as exc:
            raise FoldError("read range must align to UTF-8 boundaries") from exc


def generation_packet(folding, candidate: str, *, query: str = "", max_chars: int = 8192,
                      k: int = 4, selector=None) -> Packet:
    integer("packet budget",max_chars,256,1_000_000)
    integer("selection budget",k,0,100)
    if type(query) is not str:
        raise FoldError("query must be text")
    s=folding.state
    if s["selection_closed"] or s["holdout_spent"]:
        raise FoldError("generation sealed before confirmation; outcomes cannot feed new mutations")
    c=s["candidates"].get(candidate)
    if c is None:
        raise FoldError("unknown candidate")
    p=Proposal.parse(folding.store.json(c["proposal"]))
    if p.base != s["champion"]:
        raise FoldError("stale proposal")
    # These fields are constructed explicitly, never copied from an unrestricted
    # champion/results object. A metric name is safe; held-out metrics are not.
    obj={"schema":"fold-proposer-v1","scope":folding.scope,
         "policy_ref":s["policy"],"ledger_head":folding.store.head(folding.scope),
         "champion_ref":p.base,"artifact_ref":p.artifact,"proposal":data(p),
         "objective":folding.policy.objective,"metric":folding.policy.metric,
         "constraints":{"max_cost":folding.policy.max_cost,"max_seconds":folding.policy.max_seconds,
                        "minimum_effect":folding.policy.min_effect},
         "evidence_counts":{"checked_claims":len(s["claims"]),"memory_records":len(s["memory"])},
         "holdout":{"outcomes_exposed":False,"access":"no confirmation receipts or case access"},
         "authority":"Proposal only. Statistical promotion and formal verification are separate trusted operations.",
         "memory":[]}
    words=_words(query+" "+p.mechanism)
    records=list(s["memory"].items())
    records.sort(key=lambda item:(len(words&_words(item[1]["summary"]+" "+item[1]["next_test"])),item[0]),reverse=True)
    pool=records[:2*k]
    # Expose only summary records to the optional selector, never the store.
    if selector is not None:
        chosen=selector(decode(canonical([{ "id":r,"record":m} for r,m in pool])),k)
        allowed={r for r,_ in pool}
        if type(chosen) is not list or len(chosen)>k or any(type(r)is not str or r not in allowed for r in chosen) or len(set(chosen))!=len(chosen):
            raise FoldError("selector may only choose existing IDs within budget")
        byid=dict(pool);pool=[(r,byid[r])for r in chosen]
    else:
        pool=pool[:k]
    sources={p.base:folding.store.get(p.base),p.artifact:folding.store.get(p.artifact)}
    if len(canonical(obj).decode())>max_chars:
        raise FoldError("required exact proposal/policy exceeds packet budget")
    for r,m in pool:
        item={"id":r,**m}
        obj["memory"].append(item)
        if len(canonical(obj).decode())>max_chars:
            obj["memory"].pop()
        else:
            sources[r]=folding.store.get(r)
    rendered=canonical(obj).decode()
    return Packet(rendered,sources)
