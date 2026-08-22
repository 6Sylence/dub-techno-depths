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

from . import ai_image, ai_music, ai_voice, audio, metadata, video
from .utils import daily_seed, load_presets, run, select_preset, write_wav

ROOT = Path(__file__).resolve().parent.parent


def _env(name: str, default=None):
    return os.environ.get(name, default)


def _audio_seconds(path) -> float:
    """Duration of an audio/video file via ffprobe (so we can mux with an exact
    -t instead of the flaky `-stream_loop -1 -shortest` combination)."""
    import subprocess
    out = subprocess.run(
        ["ffprobe", "-v", "quiet", "-print_format", "json", "-show_format", str(path)],
        capture_output=True, text=True)
    return float(json.loads(out.stdout)["format"]["duration"])


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
    import yaml
    _cfg = yaml.safe_load(open(args.config, encoding="utf-8"))
    # ROTATION selects a themed rotation list (e.g. "aura" -> rotation_aura) so
    # each daily slot can stick to its own category; falls back to the general one.
    _rot_key = os.environ.get("ROTATION", "").strip()
    rotation = (_cfg.get(f"rotation_{_rot_key}") if _rot_key else None) or _cfg.get("rotation")
    preset = select_preset(presets, date, args.preset, offset=args.slot, rotation=rotation)
    seed = daily_seed(date, f"{preset['id']}#s{args.slot}")
    # Manual dispatches must never clone that day's scheduled upload: salt the
    # seed with the unique run id so ad-hoc runs always produce fresh audio.
    if os.environ.get("GITHUB_EVENT_NAME") == "workflow_dispatch":
        seed = (seed + int(os.environ.get("GITHUB_RUN_ID", "0"))) % (2**31)

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    # Run-status flags surfaced in a final [status] line (visible in the log tail).
    hero = None
    used_voice = False
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

    audio_path = wav
    block_seconds = args.loop_seconds
    music_engine = (_env("MUSIC_ENGINE", "ai") or "ai").lower()
    primary = preset["theme_words"][date.timetuple().tm_yday % len(preset["theme_words"])]

    def _procedural_mix():
        s = audio.render_mix(presets, args.target_seconds, seed=seed)
        write_wav(s, wav)
        print(f"    varied mix block: {s.shape[0] / audio.DEFAULT_SR / 60:.1f} min")
        return s.shape[0] / audio.DEFAULT_SR

    # For a published long video with the AI engine, the procedural engine must
    # NEVER be used as a silent fallback — a monotone old-engine mix going live is
    # exactly the failure we refuse. If the AI music is missing or fails, abort
    # the run so nothing is uploaded (override with ALLOW_PROCEDURAL_FALLBACK=1).
    allow_fallback = str(_env("ALLOW_PROCEDURAL_FALLBACK", "")).lower() in ("1", "true", "yes")
    require_ai = (music_engine == "ai" and not args.vertical
                  and not args.no_upload and not allow_fallback)

    if args.vertical:
        # Shorts are the discovery engine, so give them a real AI drop: generate
        # a short peak-energy track and cut its highest-energy window (the drop).
        # Falls back to the procedural engine only if AI is off / out of credits.
        src = (ai_music.generate_drop(preset, primary, args.loop_seconds, out_dir, seed=seed)
               if music_engine == "ai" and ai_music.available() else None)
        if src:
            start = ai_music.best_window_start(src, args.loop_seconds)
            print(f"[1/6] AI Short: cutting the drop at {start:.0f}s of the track…")
            run(["ffmpeg", "-y", "-v", "error", "-ss", f"{start:.2f}", "-i", str(src),
                 "-t", f"{args.loop_seconds:.2f}", "-ac", "2", "-ar", "44100", str(wav)])
        else:
            print("[1/6] synthesizing Short audio (procedural)…")
            write_wav(audio.render_loop(preset["audio"], args.loop_seconds, seed=seed), wav)
    elif music_engine == "ai" and ai_music.available():
        n_tr = int(_env("AI_TRACKS", "4") or "4")
        ts = float(_env("AI_TRACK_SECONDS", "180") or "180")
        print(f"[1/6] generating AI music (ElevenLabs Music): {n_tr} x {ts:.0f}s…")
        try:
            files = ai_music.generate_tracks(preset, primary, n_tr, ts, out_dir, seed=seed)
            if not files:
                raise RuntimeError("no AI tracks were generated")
            ai_audio = out_dir / "audio.m4a"
            run(video.build_audio_concat_cmd([str(f) for f in files], str(ai_audio)))
            block_seconds = _audio_seconds(ai_audio)
            audio_path = ai_audio
            print(f"    AI audio ready: {block_seconds / 60:.1f} min from {len(files)} track(s)")
        except Exception as exc:
            if require_ai:
                raise SystemExit(
                    f"[1/6] AI music failed ({exc}). Refusing to publish a "
                    f"procedural mix — aborting so nothing is uploaded. "
                    f"(Set ALLOW_PROCEDURAL_FALLBACK=1 to override.)")
            print(f"    AI music failed ({exc}); falling back to the procedural mix")
            audio_path = wav
            block_seconds = _procedural_mix()
    elif require_ai:
        # engine is "ai" but the API key is missing / unavailable
        raise SystemExit(
            "[1/6] MUSIC_ENGINE=ai but ElevenLabs is unavailable "
            "(ELEVENLABS_API_KEY not set or invalid). Refusing to publish a "
            "procedural mix — aborting. (Set ALLOW_PROCEDURAL_FALLBACK=1 to override.)")
    else:
        if music_engine == "ai":
            print("[1/6] ELEVENLABS_API_KEY not set; using the procedural mix")
        else:
            print("[1/6] synthesizing DJ-style mix (multiple tracks)…")
        block_seconds = _procedural_mix()

    # TRAP-MAFIA lane: mix the owner's cloned Spanish voice over the beat as a
    # recurring vocal tag. Best-effort — if the voice is unavailable the
    # instrumental beat is published unchanged (upload never breaks over it).
    if not args.vertical and preset.get("genre") == "trap_mafia":
        try:
            clips = ai_voice.generate_lines(out_dir, seed=seed)
            if clips:
                # Place the arranged lines across the beat block: intro near the
                # top, then the hook and the bar spaced out (fractions of the
                # block length, so it adapts to any block duration).
                block = block_seconds or _audio_seconds(audio_path)
                fracs = [0.02, 0.42, 0.72][:len(clips)]
                specs = [(c, round(f * block, 2)) for c, f in zip(clips, fracs)]
                voiced = out_dir / "audio_voiced.m4a"
                run(video.build_voice_mix_cmd(str(audio_path), specs, str(voiced)))
                audio_path = voiced
                block_seconds = _audio_seconds(voiced)
                used_voice = True
                print(f"    [voice] cloned voice arranged over the beat "
                      f"({len(clips)} line(s))")
        except Exception as exc:
            print(f"    [voice] mix skipped ({exc}); using the instrumental beat")

    fx_kind = preset["visual"].get("effect", "bubbles")
    print(f"[2/6] rendering animated layers (background + mist + {fx_kind})…")
    mist = out_dir / "mist.png"
    effect = out_dir / "effect.png"
    video.build_background(preset, bg, width=w, height=h, seed=seed)
    video.build_mist(preset, mist, width=w, height=h, seed=seed)
    video.build_effect_layer(preset, effect, width=w, height=h, seed=seed)

    if args.vertical:
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
    else:
        # Encode a short SILENT video loop, tile it under the full-length mix,
        # then repeat that block to the target length (all copy, no re-encode).
        # The visual is a slow scroll, so a short 90 s loop at 20 fps looks the
        # same but keeps the (expensive) 4K encode fast on CI's 2-vCPU runners.
        vloop = out_dir / "vloop.mp4"
        block_mp4 = out_dir / "block.mp4"
        vid_secs = 90.0
        print("[3/6] encoding silent video loop + muxing the full mix…")
        run(video.build_loop_clip_cmd(str(bg), str(mist), str(effect), None,
                                      preset, vid_secs, str(vloop),
                                      width=w, height=h, fps=20))
        run(video.build_mux_loop_cmd(str(vloop), str(audio_path), block_seconds, str(block_mp4)))
        if block_seconds is None or args.target_seconds > block_seconds + 1:
            print("[4/6] extending to full length…")
            run(video.build_extend_cmd(str(block_mp4), args.target_seconds, str(final_mp4)))
        else:
            print("[4/6] block already at target length; no extension needed")
            block_mp4.replace(final_mp4)

    if args.vertical:
        print("[5/6] building Shorts metadata…")
        meta = metadata.build_shorts_metadata(preset, date, privacy=args.privacy)
        thumb = None  # Shorts don't use custom thumbnails
    else:
        print("[5/6] building metadata + thumbnail…")
        meta = metadata.build_metadata(preset, date, args.target_seconds, privacy=args.privacy)
        # Cool AI cover per video (Cloudflare Workers AI); falls back to the
        # procedural thumbnail if the CF secrets are missing or the API errors.
        hero = ai_image.generate_thumbnail_hero(preset, primary, out_dir, seed=seed)
        if hero is None and ai_image.available():
            print("    [thumb] CF secrets present but no hero produced")
        elif hero is None:
            print("    [thumb] no CF secrets (CF_ACCOUNT_ID/CF_API_TOKEN) — "
                  "using the procedural thumbnail")
        # Alternate the two thumbnail layouts across uploads so Studio analytics
        # accumulate click-through data for each style (a rolling A/B test).
        variant = (date.toordinal() + args.slot) % 2
        video.build_thumbnail(preset, meta["thumbnail_title"], meta["thumbnail_subtitle"],
                              thumb, seed=seed, variant=variant, hero_path=hero)
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
    cover = "ai" if hero else "procedural"
    voice = "yes" if used_voice else ("n/a" if preset.get("genre") != "trap_mafia" else "no")
    print(f"[status] cover={cover} | voice={voice} | genre={preset.get('genre', '-')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
