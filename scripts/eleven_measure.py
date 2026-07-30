#!/usr/bin/env python3
"""Measure the real credit cost of ElevenLabs Music, then size the daily config.

Reads the credit balance, generates one short test track, reads the balance
again, and prints the exact cost per second/minute plus a recommended
tracks x length budget for the month. Spends a small amount of credits (one
~30s generation). Needs ELEVENLABS_API_KEY.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src import ai_music  # noqa: E402

TEST_SECONDS = 30
VIDEOS_PER_DAY = 2          # morning + afternoon long uploads


def _used(key: str) -> int:
    req = urllib.request.Request(
        "https://api.elevenlabs.io/v1/user/subscription",
        headers={"xi-api-key": key, "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        d = json.loads(resp.read().decode())
    return int(d["character_count"]), int(d["character_limit"])


def main() -> int:
    key = os.environ.get("ELEVENLABS_API_KEY", "").strip()
    if not key:
        print("ELEVENLABS_API_KEY not set", file=sys.stderr)
        return 1

    used_before, limit = _used(key)
    prompt = ai_music.build_prompt({"title": "Big Room", "audio": {"bpm": 128}},
                                   "energy", "test")
    dest = Path(tempfile.mkdtemp()) / "measure.mp3"
    ai_music.generate_track(prompt, TEST_SECONDS * 1000, dest)
    used_after, _ = _used(key)

    cost = used_after - used_before
    per_s = cost / TEST_SECONDS
    per_min = per_s * 60
    print(f"cost of {TEST_SECONDS}s generation: {cost} credits")
    print(f"  ≈ {per_s:.1f} credits/sec  ≈ {per_min:.0f} credits/min")
    remaining = limit - used_after
    print(f"remaining this period: {remaining} of {limit}")
    if per_min > 0:
        month_minutes = remaining / per_min
        print(f"\nAffordable this period: ~{month_minutes:.0f} min of NEW music")
        # Budget across ~30 days x VIDEOS_PER_DAY, keep 15% safety margin.
        per_video_min = (month_minutes * 0.85) / (30 * VIDEOS_PER_DAY)
        print(f"Safe per-video unique music (2 vids/day, 15% margin): "
              f"~{per_video_min:.1f} min")
        # Suggest N tracks of ~180s (3 min) each.
        n = max(1, int((per_video_min * 60) // 180))
        print(f"Suggested config: AI_TRACKS={n}  AI_TRACK_SECONDS=180 "
              f"(= {n*3} min unique music per video, looped to fill the runtime)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
