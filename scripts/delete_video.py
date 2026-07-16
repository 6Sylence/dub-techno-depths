#!/usr/bin/env python3
"""Delete one video from the channel. Destructive — dispatch-only, explicit id.

Used via the "Delete video" workflow with the VIDEO_ID env var.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.upload_youtube import _service  # noqa: E402


def main() -> int:
    video_id = os.environ.get("VIDEO_ID", "").strip()
    if not video_id:
        raise SystemExit("VIDEO_ID env var is required")
    _service().videos().delete(id=video_id).execute()
    print(f"deleted video: {video_id}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
