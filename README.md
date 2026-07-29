# 🔊 Bass Boosted Nation — Canal de EDM bass boosted automatizado

Genera y publica un mix nuevo de **EDM bass boosted / car music** cada día en
YouTube, de forma totalmente automática. (Este repo empezó con otros nombres —
techno, luego lofi — y se reorientó a **bass boosted / car music**, un nicho
global con enorme demanda: coche, gimnasio y fiesta.)

Todo es **100% original y sintetizado desde cero** con numpy: kick enorme, el
característico "donk" del bounce en los contratiempos, supersaw de la caída,
pluck pegadizo, sidechain duro, redobles de caja y risers hacia el drop. Nada
sampleado → seguro frente a copyright y a la política de "contenido inauténtico"
de YouTube.

## El motor (src/audio.py)

- **Bass boosted de verdad:** kick contundente + sub, y el *donk* graves en los
  offbeats — la energía de los grandes mixes de coche, pero original.
- **Estructura EDM:** acordes supersaw detunados en el drop, lead de pluck,
  builds con snare-roll y barridos de riser que entran al drop.
- **Sidechain duro** que bombea toda la mezcla al ritmo del kick.
- **Loop sin costura por diseño:** cada golpe/eco se suma de forma circular
  (`_wrap_add`), los procesos continuos (EQ, reverb, filtro) son circulares y
  cada LFO cumple ciclos enteros → un mix de 1-2 h repite sin ningún clic.
- **Patrones/clave aleatorios por día** (seed determinista) → ningún mix se repite.

## Fondos de vídeo

Escena **synthwave** dibujada por código, o — si hay imágenes en
`assets/car_backgrounds/` — una **foto de coche neón** rotada como base estática
(la marca, la niebla, las estrellas y el pulso al ritmo se componen encima; el
loop sigue sin costura). Carpeta vacía → synthwave. Las imágenes deben ser de
**coches genéricos, sin logos ni marcas reales** para mantener el canal 100%
libre de copyright. Ver `assets/car_backgrounds/README.md`.

## Presets (rotación diaria)

| id             | Título        | Estilo  | BPM |
| -------------- | ------------- | ------- | --- |
| `bounce_night` | Bounce        | bounce  | 126 |
| `car_bounce`   | Car Music     | bounce  | 128 |
| `big_room`     | Big Room      | bigroom | 128 |
| `festival`     | Festival EDM  | bigroom | 130 |
| `electro_house`| Electro House | electro | 128 |
| `bass_drive`   | Night Drive   | bounce  | 126 |

## Automatización

- `daily.yml` — 2 mixes/día (mañana 1 h, tarde 2 h), presets distintos por slot.
- `shorts.yml` — 1 Short vertical/día (dispatch manual; reactivable en cron).
- `generate-backgrounds.yml` — genera fondos de coche con IA (necesita saldo en
  la API) y los commitea a `assets/car_backgrounds/`.
- `ci.yml` — smoke test end-to-end de todos los presets en cada push.
- `branding.yml` / `delete-video.yml` — mantenimiento del canal.

## Puesta en marcha

Los secrets `YT_CLIENT_ID/SECRET/REFRESH_TOKEN` y el proyecto de Google Cloud ya
existentes siguen valiendo. Solo hay que:
1. Tener el canal de YouTube nombrado **"Bass Boosted Nation"** (o el que elijas
   — dilo y actualizo `CHANNEL_NAME` en `src/metadata.py`).
2. Ejecutar el workflow **Channel branding** para aplicar banner/descripción.
3. (Opcional) subir el avatar en Studio.

## Uso local

```bash
pip install -r requirements.txt   # + ffmpeg
python -m src.pipeline --no-upload --loop-seconds 24 --target-seconds 48
python -m tests.test_audio
```
