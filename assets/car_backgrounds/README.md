# Car background library

Drop 16:9 background images here (`.jpg` / `.png`) and the daily video pipeline
will rotate through them as the **static base** of each video instead of the
drawn synthwave scene. The channel brand mark, drifting mist, stars and the
beat-pulse still composite on top, and the loop stays seamless (the base is
static — only the overlays move).

Two ways to fill this folder:

1. **Bring your own** — generate images with any AI tool and save them here.
   Use **generic** sports cars only: no real-brand logos, badges, body-kit
   marques or number plates you don't own. That keeps the channel 100%
   copyright/trademark-safe (our whole edge over channels that reuse real
   car photos).

2. **Generate automatically** — add an `OPENAI_API_KEY` repo secret and run the
   **Generate car backgrounds** workflow (`.github/workflows/generate-backgrounds.yml`).
   It calls `scripts/generate_backgrounds.py`, writes the images here and commits
   them. One-time cost, then no per-video API spend.

If this folder has no images, the pipeline falls back to the synthwave scene.
```
```
