#!/usr/bin/env python3
"""Report the ElevenLabs subscription: tier, credit allowance, usage and reset.

Read-only. Used to size the daily music config (tracks x length) to the plan's
monthly credits without running out. Needs ELEVENLABS_API_KEY.
"""

from __future__ import annotations

import json
import os
import sys
import urllib.request


def _get(path: str, key: str) -> dict:
    req = urllib.request.Request(
        f"https://api.elevenlabs.io/v1{path}",
        headers={"xi-api-key": key, "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.loads(resp.read().decode())


def main() -> int:
    key = os.environ.get("ELEVENLABS_API_KEY", "").strip()
    if not key:
        print("ELEVENLABS_API_KEY not set", file=sys.stderr)
        return 1
    sub = _get("/user/subscription", key)
    tier = sub.get("tier", "?")
    limit = sub.get("character_limit")          # unified credit allowance / period
    used = sub.get("character_count")
    reset = sub.get("next_character_count_reset_unix")
    print(f"tier: {tier}")
    print(f"credit allowance (period): {limit}")
    print(f"used so far: {used}")
    if isinstance(limit, int) and isinstance(used, int):
        print(f"remaining: {limit - used}")
    print(f"next reset (unix): {reset}")
    print(f"can extend / overage: {sub.get('can_extend_character_limit')}")
    # dump the rest for anything useful we didn't name
    extra = {k: v for k, v in sub.items() if k not in (
        "tier", "character_limit", "character_count",
        "next_character_count_reset_unix", "can_extend_character_limit")}
    print("\nfull payload:")
    print(json.dumps(extra, indent=2)[:2000])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
