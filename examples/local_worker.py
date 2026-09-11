#!/usr/bin/env python3
"""A fixed deterministic worker showing the local JSON contract.

Not an inference engine. Replace demo.complete with your own trusted local model
adapter; never claim this demonstration measures a neural model's performance.
"""
import json
import sys
from headroom_recursion import demo
from headroom_recursion.clients import strict_json


def main():
    try:
        request = strict_json(sys.stdin.read(1_000_001))
        if not isinstance(request, dict) or request.get("protocol_version") != 1:
            raise ValueError("unsupported request")
        text = demo.complete(**request)
        print(json.dumps({"protocol_version": 1, "ok": True, "text": text}))
    except Exception:
        print(json.dumps({"protocol_version": 1, "ok": False, "error": "invalid request"}))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
