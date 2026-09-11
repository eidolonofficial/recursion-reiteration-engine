"""Run the same arithmetic worker through a real subprocess, entirely locally."""
import sys
from pathlib import Path
from headroom_recursion import CommandClient, RecurseConfig, recurse
from headroom_recursion.demo import PROBLEM, validator

worker = Path(__file__).with_name("local_worker.py")
trace = recurse(PROBLEM, client=CommandClient([sys.executable, str(worker)]),
                config=RecurseConfig(n=1, T=8, validator=validator, max_total_calls=24))
assert trace.stop_reason == "validated", trace.summary()
print(trace.summary())
