"""Explicit local role calls with shared accounting; no dependency installation.

Useful for offline memory jobs outside `recurse`. Within the main controller the
same role calls are charged at its existing attempted-completion boundary.
"""
from __future__ import annotations
import time
import math
from .clients import CallResult, TransportError
from .compression import TokenMeter, ContextLimitError
from .runtime import BudgetExhausted


class LocalRoleRunner:
    def __init__(self, client, *, max_calls=16, max_input=8192, max_total_units=64000,
                 counter=None, counter_label=None, max_seconds=120):
        for value in (max_calls,max_input,max_total_units):
            if type(value)is not int or value<1:raise ValueError('positive role budget required')
        if type(max_seconds)not in (int,float) or not math.isfinite(max_seconds) or max_seconds<=0:raise ValueError('positive deadline required')
        if not callable(getattr(client,'complete',None)):raise TypeError('local completion client required')
        self.client=client;self.meter=TokenMeter(counter,counter_label)
        self.max_calls,self.max_input,self.max_total=max_calls,max_input,max_total_units
        self.deadline=time.monotonic()+max_seconds;self.events=[];self.units=0

    def __call__(self, *, role, model, system, user, max_tokens):
        if type(max_tokens) is not int or max_tokens < 1:
            raise ValueError("positive output allowance required")
        if len(self.events)>=self.max_calls or time.monotonic()>=self.deadline:
            raise BudgetExhausted('local role budget exhausted')
        n=self.meter.prompt(system,user,model)
        if n>self.max_input:raise ContextLimitError('local role input too large')
        if self.units+n+max_tokens>self.max_total:
            raise BudgetExhausted('reserve input and declared output allowance before role call')
        event={'role':role,'model':model,'input':n,'output':0,'status':'attempted','counter':self.meter.label}
        self.events.append(event);self.units+=n
        try:
            result=self.client.complete(model=model,system=system,user=user,max_tokens=max_tokens,
                                        temperature=0.0,use_headroom=False)
            if not isinstance(result,CallResult):raise TransportError('invalid role result')
            out=self.meter.count(result.text,model);self.units+=out;event['output']=out
            if out>max_tokens or self.units>self.max_total or time.monotonic()>=self.deadline:
                raise BudgetExhausted('role exceeded declared budget; result discarded')
            if result.stop_reason in {'max_tokens','length','error','refused','refusal'}:
                raise TransportError('incomplete role result')
            event['status']='returned';return result
        except BaseException as exc:
            event['status']=type(exc).__name__;raise
