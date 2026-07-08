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

Example:

```bash
curl http://127.0.0.1:8008/voices
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
curl -X POST http://127.0.0.1:8008/tts \
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
curl -X POST http://127.0.0.1:8008/tts/file \
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
