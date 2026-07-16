#!/usr/bin/env python3
"""One-time helper to obtain a YouTube OAuth refresh token.

Run this ONCE on your own computer (it opens a browser). It prints a refresh
token that you then store as the GitHub secret ``YT_REFRESH_TOKEN`` so the daily
workflow can upload without any interaction.

Usage:
    pip install google-auth-oauthlib
    python scripts/get_refresh_token.py /path/to/client_secret.json

The client_secret.json comes from Google Cloud Console (OAuth client of type
"Desktop app"). See docs/SETUP.md for the full walkthrough.
"""

import json
import sys

SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube",
]


def main() -> int:
    if len(sys.argv) != 2:
        print(__doc__)
        return 1
    client_secret = sys.argv[1]

    try:
        from google_auth_oauthlib.flow import InstalledAppFlow
    except ImportError:
        print("Please run: pip install google-auth-oauthlib")
        return 1

    flow = InstalledAppFlow.from_client_secrets_file(client_secret, SCOPES)
    try:
        creds = flow.run_local_server(port=0, prompt="consent", access_type="offline")
    except Exception:
        # Headless fallback (no local browser available).
        creds = flow.run_console()

    if not creds.refresh_token:
        print("\nNo refresh token returned. Revoke prior access at "
              "https://myaccount.google.com/permissions and retry with a fresh consent.")
        return 1

    with open(client_secret, encoding="utf-8") as fh:
        data = json.load(fh)["installed"]

    print("\n" + "=" * 64)
    print("Store these as GitHub repository secrets (Settings → Secrets → Actions):")
    print("=" * 64)
    print(f"YT_CLIENT_ID      = {data['client_id']}")
    print(f"YT_CLIENT_SECRET  = {data['client_secret']}")
    print(f"YT_REFRESH_TOKEN  = {creds.refresh_token}")
    print("=" * 64)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
