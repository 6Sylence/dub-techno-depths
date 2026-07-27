#!/usr/bin/env python3
"""Read-only audit of the channel's uploads.

Lists every uploaded video with its privacy status, view count and publish date
so we can see, at a glance, whether recent uploads are public and getting views
(or accidentally private/unlisted). Changes NOTHING — safe to run any time.

Run via the "Audit videos" workflow (uses the repo's YouTube secrets).
"""

from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.upload_youtube import _service  # noqa: E402


def main() -> int:
    yt = _service()
    ch = yt.channels().list(part="contentDetails,statistics", mine=True).execute()
    item = ch["items"][0]
    uploads = item["contentDetails"]["relatedPlaylists"]["uploads"]
    stats = item.get("statistics", {})
    print(f"channel: subs={stats.get('subscriberCount','?')} "
          f"total_views={stats.get('viewCount','?')} "
          f"videos={stats.get('videoCount','?')}")

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

    rows = []
    for i in range(0, len(ids), 50):
        batch = ids[i:i + 50]
        info = yt.videos().list(
            part="status,snippet,statistics", id=",".join(batch)).execute()
        for v in info["items"]:
            rows.append((
                v["snippet"].get("publishedAt", "")[:10],
                v["id"],
                v["status"].get("privacyStatus", "?"),
                v.get("statistics", {}).get("viewCount", "0"),
                v["snippet"]["title"][:52],
            ))

    rows.sort(reverse=True)  # newest first
    print(f"\n{'PUBLISHED':<11} {'VIDEO ID':<13} {'PRIVACY':<9} {'VIEWS':>6}  TITLE")
    print("-" * 88)
    by_privacy: Counter = Counter()
    for pub, vid, priv, views, title in rows:
        by_privacy[priv] += 1
        print(f"{pub:<11} {vid:<13} {priv:<9} {views:>6}  {title}")

    print("\nsummary by privacy:", dict(by_privacy))
    print(f"total uploads: {len(rows)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
