# VieNeu TTS API

Run:

```bash
uv run vieneu-api
```

For preset voices only, `uv sync` is enough. For voice cloning from uploaded
reference audio, install the extra runtime first:

```bash
uv sync --group gpu
```

Default URL: `http://127.0.0.1:1238`

Environment variables:

- `VIENEU_API_HOST`: bind host, default `127.0.0.1`
- `VIENEU_API_PORT`: bind port, default `1238`
- `VIENEU_DEVICE`: optional override. By default the API matches the Gradio
  `Auto` behavior: `mps` on Apple Silicon when available, `cuda` on CUDA
  machines, otherwise `cpu`
- `VIENEU_OUTPUT_DIR`: output parent directory for generated audio files
- `XIAOZHI_WARMUP`: enable/disable Xiaozhi warm-up on startup, default `true`
- `XIAOZHI_WARMUP_TEXT`: warm-up text, default `Xin chào.`
- `XIAOZHI_TTS_VOICE`: default voice for `/xiaozhi/tts` and warm-up

## Endpoints

### `GET /health`

Returns server/model status.

### `GET /voices`

Returns preset voices and supported speaking styles.

Example:

```bash
curl http://127.0.0.1:1238/voices
```

Response shape:

```json
{
  "default_voice": "Phạm Tuyên",
  "voices": [
    {
      "label": "Trúc Ly — Nữ · Bắc · Phong cách tự nhiên",
      "id": "Trúc Ly"
    }
  ],
  "styles": [
    {
      "label": "Tự nhiên",
      "id": "tu_nhien"
    }
  ]
}
```

### `GET /xiaozhi/health`

Returns the same model/device status as `/health`, plus warm-up fields:
`warmup_started`, `warmup_done`, and `warmup_error`.

### `POST /xiaozhi/tts`

Xiaozhi-optimized endpoint. It synthesizes with VieNeu at 48 kHz, then returns
a mono WAV resampled to `16000` or `24000` Hz. Default output is `16000` Hz for
ESP32-friendly playback.

The server starts a short background warm-up automatically when `uv run
vieneu-api` starts, so the first real Xiaozhi request avoids most model/MPS
startup cost.

```bash
curl -X POST http://127.0.0.1:1238/xiaozhi/tts \
  -H 'Content-Type: application/json' \
  -d '{
    "text": "Xin chào, đây là giọng nói dành cho Xiaozhi.",
    "voice": "Phạm Tuyên",
    "sample_rate": 16000,
    "style": "tu_nhien"
  }' \
  --output xiaozhi.wav
```

Request fields:

- `text` required
- `voice` optional; falls back to `XIAOZHI_TTS_VOICE`, then model default
- `sample_rate`: `16000` or `24000`, default `16000`
- `style`: `tu_nhien`, `tin_tuc`, or `doc_truyen`
- `temperature`: default `0.8`
- `max_chars`: default `160`
- `apply_watermark`: default `true`

### `POST /tts`

Returns `audio/wav` directly.

```bash
curl -X POST http://127.0.0.1:1238/tts \
  -H 'Content-Type: application/json' \
  -d '{
    "text": "Xin chào, đây là VieNeu TTS API.",
    "voice": "Trúc Ly",
    "style": "tu_nhien",
    "temperature": 0.8,
    "max_chars": 256
  }' \
  --output output.wav
```

### `POST /tts/file`

Generates a WAV file and returns JSON with `audio_url` and `audio_path`.

```bash
curl -X POST http://127.0.0.1:1238/tts/file \
  -H 'Content-Type: application/json' \
  -d '{
    "text": "Xin chào, đây là VieNeu TTS API.",
    "voice": "Trúc Ly"
}'
```

### `POST /tts/clone`

Clones a voice from an uploaded reference audio file and returns `audio/wav`
directly. This matches the Gradio v3 Voice Cloning flow: upload a short
reference clip and synthesize with that voice. For v3 Turbo, no reference
transcript is needed.

```bash
curl -X POST http://127.0.0.1:1238/tts/clone \
  -F 'ref_audio=@examples/audio_ref/example.wav' \
  -F 'text=[cười] Đây là giọng được clone từ audio mẫu.' \
  -F 'style=tu_nhien' \
  -F 'denoise=true' \
  --output cloned.wav
```

### `POST /tts/clone/file`

Clones a voice from an uploaded reference audio file and returns JSON with
`audio_url`, `audio_path`, and `reference_audio_path`.

```bash
curl -X POST http://127.0.0.1:1238/tts/clone/file \
  -F 'ref_audio=@examples/audio_ref/example.wav' \
  -F 'text=Xin chào, đây là endpoint clone giọng.' \
  -F 'temperature=0.8' \
  -F 'max_chars=256'
```

## Request Parameters

- `text` required
- `voice` optional preset id or display label; omit for default voice
- `style`: `tu_nhien`, `tin_tuc`, or `doc_truyen`
- `temperature`: default `0.8`
- `top_k`: default `25`
- `top_p`: default `0.95`
- `max_new_frames`: default `300`
- `repetition_penalty`: default `1.2`
- `max_chars`: default `256`
- `denoise`: default `true`
- `use_ref_codes`: default `true`
- `apply_watermark`: default `true`

For `/tts/clone` and `/tts/clone/file`, send the same parameters as multipart
form fields. The `voice` field is ignored because `ref_audio` becomes the voice
source.

Clone-specific fields:

- `ref_audio` required upload; use a clean `.wav` around 3-5 seconds when possible
- `denoise`: default `true`; removes background noise and normalizes the reference
- `text`: supports the same inline emotion tags as preset generation

## Voice Names

Use `GET /voices` to list built-in voices. Pass the `id` value as `voice`.

Example voice ids:

- `Phạm Tuyên`
- `Trúc Ly`
- `Thái Sơn`
- `Xuân Vĩnh`
- `Thanh Bình`
- `Minh Đức`
- `Ngọc Linh`
- `Đoan Trang`
- `Mai Anh`
- `Thục Đoan`

## Emotion And Non-Verbal Tags

VieNeu v3 Turbo supports inline emotion/non-verbal cue tags inside `text`.
These are not separate API parameters. Put the tag directly where the sound or
style cue should happen.

Supported experimental tags:

- `[cười]`: laughing / smiling cue
- `[hắng giọng]`: throat-clearing cue
- `[thở dài]`: sigh cue

Example with direct WAV output:

```bash
curl -X POST http://127.0.0.1:1238/tts \
  -H 'Content-Type: application/json' \
  -d '{
    "text": "[cười] Trời ơi, cái giọng nó tự nhiên mà nó mượt mà dã man. Để mình nói tiếp [hắng giọng], mọi người bật loa lên rồi cùng trải nghiệm nhé!",
    "voice": "Phạm Tuyên",
    "style": "tu_nhien",
    "temperature": 0.8,
    "max_chars": 256
  }' \
  --output output.wav
```

Example returning a JSON file URL:

```bash
curl -X POST http://127.0.0.1:1238/tts/file \
  -H 'Content-Type: application/json' \
  -d '{
    "text": "[cười] Xin chào anh. Đây là server TTS VieNeu. [thở dài] Nghe cũng khá tự nhiên đúng không?",
    "voice": "Trúc Ly",
    "style": "tu_nhien"
  }'
```

Notes:

- Tags work only when the model/backend supports them. VieNeu v3 Turbo supports
  these tags experimentally.
- Keep tags in square brackets exactly as shown.
- You can mix tags with normal Vietnamese text in one `text` string.
