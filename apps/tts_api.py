import os
import tempfile
import threading
import time
from pathlib import Path
from typing import Optional

import numpy as np
import soundfile as sf
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from vieneu import Vieneu


STYLE_LABEL_TO_KEY = {
    "tu_nhien": "tu_nhien",
    "tự nhiên": "tu_nhien",
    "tu nhien": "tu_nhien",
    "tin_tuc": "tin_tuc",
    "tin tức": "tin_tuc",
    "tin tuc": "tin_tuc",
    "doc_truyen": "doc_truyen",
    "đọc truyện": "doc_truyen",
    "doc truyen": "doc_truyen",
    "kể chuyện": "doc_truyen",
    "ke chuyen": "doc_truyen",
}

OUTPUT_DIR = Path(os.getenv("VIENEU_OUTPUT_DIR", tempfile.gettempdir())) / "vieneu_tts_api"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

app = FastAPI(title="VieNeu TTS API", version="0.1.0")
app.mount("/audio", StaticFiles(directory=str(OUTPUT_DIR)), name="audio")

_tts = None
_tts_lock = threading.Lock()
_infer_lock = threading.Lock()
_load_error: Optional[str] = None


class TTSRequest(BaseModel):
    text: str = Field(..., min_length=1, description="Text to synthesize.")
    voice: Optional[str] = Field(
        None,
        description="Preset voice id or display label. Omit to use the default voice.",
    )
    style: str = Field("tu_nhien", description="tu_nhien, tin_tuc, or doc_truyen.")
    temperature: float = Field(0.8, ge=0.0, le=2.0)
    top_k: int = Field(25, ge=0, le=200)
    top_p: float = Field(0.95, ge=0.0, le=1.0)
    max_new_frames: int = Field(300, ge=1, le=1000)
    repetition_penalty: float = Field(1.2, ge=0.1, le=5.0)
    max_chars: int = Field(256, ge=32, le=2048)
    denoise: bool = True
    use_ref_codes: bool = True
    apply_watermark: bool = True


def _normalize_style(style: str) -> str:
    key = STYLE_LABEL_TO_KEY.get((style or "").strip().lower())
    if key:
        return key
    raise HTTPException(
        status_code=400,
        detail="style must be one of: tu_nhien, tin_tuc, doc_truyen",
    )


def _get_tts():
    global _tts, _load_error
    if _tts is not None:
        return _tts
    with _tts_lock:
        if _tts is not None:
            return _tts
        try:
            _tts = Vieneu(mode="v3turbo", device=os.getenv("VIENEU_DEVICE", "auto"))
            _load_error = None
            return _tts
        except Exception as exc:
            _load_error = str(exc)
            raise HTTPException(status_code=503, detail=f"Failed to load VieNeu model: {exc}") from exc


def _voice_id(tts, voice: Optional[str]) -> Optional[str]:
    if not voice:
        return None
    for label, value in tts.list_preset_voices():
        if voice == value or voice == label:
            return value
    available = [value for _, value in tts.list_preset_voices()]
    raise HTTPException(status_code=400, detail={"message": f"Voice '{voice}' not found.", "voices": available})


def _synthesize(req: TTSRequest) -> tuple[np.ndarray, int, float, str]:
    tts = _get_tts()
    style = _normalize_style(req.style)
    voice = _voice_id(tts, req.voice)

    start = time.time()
    # CPU/ONNX inference is not designed for concurrent mutation of model caches.
    with _infer_lock:
        wav = tts.infer(
            text=req.text.strip(),
            voice=voice,
            style=style,
            denoise=req.denoise,
            use_ref_codes=req.use_ref_codes,
            temperature=req.temperature,
            top_k=req.top_k,
            top_p=req.top_p,
            max_new_frames=req.max_new_frames,
            repetition_penalty=req.repetition_penalty,
            max_chars=req.max_chars,
            apply_watermark=req.apply_watermark,
        )
    elapsed = time.time() - start
    if wav is None or len(wav) == 0:
        raise HTTPException(status_code=500, detail="Model returned empty audio.")
    return np.asarray(wav, dtype=np.float32), int(getattr(tts, "sample_rate", 48000)), elapsed, style


def _write_wav(wav: np.ndarray, sample_rate: int) -> Path:
    path = OUTPUT_DIR / f"tts_{int(time.time() * 1000)}_{threading.get_ident()}.wav"
    sf.write(str(path), wav, sample_rate)
    return path


@app.get("/health")
def health():
    return {
        "ok": _load_error is None,
        "model_loaded": _tts is not None,
        "load_error": _load_error,
        "output_dir": str(OUTPUT_DIR),
    }


@app.get("/voices")
def voices():
    tts = _get_tts()
    return {
        "default_voice": getattr(tts, "_default_voice", None),
        "voices": [{"label": label, "id": value} for label, value in tts.list_preset_voices()],
        "styles": [
            {"label": "Tự nhiên", "id": "tu_nhien"},
            {"label": "Tin tức", "id": "tin_tuc"},
            {"label": "Kể chuyện", "id": "doc_truyen"},
        ],
    }


@app.post("/tts")
def tts_audio(req: TTSRequest):
    wav, sample_rate, elapsed, style = _synthesize(req)
    path = _write_wav(wav, sample_rate)
    headers = {
        "X-Sample-Rate": str(sample_rate),
        "X-Elapsed-Seconds": f"{elapsed:.3f}",
        "X-Style": style,
    }
    return FileResponse(str(path), media_type="audio/wav", filename=path.name, headers=headers)


@app.post("/tts/file")
def tts_file(req: TTSRequest):
    wav, sample_rate, elapsed, style = _synthesize(req)
    path = _write_wav(wav, sample_rate)
    duration = len(wav) / sample_rate
    return JSONResponse(
        {
            "audio_url": f"/audio/{path.name}",
            "audio_path": str(path),
            "sample_rate": sample_rate,
            "duration_seconds": round(duration, 3),
            "elapsed_seconds": round(elapsed, 3),
            "style": style,
        }
    )


def main():
    import uvicorn

    host = os.getenv("VIENEU_API_HOST", "127.0.0.1")
    port = int(os.getenv("VIENEU_API_PORT", "8008"))
    uvicorn.run("apps.tts_api:app", host=host, port=port, reload=False)


if __name__ == "__main__":
    main()
