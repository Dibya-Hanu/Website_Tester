#!/usr/bin/env python3
"""API readiness check. Never launches a scan against an unapproved target."""
import json
import sys
import httpx

base = sys.argv[1] if len(sys.argv)>1 else "http://127.0.0.1:8080"
with httpx.Client(base_url=base,timeout=15) as client:
    for path in ["/api/health","/api/policy","/api/tools"]:
        result=client.get(path)
        result.raise_for_status()
        print(path,json.dumps(result.json(),indent=2))
