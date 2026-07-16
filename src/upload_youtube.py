"""Upload a rendered video to YouTube via the Data API v3.

Auth uses an OAuth *refresh token* stored as a secret (never interactive), so it
runs unattended in CI. Obtain the token once with scripts/get_refresh_token.py.

Required environment variables:
  YT_CLIENT_ID, YT_CLIENT_SECRET, YT_REFRESH_TOKEN
"""

from __future__ import annotations

import os
from pathlib import Path

TOKEN_URI = "https://oauth2.googleapis.com/token"
SCOPES = ["https://www.googleapis.com/auth/youtube.upload",
          "https://www.googleapis.com/auth/youtube"]


def _credentials():
    from google.oauth2.credentials import Credentials

    missing = [k for k in ("YT_CLIENT_ID", "YT_CLIENT_SECRET", "YT_REFRESH_TOKEN")
               if not os.environ.get(k)]
    if missing:
        raise SystemExit(
            "Missing YouTube credentials: " + ", ".join(missing)
            + "\nSee docs/SETUP.md to create them."
        )
    return Credentials(
        token=None,
        refresh_token=os.environ["YT_REFRESH_TOKEN"],
        client_id=os.environ["YT_CLIENT_ID"],
        client_secret=os.environ["YT_CLIENT_SECRET"],
        token_uri=TOKEN_URI,
        scopes=SCOPES,
    )


def _safe_diagnostics() -> str:
    """Structural checks on the secrets that never reveal their contents.

    Only lengths and booleans are printed (GitHub masks the exact secret string,
    not these derived values), so this is safe to log and pinpoints paste errors.
    """
    lines = ["Secret sanity check (no values shown):"]
    cid = os.environ.get("YT_CLIENT_ID", "")
    sec = os.environ.get("YT_CLIENT_SECRET", "")
    tok = os.environ.get("YT_REFRESH_TOKEN", "")
    for name, val in (("YT_CLIENT_ID", cid), ("YT_CLIENT_SECRET", sec),
                      ("YT_REFRESH_TOKEN", tok)):
        flags = []
        if val != val.strip():
            flags.append("HAS LEADING/TRAILING WHITESPACE")
        if "\n" in val or "\r" in val:
            flags.append("CONTAINS NEWLINE")
        if " " in val.strip():
            flags.append("CONTAINS INNER SPACE")
        lines.append(f"  {name}: length={len(val)}"
                     + (("  ⚠ " + ", ".join(flags)) if flags else "  ok"))
    lines.append("  YT_CLIENT_ID ends with '.apps.googleusercontent.com': "
                 + str(cid.strip().endswith(".apps.googleusercontent.com")))
    lines.append("  YT_CLIENT_SECRET starts with 'GOCSPX-': "
                 + str(sec.strip().startswith("GOCSPX-")))
    return "\n".join(lines)


def verify_credentials():
    """Fail fast if the OAuth secrets are wrong, BEFORE the long render.

    A single token refresh round-trip surfaces bad/mismatched client id/secret
    or an expired refresh token in seconds, instead of after minutes of encoding.
    """
    from google.auth.transport.requests import Request
    from google.auth.exceptions import RefreshError

    creds = _credentials()
    try:
        creds.refresh(Request())
    except RefreshError as exc:
        raise SystemExit(
            "\nYouTube authentication failed: " + str(exc) + "\n\n"
            + _safe_diagnostics() + "\n\n"
            "Most likely one of the repo secrets is wrong. Check that:\n"
            "  • YT_CLIENT_ID ends with '.apps.googleusercontent.com' and was\n"
            "    pasted whole, with no extra spaces or line breaks.\n"
            "  • YT_CLIENT_SECRET matches that same OAuth client.\n"
            "  • YT_REFRESH_TOKEN was generated from the same client_secret.json.\n"
            "  • The OAuth client still exists in the Google Cloud project.\n"
            "See docs/SETUP.md (Troubleshooting)."
        )
    return creds


def _service():
    from googleapiclient.discovery import build
    return build("youtube", "v3", credentials=_credentials(), cache_discovery=False)


def upload_video(video_path: str | Path, meta: dict,
                 thumbnail_path: str | Path | None = None,
                 publish_at: str | None = None) -> str:
    """Upload ``video_path`` with ``meta``; returns the new video id."""
    from googleapiclient.http import MediaFileUpload

    youtube = _service()
    status = {"privacyStatus": meta.get("privacyStatus", "public"),
              "selfDeclaredMadeForKids": False}
    if publish_at:
        # Scheduled publish requires the video to start private.
        status["privacyStatus"] = "private"
        status["publishAt"] = publish_at

    body = {
        "snippet": {
            "title": meta["title"],
            "description": meta["description"],
            "tags": meta.get("tags", []),
            "categoryId": meta.get("categoryId", "10"),
            # English metadata maximizes reach in the global ambient/sleep niche.
            "defaultLanguage": "en",
            "defaultAudioLanguage": "en",
        },
        "status": status,
    }
    parts = "snippet,status"
    if meta.get("localizations"):
        body["localizations"] = meta["localizations"]
        parts += ",localizations"

    media = MediaFileUpload(str(video_path), chunksize=8 * 1024 * 1024,
                            resumable=True, mimetype="video/mp4")
    request = youtube.videos().insert(part=parts, body=body, media_body=media)

    response = None
    while response is None:
        progress, response = request.next_chunk()
        if progress:
            print(f"  upload {int(progress.progress() * 100)}%", flush=True)
    video_id = response["id"]
    print(f"uploaded video id: {video_id}", flush=True)

    if thumbnail_path and Path(thumbnail_path).exists():
        try:
            youtube.thumbnails().set(
                videoId=video_id,
                media_body=MediaFileUpload(str(thumbnail_path), mimetype="image/jpeg"),
            ).execute()
            print("thumbnail set", flush=True)
        except Exception as exc:  # thumbnails require a verified channel
            print(f"thumbnail skipped: {exc}", flush=True)

    return video_id

def _find_or_create_playlist(youtube, title: str) -> str:
    """Return the id of the channel playlist named ``title``, creating it once."""
    request = youtube.playlists().list(part="snippet", mine=True, maxResults=50)
    while request is not None:
        response = request.execute()
        for item in response.get("items", []):
            if item["snippet"]["title"] == title:
                return item["id"]
        request = youtube.playlists().list_next(request, response)
    created = youtube.playlists().insert(
        part="snippet,status",
        body={"snippet": {"title": title,
                          "description": "New videos are added automatically every day."},
              "status": {"privacyStatus": "public"}},
    ).execute()
    print(f"created playlist: {title}", flush=True)
    return created["id"]


def add_to_playlist(video_id: str, playlist_title: str) -> None:
    """Append ``video_id`` to the genre playlist (playlists chain views, which
    boosts session watch time — the metric the algorithm rewards most)."""
    import time

    youtube = _service()
    playlist_id = _find_or_create_playlist(youtube, playlist_title)
    body = {"snippet": {"playlistId": playlist_id,
                        "resourceId": {"kind": "youtube#video",
                                       "videoId": video_id}}}
    for attempt in (1, 2, 3):
        try:
            youtube.playlistItems().insert(part="snippet", body=body).execute()
            print(f"added to playlist: {playlist_title}", flush=True)
            return
        except Exception as exc:  # transient 409/5xx right after playlist creation
            if attempt == 3:
                raise
            print(f"playlist insert retry {attempt} after error: {exc}", flush=True)
            time.sleep(5 * attempt)
