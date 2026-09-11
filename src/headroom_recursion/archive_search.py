"""Bounded exact literal search on currently offered immutable archive sources."""
from __future__ import annotations
from .clients import TransportError


def find_literal(text: str, needle: str, start: int, *, max_matches=3,
                 scan_chars=1000000, context_chars=48):
    if (type(needle)is not str or not needle or len(needle)>256 or
            type(start)is not int or not 0<=start<=len(text)):
        raise TransportError('invalid literal search')
    for value,maximum in ((max_matches,16),(scan_chars,10000000),(context_chars,256)):
        if type(value)is not int or not 1<=value<=maximum:raise TransportError('invalid search budget')
    if scan_chars < len(needle):
        raise TransportError("scan budget must cover the literal")
    stop=min(len(text),start+scan_chars)
    cursor=start;matches=[]
    while len(matches)<max_matches:
        pos=text.find(needle,cursor,stop)
        if pos<0:break
        end=pos+len(needle)
        a=max(0,pos-context_chars);b=min(len(text),end+context_chars)
        matches.append({'start':pos,'end':end,'excerpt_start':a,'text':text[a:b]})
        cursor=pos+1  # preserve overlapping matches
    more=text.find(needle,cursor,stop)>=0
    nxt=cursor if more else max(start+1,stop-len(needle)+1) if stop<len(text) else None
    return {'matches':matches,'next_start':nxt,'complete':nxt is None}
