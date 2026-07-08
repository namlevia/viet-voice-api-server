import os
import sys
import tempfile
import threading
import time
from pathlib import Path
from typing import Optional

import numpy as np
import soundfile as sf
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
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
_device_used: Optional[str] = None
_warmup_started = False
_warmup_done = False
_warmup_error: Optional[str] = None


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


class XiaozhiTTSRequest(BaseModel):
    text: str = Field(..., min_length=1, description="Text to synthesize for Xiaozhi.")
    voice: Optional[str] = Field(None, description="Preset voice id or display label.")
    style: str = "tu_nhien"
    sample_rate: int = Field(16000, description="Output WAV sample rate: 16000 or 24000.")
    temperature: float = Field(0.8, ge=0.0, le=2.0)
    max_chars: int = Field(160, ge=32, le=512)
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
    global _tts, _load_error, _device_used
    if _tts is not None:
        return _tts
    with _tts_lock:
        if _tts is not None:
            return _tts
        try:
            _device_used = _resolve_device()
            _tts = Vieneu(mode="v3turbo", device=_device_used)
            _load_error = None
            return _tts
        except Exception as exc:
            _load_error = str(exc)
            raise HTTPException(status_code=503, detail=f"Failed to load VieNeu model: {exc}") from exc


def _resolve_device() -> str:
    """Match Gradio's Auto behavior: prefer MPS on macOS, CUDA elsewhere, CPU last."""
    override = os.getenv("VIENEU_DEVICE")
    if override:
        return override.strip().lower()
    try:
        import torch
        if sys.platform == "darwin":
            return "mps" if torch.backends.mps.is_available() else "cpu"
        return "cuda" if torch.cuda.is_available() else "cpu"
    except Exception:
        return "cpu"


def _voice_id(tts, voice: Optional[str]) -> Optional[str]:
    if not voice:
        return None
    for label, value in tts.list_preset_voices():
        if voice == value or voice == label:
            return value
    available = [value for _, value in tts.list_preset_voices()]
    raise HTTPException(status_code=400, detail={"message": f"Voice '{voice}' not found.", "voices": available})


def _synthesize(req: TTSRequest, ref_audio: Optional[Path] = None) -> tuple[np.ndarray, int, float, str]:
    tts = _get_tts()
    style = _normalize_style(req.style)
    voice = None if ref_audio else _voice_id(tts, req.voice)

    start = time.time()
    # CPU/ONNX inference is not designed for concurrent mutation of model caches.
    with _infer_lock:
        wav = tts.infer(
            text=req.text.strip(),
            voice=voice,
            ref_audio=str(ref_audio) if ref_audio else None,
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


def _request_from_form(
    text: str,
    style: str,
    temperature: float,
    top_k: int,
    top_p: float,
    max_new_frames: int,
    repetition_penalty: float,
    max_chars: int,
    denoise: bool,
    use_ref_codes: bool,
    apply_watermark: bool,
) -> TTSRequest:
    return TTSRequest(
        text=text,
        style=style,
        temperature=temperature,
        top_k=top_k,
        top_p=top_p,
        max_new_frames=max_new_frames,
        repetition_penalty=repetition_penalty,
        max_chars=max_chars,
        denoise=denoise,
        use_ref_codes=use_ref_codes,
        apply_watermark=apply_watermark,
    )


def _save_upload(upload: UploadFile) -> Path:
    suffix = Path(upload.filename or "reference.wav").suffix or ".wav"
    path = OUTPUT_DIR / f"ref_{int(time.time() * 1000)}_{threading.get_ident()}{suffix}"
    with path.open("wb") as out:
        while True:
            chunk = upload.file.read(1024 * 1024)
            if not chunk:
                break
            out.write(chunk)
    return path


def _write_wav(wav: np.ndarray, sample_rate: int) -> Path:
    path = OUTPUT_DIR / f"tts_{int(time.time() * 1000)}_{threading.get_ident()}.wav"
    sf.write(str(path), wav, sample_rate)
    return path


def _resample_wav(wav: np.ndarray, source_rate: int, target_rate: int) -> np.ndarray:
    if target_rate not in (16000, 24000):
        raise HTTPException(status_code=400, detail="sample_rate must be 16000 or 24000")
    if source_rate == target_rate:
        return np.asarray(wav, dtype=np.float32)
    import soxr
    return np.asarray(soxr.resample(wav, source_rate, target_rate), dtype=np.float32)


def _xiaozhi_to_tts_request(req: XiaozhiTTSRequest) -> TTSRequest:
    return TTSRequest(
        text=req.text,
        voice=req.voice or os.getenv("XIAOZHI_TTS_VOICE") or None,
        style=req.style,
        temperature=req.temperature,
        max_chars=req.max_chars,
        apply_watermark=req.apply_watermark,
    )


def _warmup_once() -> None:
    global _warmup_done, _warmup_error
    try:
        text = os.getenv("XIAOZHI_WARMUP_TEXT", "Xin chào.")
        voice = os.getenv("XIAOZHI_TTS_VOICE") or None
        req = TTSRequest(text=text, voice=voice, max_chars=64, apply_watermark=False)
        _synthesize(req)
        _warmup_done = True
        _warmup_error = None
        print("✅ Xiaozhi TTS warm-up completed.")
    except Exception as exc:
        _warmup_error = str(exc)
        print(f"⚠️ Xiaozhi TTS warm-up failed: {exc}")


@app.on_event("startup")
def start_warmup() -> None:
    global _warmup_started
    if os.getenv("XIAOZHI_WARMUP", "true").lower() in ("0", "false", "no", "off"):
        return
    if _warmup_started:
        return
    _warmup_started = True
    threading.Thread(target=_warmup_once, name="xiaozhi-tts-warmup", daemon=True).start()


@app.get("/health")
def health():
    backend = getattr(_tts, "backend", None) if _tts is not None else None
    engine_device = getattr(getattr(_tts, "engine", None), "device", None) if _tts is not None else None
    return {
        "ok": _load_error is None,
        "model_loaded": _tts is not None,
        "load_error": _load_error,
        "device": _device_used or _resolve_device(),
        "backend": backend,
        "engine_device": str(engine_device) if engine_device is not None else None,
        "warmup_started": _warmup_started,
        "warmup_done": _warmup_done,
        "warmup_error": _warmup_error,
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


@app.get("/xiaozhi/health")
def xiaozhi_health():
    return health()


@app.post("/xiaozhi/tts")
def xiaozhi_tts(req: XiaozhiTTSRequest):
    tts_req = _xiaozhi_to_tts_request(req)
    wav, source_rate, elapsed, style = _synthesize(tts_req)
    out_wav = _resample_wav(wav, source_rate, req.sample_rate)
    path = _write_wav(out_wav, req.sample_rate)
    headers = {
        "X-Sample-Rate": str(req.sample_rate),
        "X-Source-Sample-Rate": str(source_rate),
        "X-Elapsed-Seconds": f"{elapsed:.3f}",
        "X-Style": style,
    }
    return FileResponse(str(path), media_type="audio/wav", filename=path.name, headers=headers)


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


@app.post("/tts/clone")
def tts_clone_audio(
    ref_audio: UploadFile = File(..., description="Reference voice audio, ideally 3-5 seconds."),
    text: str = Form(...),
    style: str = Form("tu_nhien"),
    temperature: float = Form(0.8),
    top_k: int = Form(25),
    top_p: float = Form(0.95),
    max_new_frames: int = Form(300),
    repetition_penalty: float = Form(1.2),
    max_chars: int = Form(256),
    denoise: bool = Form(True),
    use_ref_codes: bool = Form(True),
    apply_watermark: bool = Form(True),
):
    req = _request_from_form(
        text, style, temperature, top_k, top_p, max_new_frames,
        repetition_penalty, max_chars, denoise, use_ref_codes, apply_watermark,
    )
    ref_path = _save_upload(ref_audio)
    try:
        wav, sample_rate, elapsed, style_key = _synthesize(req, ref_audio=ref_path)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Voice cloning failed: {exc}") from exc
    path = _write_wav(wav, sample_rate)
    headers = {
        "X-Sample-Rate": str(sample_rate),
        "X-Elapsed-Seconds": f"{elapsed:.3f}",
        "X-Style": style_key,
    }
    return FileResponse(str(path), media_type="audio/wav", filename=path.name, headers=headers)


@app.post("/tts/clone/file")
def tts_clone_file(
    ref_audio: UploadFile = File(..., description="Reference voice audio, ideally 3-5 seconds."),
    text: str = Form(...),
    style: str = Form("tu_nhien"),
    temperature: float = Form(0.8),
    top_k: int = Form(25),
    top_p: float = Form(0.95),
    max_new_frames: int = Form(300),
    repetition_penalty: float = Form(1.2),
    max_chars: int = Form(256),
    denoise: bool = Form(True),
    use_ref_codes: bool = Form(True),
    apply_watermark: bool = Form(True),
):
    req = _request_from_form(
        text, style, temperature, top_k, top_p, max_new_frames,
        repetition_penalty, max_chars, denoise, use_ref_codes, apply_watermark,
    )
    ref_path = _save_upload(ref_audio)
    try:
        wav, sample_rate, elapsed, style_key = _synthesize(req, ref_audio=ref_path)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Voice cloning failed: {exc}") from exc
    path = _write_wav(wav, sample_rate)
    duration = len(wav) / sample_rate
    return JSONResponse(
        {
            "audio_url": f"/audio/{path.name}",
            "audio_path": str(path),
            "reference_audio_path": str(ref_path),
            "sample_rate": sample_rate,
            "duration_seconds": round(duration, 3),
            "elapsed_seconds": round(elapsed, 3),
            "style": style_key,
        }
    )


def main():
    import uvicorn

    host = os.getenv("VIENEU_API_HOST", "127.0.0.1")
    port = int(os.getenv("VIENEU_API_PORT", "1238"))
    uvicorn.run("apps.tts_api:app", host=host, port=port, reload=False)


if __name__ == "__main__":
    main()
