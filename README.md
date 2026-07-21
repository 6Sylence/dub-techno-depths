# 🎧 Lofi Study Lounge — Canal de lofi hip hop automatizado

Genera y publica un mix de **lofi hip hop** nuevo cada día en YouTube, de forma
totalmente automática. (Este repo empezó como un canal de techno y se reorientó
a lofi — un nicho con mucha más demanda de audiencia.)

Todo es **100% original y sintetizado desde cero** con numpy: batería boom-bap
suave, sub-bajo cálido, acordes jazz de piano Rhodes con *warble* de cinta,
hi-hats con swing, lluvia opcional y crujido de vinilo. Nada sampleado → seguro
frente a copyright y a la nueva política de "contenido inauténtico" de YouTube.

## El motor (src/audio.py)

- **Rejilla musical:** los loops se cuadran a frases de 8 compases; la progresión
  de acordes (4 compases, voicings maj7/min9/dom9…) tesela el loop, y las colas
  de reverb/notas **dan la vuelta al buffer**, así un mix de 1-2 h no tiene costura.
- **Batería boom-bap:** bombo suave con caída de pitch, caja en 2 y 4, hi-hats a
  corcheas **con swing** y humanización de velocidad.
- **Rhodes jazzy:** cada nota es un piano eléctrico sintetizado con vibrato de
  cinta coherente (warble), a través de una reverb oscura de ecos envueltos.
- **Textura:** sub-bajo cálido, sidechain suave, filtro "polvoriento" y vinilo.
- **Clave/patrones aleatorios por día** (seed determinista) → ningún mix se repite.

## Presets (rotación diaria)

| id            | Estilo                        | BPM |
| ------------- | ----------------------------- | --- |
| `lofi_study`  | Clásico cálido para estudiar  | 78  |
| `sleepy_lofi` | Lento, nocturno, con lluvia   | 68  |
| `rainy_lofi`  | Día de lluvia, acogedor       | 74  |
| `jazzy_lofi`  | Café, más brillante y movido  | 84  |
| `boombap_lofi`| Boom bap old-school, pegada   | 86  |
| `dreamy_lofi` | Onírico, maj9, mucha reverb   | 70  |

## Automatización

- `daily.yml` — 2 mixes/día (mañana 1 h, tarde 2 h), presets distintos por slot.
- `shorts.yml` — 1 Short vertical/día (dispatch manual; reactivable en cron).
- `ci.yml` — smoke test end-to-end de todos los presets en cada push.
- `branding.yml` / `delete-video.yml` — mantenimiento del canal.

## Puesta en marcha

Reutiliza el mismo canal de YouTube, secrets y proyecto de Google Cloud que ya
tenía el canal de techno. Solo hay que:
1. Renombrar el canal en YouTube Studio a **"Lofi Study Lounge"** (o el nombre que
   elijas — dilo y actualizo `CHANNEL_NAME`), y borrar los mixes de techno viejos.
2. Ejecutar el workflow **Channel branding** para aplicar banner/descripción lofi.
3. (Opcional) subir el avatar nuevo en Studio.

Los secrets `YT_CLIENT_ID/SECRET/REFRESH_TOKEN` ya existentes siguen valiendo.

## Uso local

```bash
pip install -r requirements.txt   # + ffmpeg
python -m src.pipeline --no-upload --loop-seconds 24 --target-seconds 48
python -m tests.test_audio
```
