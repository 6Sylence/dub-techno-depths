# 🌀 Dub Techno Depths — Canal de techno generativo automatizado

Hermano del canal ambient (`sylence-ambient`), con la misma arquitectura probada
pero un **motor de dub techno procedural**: genera y publica mixes hipnóticos de
dub/deep techno en YouTube **cada día, sin intervención humana**.

Todo es **100% original y sintetizado desde cero** con numpy — kick, sub-bajo con
sidechain, acordes dub a través de un delay ping-pong con feedback, hats, pads y
crujido de vinilo. Nada sampleado → cero riesgo de copyright.

## El motor (src/audio.py)

- **Rejilla musical:** los loops se cuadran a frases de 8 compases al BPM del
  preset, y las colas de delay **dan la vuelta al buffer** (wrap-around), así el
  loop es matemáticamente perfecto y un mix de 1-2 h no tiene ni una costura.
- **Kick** four-to-the-floor (seno con caída de pitch 140→44 Hz + click).
- **Sub-bajo** en corcheas a contratiempo, saturación suave.
- **Acordes dub** (m7/m9/sus, saw band-limited + lowpass) con **delay de corchea
  con puntillo en ping-pong** que se oscurece eco a eco — el sonido Basic Channel.
- **Sidechain pump** en todo menos el kick.
- **Clave y patrones aleatorios por día** (seed determinista) → cada upload es único.

## Presets (rotación diaria)

| id            | Estilo                          | BPM |
| ------------- | ------------------------------- | --- |
| `dub_classic` | Dub techno clásico              | 122 |
| `deep_space`  | Espacial, m9, delays largos     | 118 |
| `minimal_dub` | Minimal, sus, clicky            | 124 |
| `warm_dub`    | Cálido analógico, mucho vinilo  | 116 |
| `abyss`       | Oscuro abisal, casi sin hats    | 120 |
| `drive`       | Nocturno, más rápido y brillante| 126 |

## Automatización

- `daily.yml` — 2 mixes/día en horarios de **música de trabajo**: 06:30 UTC
  (mañana EU, 1 h) y 13:30 UTC (mañana US, 2 h), con presets distintos por slot.
- `shorts.yml` — 1 Short vertical/día a las 17:00 UTC (mediodía US) que
  promociona el mix del día.
- `ci.yml` — smoke test end-to-end de todos los presets en cada push.

## Puesta en marcha

Reutiliza el proyecto de Google Cloud del canal ambient (mismo `client_secret`):

1. Crea el canal de YouTube **"Dub Techno Depths"** (cuenta de marca) y verifícalo.
2. `python scripts/get_refresh_token.py client_secret.json` — inicia sesión y
   **elige el canal nuevo** en el selector de cuenta/canal.
3. Guarda en este repo los secrets `YT_CLIENT_ID`, `YT_CLIENT_SECRET` (los mismos
   del otro canal) y `YT_REFRESH_TOKEN` (el **nuevo**).
4. Actions → *Daily techno upload* → Run workflow.

## Uso local

```bash
pip install -r requirements.txt   # + ffmpeg en el sistema
python -m src.pipeline --no-upload --loop-seconds 32 --target-seconds 64
python -m tests.test_audio
```
