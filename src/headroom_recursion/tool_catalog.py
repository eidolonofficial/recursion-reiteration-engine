"""Progressive disclosure for an operator-allowlisted local tool catalog.

Discovery does not execute a tool or grant write permission. The host's tool
broker remains the authority. No hidden tools or privileged schemas are offered.
"""
from __future__ import annotations
from .memory.contracts import bounded_text, fields, integer, wire, MemoryContractError


class ToolCatalog:
    def __init__(self, descriptors, *, max_tools=128):
        integer(max_tools,'catalog size',1,4096)
        if type(descriptors)is not list or len(descriptors)>max_tools:raise MemoryContractError('invalid tool catalog')
        self._items={}
        for d in descriptors:
            fields(d,{'name','description','input_schema'})
            bounded_text(d['name'],'tool name',128);bounded_text(d['description'],'description',2000)
            if d['name'] in self._items or type(d['input_schema'])is not dict:raise MemoryContractError('invalid tool descriptor')
            raw=wire(d)
            if len(raw)>16000:raise MemoryContractError('tool descriptor too large')
            import json
            self._items[d['name']]=json.loads(raw)

    def discover(self, query, *, k=5, max_chars=2000):
        from .workspace import _words
        bounded_text(query,'discovery query',1000);integer(k,'K',1,32);integer(max_chars,'catalog budget',64,64000)
        q=_words(query)
        ordered=sorted(self._items.values(),key=lambda d:(-len(q&_words(d['name']+' '+d['description'])),d['name']))
        out=[]
        for d in ordered:
            item={'name':d['name'],'description':d['description'][:160]}
            if len(wire(out+[item]))>max_chars:continue
            out.append(item)
            if len(out)==k:break
        return out

    def schema(self, name):
        import json
        if name not in self._items:raise MemoryContractError('tool not offered')
        return json.loads(wire(self._items[name]))
