# VieNeu TTS API

Run:

```bash
uv run vieneu-api
```

Default URL: `http://127.0.0.1:8008`

Environment variables:

- `VIENEU_API_HOST`: bind host, default `127.0.0.1`
- `VIENEU_API_PORT`: bind port, default `8008`
- `VIENEU_DEVICE`: model device, default `auto`
- `VIENEU_OUTPUT_DIR`: output parent directory for generated audio files

## Endpoints

### `GET /health`

Returns server/model status.

### `GET /voices`

Returns preset voices and supported speaking styles.

### `POST /tts`

Returns `audio/wav` directly.

```bash
curl -X POST http://127.0.0.1:8008/tts \
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
curl -X POST http://127.0.0.1:8008/tts/file \
  -H 'Content-Type: application/json' \
  -d '{
    "text": "Xin chào, đây là VieNeu TTS API.",
    "voice": "Trúc Ly"
  }'
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
