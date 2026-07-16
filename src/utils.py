"""Small shared helpers: WAV writing, ffmpeg execution, preset selection."""

from __future__ import annotations

import datetime as _dt
import hashlib
import subprocess
import sys
import wave
from pathlib import Path

import numpy as np
import yaml

from .audio import DEFAULT_SR


def load_presets(config_path: str | Path) -> list[dict]:
    with open(config_path, "r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh)
    return data["presets"]


def select_preset(presets: list[dict], date: _dt.date, override_id: str | None = None,
                  offset: int = 0):
    """Pick a preset. Rotates by ordinal date unless overridden.

    ``offset`` shifts the rotation so different daily upload slots pick different
    presets on the same day (avoids near-duplicate uploads). A stride of 5 keeps
    the two slots well separated across the current library.
    """
    if override_id:
        for p in presets:
            if p["id"] == override_id:
                return p
        raise SystemExit(f"Unknown preset id: {override_id!r}")
    return presets[(date.toordinal() + offset * 5) % len(presets)]


def write_wav(samples_i16: np.ndarray, path: str | Path, sr: int = DEFAULT_SR) -> Path:
    """Write an int16 (N, 2) array to a stereo WAV file."""
    if samples_i16.ndim != 2 or samples_i16.shape[1] != 2:
        raise ValueError("expected stereo (N, 2) int16 array")
    out = Path(path)
    with wave.open(str(out), "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(samples_i16.astype("<i2").tobytes())
    return out


def run(cmd: list[str]) -> None:
    """Run a subprocess, streaming output; raise on failure."""
    print("+ " + " ".join(cmd), flush=True)
    proc = subprocess.run(cmd)
    if proc.returncode != 0:
        print(f"command failed ({proc.returncode})", file=sys.stderr)
        raise SystemExit(proc.returncode)


def daily_seed(date: _dt.date, preset_id: str) -> int:
    """A stable but per-day/per-preset seed so each upload is unique.

    Uses a content hash (not builtin ``hash()``, which is salted per process)
    so the same day + preset always reproduces the same soundscape.
    """
    digest = hashlib.md5(f"{date.isoformat()}:{preset_id}".encode()).hexdigest()
    return int(digest[:8], 16)
