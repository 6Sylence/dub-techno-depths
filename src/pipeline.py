"""Daily pipeline: synthesize -> render -> (optionally) upload.

Run locally:
    python -m src.pipeline --no-upload --loop-seconds 20 --target-seconds 40

In CI the GitHub Actions workflow calls it with no flags (full-length upload).
Everything is driven by CLI flags with sensible env-var fallbacks.
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import os
from pathlib import Path

from . import audio, metadata, video
from .utils import daily_seed, load_presets, run, select_preset, write_wav

ROOT = Path(__file__).resolve().parent.parent


def _env(name: str, default=None):
    return os.environ.get(name, default)


def parse_args(argv=None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Render (and optionally upload) a daily ambient video.")
    p.add_argument("--config", default=_env("CONFIG", str(ROOT / "config" / "presets.yaml")))
    p.add_argument("--out-dir", default=_env("OUT_DIR", str(ROOT / "out")))
    p.add_argument("--preset", default=_env("PRESET") or None, help="Force a preset id (default: rotate by date).")
    p.add_argument("--slot", type=int, default=int(_env("SLOT", "0") or "0"),
                   help="Upload slot index; shifts the rotation so multiple daily slots differ.")
    p.add_argument("--date", default=_env("RUN_DATE") or None, help="YYYY-MM-DD (default: today, UTC).")
    p.add_argument("--loop-seconds", type=float, default=float(_env("LOOP_SECONDS", 300)))
    p.add_argument("--target-seconds", type=float, default=float(_env("TARGET_SECONDS", 3600)))
    p.add_argument("--privacy", default=_env("DEFAULT_PRIVACY", "public"),
                   choices=["public", "unlisted", "private"])
    p.add_argument("--publish-at", default=_env("PUBLISH_AT") or None,
                   help="RFC3339 time for scheduled publish (optional).")
    p.add_argument("--no-upload", action="store_true",
                   default=str(_env("NO_UPLOAD", "")).lower() in ("1", "true", "yes"))
    p.add_argument("--vertical", action="store_true",
                   default=str(_env("VERTICAL", "")).lower() in ("1", "true", "yes"),
                   help="Render a 1080x1920 vertical Short (60s loop, no thumbnail).")
    return p.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(argv)
    date = _dt.date.fromisoformat(args.date) if args.date else _dt.datetime.utcnow().date()

    presets = load_presets(args.config)
    preset = select_preset(presets, date, args.preset, offset=args.slot)
    seed = daily_seed(date, f"{preset['id']}#s{args.slot}")
    # Manual dispatches must never clone that day's scheduled upload: salt the
    # seed with the unique run id so ad-hoc runs always produce fresh audio.
    if os.environ.get("GITHUB_EVENT_NAME") == "workflow_dispatch":
        seed = (seed + int(os.environ.get("GITHUB_RUN_ID", "0"))) % (2**31)

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    wav = out_dir / "audio.wav"
    bg = out_dir / "background.png"
    loop_mp4 = out_dir / "loop.mp4"
    final_mp4 = out_dir / "video.mp4"
    thumb = out_dir / "thumbnail.jpg"

    # Vertical Shorts render at 1080x1920; landscape videos at 1920x1080.
    w, h = (1080, 1920) if args.vertical else (video.WIDTH, video.HEIGHT)

    # Musical loops must be whole 8-bar phrases: snap the requested duration to
    # the preset's BPM grid so drums and delay echoes line up at the seam.
    args.loop_seconds = audio.snap_loop_seconds(
        float(preset["audio"].get("bpm", 122)), args.loop_seconds)

    # Human-feel durations: extend the target by a seeded 2-9 minutes so no
    # two uploads share the exact same length (always upward, never shorter).
    if not args.vertical:
        args.target_seconds += 60.0 * (2 + seed % 8)

    mode = "SHORT" if args.vertical else "long"
    print(f"== Bass Boosted Nation daily run | {date} | preset={preset['id']} "
          f"| seed={seed} | {mode} | loop={args.loop_seconds:.2f}s ==")

    # Verify credentials BEFORE the (minutes-long) render so a bad secret fails
    # in seconds instead of after a full encode.
    if not args.no_upload:
        print("[0/6] verifying YouTube credentials…")
        from .upload_youtube import verify_credentials
        verify_credentials()
        print("    credentials OK")

    print("[1/6] synthesizing audio…")
    samples = audio.render_loop(preset["audio"], args.loop_seconds, seed=seed)
    write_wav(samples, wav)

    fx_kind = preset["visual"].get("effect", "bubbles")
    print(f"[2/6] rendering animated layers (background + mist + {fx_kind})…")
    mist = out_dir / "mist.png"
    effect = out_dir / "effect.png"
    video.build_background(preset, bg, width=w, height=h, seed=seed)
    video.build_mist(preset, mist, width=w, height=h, seed=seed)
    video.build_effect_layer(preset, effect, width=w, height=h, seed=seed)

    print("[3/6] encoding seamless animated loop clip…")
    run(video.build_loop_clip_cmd(str(bg), str(mist), str(effect), str(wav),
                                  preset, args.loop_seconds, str(loop_mp4),
                                  width=w, height=h))

    if args.target_seconds > args.loop_seconds:
        print("[4/6] extending to full length…")
        run(video.build_extend_cmd(str(loop_mp4), args.target_seconds, str(final_mp4)))
    else:
        print("[4/6] loop already at target length; no extension needed")
        loop_mp4.replace(final_mp4)

    if args.vertical:
        print("[5/6] building Shorts metadata…")
        meta = metadata.build_shorts_metadata(preset, date, privacy=args.privacy)
        thumb = None  # Shorts don't use custom thumbnails
    else:
        print("[5/6] building metadata + thumbnail…")
        meta = metadata.build_metadata(preset, date, args.target_seconds, privacy=args.privacy)
        video.build_thumbnail(preset, meta["thumbnail_title"], meta["thumbnail_subtitle"], thumb, seed=seed)
    (out_dir / "metadata.json").write_text(json.dumps(meta, indent=2, ensure_ascii=False))
    print(f"    title: {meta['title']}")

    if args.no_upload:
        print("[6/6] --no-upload set; skipping upload. Artifacts in", out_dir)
        return 0

    print("[6/6] uploading to YouTube…")
    from .upload_youtube import upload_video
    video_id = upload_video(final_mp4, meta, thumbnail_path=thumb, publish_at=args.publish_at)
    if not args.vertical and meta.get("playlist"):
        try:
            from .upload_youtube import add_to_playlist
            add_to_playlist(video_id, meta["playlist"])
        except Exception as exc:  # never fail the upload over playlist curation
            print(f"playlist skipped: {exc}")
    (out_dir / "result.json").write_text(json.dumps(
        {"date": date.isoformat(), "preset": preset["id"], "video_id": video_id,
         "url": f"https://youtu.be/{video_id}"}, indent=2))
    print(f"Done → https://youtu.be/{video_id}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
