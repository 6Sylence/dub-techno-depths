#!/usr/bin/env python3
"""Hide the channel's old public videos (set them to private).

Run via the "Hide old videos" workflow (uses the repo's YouTube secrets).
Only videos whose privacy is currently ``public`` are changed — so the newer
unlisted/private test uploads are left untouched — and each is set to
``HIDE_PRIVACY`` (default: private). Nothing is deleted; flip a video back to
public in YouTube Studio any time.

  HIDE_PRIVACY   private | unlisted   (default: private)
  KEEP_IDS       comma-separated video ids to never touch (optional)
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
    target = os.environ.get("HIDE_PRIVACY", "private").strip().lower()
    if target not in ("private", "unlisted"):
        target = "private"
    keep = {v.strip() for v in os.environ.get("KEEP_IDS", "").split(",") if v.strip()}

    yt = _service()
    ch = yt.channels().list(part="contentDetails", mine=True).execute()
    uploads = ch["items"][0]["contentDetails"]["relatedPlaylists"]["uploads"]

    ids: list[str] = []
    token = None
    while True:
        resp = yt.playlistItems().list(
            part="contentDetails", playlistId=uploads, maxResults=50,
            pageToken=token).execute()
        ids += [it["contentDetails"]["videoId"] for it in resp["items"]]
        token = resp.get("nextPageToken")
        if not token:
            break
    print(f"channel has {len(ids)} uploads")

    changed = 0
    for i in range(0, len(ids), 50):
        batch = ids[i:i + 50]
        info = yt.videos().list(part="status,snippet", id=",".join(batch)).execute()
        for v in info["items"]:
            vid, st = v["id"], v["status"]
            title = v["snippet"]["title"][:60]
            if vid in keep:
                print(f"keep    {vid}  {title}")
                continue
            if st.get("privacyStatus") != "public":          # only hide public (old) videos
                print(f"skip    {vid}  ({st.get('privacyStatus')})  {title}")
                continue
            body = {"id": vid, "status": {"privacyStatus": target}}
            for f in SAFE_STATUS_FIELDS:
                if f in st:
                    body["status"][f] = st[f]
            yt.videos().update(part="status", body=body).execute()
            changed += 1
            print(f"hid ->{target}  {vid}  {title}")

    print(f"done: {changed} video(s) set to {target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
