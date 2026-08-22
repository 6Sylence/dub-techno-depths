# Aura backgrounds

Drop 16:9 `.jpg`/`.png` images here to use as the static background of the
**aura-phonk** videos (the "aura farming" lane). They are cover-cropped to the
frame and rendered with a dark, cinematic "aura car edit" grade (crushed blacks,
cool teal-blue tint, heavy vignette) so the subject glows out of the shadows.

If this folder is empty, the aura videos automatically reuse the images in
`../car_backgrounds/` with that same dark grade — so you already get the look
without adding anything. Add files here only when you want dedicated,
on-brand-for-aura art (e.g. blacked-out cars with glowing ring headlights).

## The look we're matching
Two styles work great for the aura/car lane:
1. Dark, moody, blacked-out luxury/sports cars on an empty road at dusk, with
   glowing white/neon headlight rings — the classic "aura" car-edit thumbnail.
2. Aggressive muscle cars mid-burnout with THICK coloured tyre smoke and flames
   (the drift/burnout look). Here the smoke is baked into the image itself, which
   is the most realistic "car smoke" — the code also adds drifting coloured smoke
   on top, but a burnout photo sells it best.

## Free ways to generate them (no OpenAI billing needed)
Use **Bing Image Creator** (bing.com/create, free, DALL·E 3) or any free image
generator, download the 16:9 results, and drop them in this folder. Prompts:

Burnout / smoke muscle-car look (matches the reference):
- `Aggressive matte black muscle car (generic, unbranded) doing a burnout, thick
  billowing purple green and yellow tyre smoke, sparks and flames, glowing red
  wheels, dark dramatic cinematic lighting, low angle, ultra detailed, 16:9`
- `Blacked-out muscle car with a big supercharger on the hood mid-burnout, dense
  colourful neon smoke clouds (purple, green, yellow), fire, wet asphalt night
  street, moody phonk aesthetic, 16:9`
- `Drift car sideways with huge coloured smoke plumes (vivid purple, green,
  yellow) pouring off the rear tyres, night, neon rim light, cinematic, 16:9`

Dark "aura" cruise look:
- `Blacked-out matte black sports car facing the camera on an empty desert road
  at dusk, glowing white LED ring headlights, dark moody cinematic teal-blue
  color grade, low angle, atmospheric fog, ultra detailed, 16:9`
- `Black luxury SUV (generic, unbranded) front view on a lonely road at night,
  bright glowing circular headlights, dramatic dark cinematic lighting,
  desaturated cold blue tone, film grain, 16:9`

Keep them unbranded/generic (no real logos or badges) to stay copyright-safe.
File names don't matter; the pipeline rotates through them by upload seed.
