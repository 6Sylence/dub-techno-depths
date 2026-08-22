"""Learn from the channel's own performance.

Every long upload is stamped with two hidden tag markers — the preset id
(``bbnp-<id>``) and the cover-style index (``bbns-<n>``). This module reads the
channel's view counts back from the YouTube API, works out which presets and
which cover styles earn the most views (per-day velocity, so new and old videos
compare fairly), and biases future uploads toward the winners — while keeping an
exploration share so fresh looks and new trends keep getting tried.

Everything is best-effort: any API/parse failure yields empty weights and the
pipeline just uses its normal rotation and a seed-picked style.
"""

from __future__ import annotations

import datetime as _dt
import os
from collections import defaultdict

PRESET_TAG = "bbnp-"        # hidden tag: which preset made the video
STYLE_TAG = "bbns-"         # hidden tag: which cover style was used
EXPLORE = 0.25              # share of runs that try a non-winning style (trends)


def enabled() -> bool:
    return str(os.environ.get("LEARN", "1")).lower() not in ("0", "false", "no")


def _velocity(views, published_iso, today: _dt.date | None = None) -> float | None:
    """Views per day since publish — fair across video ages."""
    try:
        v = int(views)
    except Exception:
        return None
    today = today or _dt.date.today()
    try:
        d = _dt.date.fromisoformat(str(published_iso)[:10])
        age = max(1, (today - d).days)
    except Exception:
        age = 1
    return v / age


def _marker(tags, prefix) -> str | None:
    for t in tags or ():
        if isinstance(t, str) and t.startswith(prefix):
            return t[len(prefix):]
    return None


def fetch_videos() -> list[dict]:
    """[{id,title,tags,views,published}] for the channel, or [] on any failure."""
    try:
        from .upload_youtube import _service
        yt = _service()
        ch = yt.channels().list(part="contentDetails", mine=True).execute()
        uploads = ch["items"][0]["contentDetails"]["relatedPlaylists"]["uploads"]
    except Exception:
        return []
    ids: list[str] = []
    token = None
    try:
        while True:
            resp = yt.playlistItems().list(
                part="contentDetails", playlistId=uploads, maxResults=50,
                pageToken=token).execute()
            ids += [it["contentDetails"]["videoId"] for it in resp["items"]]
            token = resp.get("nextPageToken")
            if not token:
                break
    except Exception:
        pass
    out: list[dict] = []
    for i in range(0, len(ids), 50):
        try:
            info = yt.videos().list(part="snippet,statistics",
                                    id=",".join(ids[i:i + 50])).execute()
        except Exception:
            continue
        for v in info.get("items", []):
            sn = v.get("snippet", {})
            out.append({
                "id": v.get("id"), "title": sn.get("title", ""),
                "tags": sn.get("tags", []) or [],
                "views": v.get("statistics", {}).get("viewCount", "0"),
                "published": sn.get("publishedAt", ""),
            })
    return out


def _weights(scores: dict) -> dict:
    """Relative weights in (0, 1], normalized to the best performer."""
    if not scores:
        return {}
    m = max(scores.values()) or 1.0
    return {k: (val / m) for k, val in scores.items()}


def learn(presets: list[dict], videos=None, today: _dt.date | None = None):
    """Return (preset_weights, style_weights).

    preset_weights: {preset_id: weight in (0,1]} — average view-velocity per
    preset, normalized. style_weights: {"<genre>#<idx>": weight} likewise.
    Both empty when there's no marked data yet.
    """
    if videos is None:
        videos = fetch_videos()
    id2genre = {p["id"]: p.get("genre", "-") for p in presets}
    pv, sv = defaultdict(list), defaultdict(list)
    for v in videos:
        vel = _velocity(v.get("views"), v.get("published"), today)
        if vel is None:
            continue
        pid = _marker(v.get("tags"), PRESET_TAG)
        sid = _marker(v.get("tags"), STYLE_TAG)
        if pid:
            pv[pid].append(vel)
        genre = id2genre.get(pid)
        if genre and sid is not None:
            sv[f"{genre}#{sid}"].append(vel)
    pscore = {k: sum(a) / len(a) for k, a in pv.items() if a}
    sscore = {k: sum(a) / len(a) for k, a in sv.items() if a}
    return _weights(pscore), _weights(sscore)


def weighted_rotation(base: list[str], preset_weights: dict,
                      max_extra: int = 2) -> list[str]:
    """Repeat winning presets in the rotation (up to max_extra extra slots) so
    they publish more often, while every preset still appears at least once (so
    the channel keeps its variety and keeps exploring). Order is preserved."""
    if not base or not preset_weights:
        return base
    present = [preset_weights.get(p, 0.0) for p in base]
    top = max(present) if present else 0.0
    if top <= 0:
        return base
    out: list[str] = []
    for p in base:
        w = preset_weights.get(p, 0.0)
        extra = round(max_extra * (w / top)) if w > 0 else 0
        out += [p] * (1 + extra)
    return out


def best_style(genre: str, style_weights: dict, n_styles: int, seed: int,
               explore: float = EXPLORE) -> int:
    """Pick a cover-style index: mostly the best performer for this genre, but an
    ``explore`` share of the time a seed-picked one (keeps trying new looks and
    trends). Deterministic in ``seed`` (no RNG, so runs stay reproducible)."""
    if n_styles <= 1:
        return 0
    if (seed % 100) < int(explore * 100):
        return seed % n_styles
    best_idx, best_w = None, -1.0
    for i in range(n_styles):
        w = style_weights.get(f"{genre}#{i}")
        if w is not None and w > best_w:
            best_idx, best_w = i, w
    return best_idx if best_idx is not None else (seed % n_styles)
