#!/usr/bin/env python3
"""Restore specific videos to a given privacy (default: public).

Only the exact video ids in RESTORE_IDS are touched — nothing else on the
channel is affected. Existing safe status fields are preserved.

  RESTORE_IDS       comma-separated video ids to restore (required)
  RESTORE_PRIVACY   public | unlisted | private   (default: public)

Run via the "Restore videos" workflow (uses the repo's YouTube secrets).
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.upload_youtube import _service  # noqa: E402

SAFE_STATUS_FIELDS = ("license", "embeddable", "publicStatsViewable",
                      "selfDeclaredMadeForKids")


def main() -> int:
    target = os.environ.get("RESTORE_PRIVACY", "public").strip().lower()
    if target not in ("public", "unlisted", "private"):
        target = "public"
    ids = [v.strip() for v in os.environ.get("RESTORE_IDS", "").split(",") if v.strip()]
    if not ids:
        print("no RESTORE_IDS given — nothing to do")
        return 0

    yt = _service()
    info = yt.videos().list(part="status,snippet", id=",".join(ids)).execute()
    found = {v["id"]: v for v in info["items"]}

    changed = 0
    for vid in ids:
        v = found.get(vid)
        if not v:
            print(f"missing  {vid}  (not on this channel?)")
            continue
        st = v["status"]
        title = v["snippet"]["title"][:60]
        if st.get("privacyStatus") == target:
            print(f"already  {vid}  ({target})  {title}")
            continue
        body = {"id": vid, "status": {"privacyStatus": target}}
        for f in SAFE_STATUS_FIELDS:
            if f in st:
                body["status"][f] = st[f]
        yt.videos().update(part="status", body=body).execute()
        changed += 1
        print(f"restored ->{target}  {vid}  {title}")

    print(f"done: {changed} video(s) set to {target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
