"""
Local multimodal ingest: image OCR (Tesseract) + audio transcription
(faster-whisper). No external API calls — both run inside the container.

System packages required (installed by Dockerfile):
    apt-get install tesseract-ocr ffmpeg

Python packages (pinned in requirements.txt):
    pytesseract, Pillow, faster-whisper

Environment variables:
    SAM_WHISPER_MODEL_SIZE  default "small"   (tiny|base|small|medium|large-v3)
    SAM_WHISPER_DEVICE      default "cpu"
    SAM_WHISPER_COMPUTE     default "int8"
    SAM_WHISPER_MODEL_DIR   optional model cache dir
    SAM_TESSERACT_LANG      default "eng"     ("eng+hin" if Hindi data installed)
"""

from __future__ import annotations

import logging
import os
import threading
from pathlib import Path
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Whisper (lazy singleton)
# ---------------------------------------------------------------------------

_whisper_model = None
_whisper_lock = threading.Lock()


def _get_whisper_model():
    """
    Lazy-load the faster-whisper model the first time it's needed. Loading
    `small` on CPU costs ~1 GB resident memory and 8–15s cold start, so we
    do it once per process and pin it in module state.

    Worker boot can call this directly (via warmup_whisper) to absorb that
    latency before the first user-facing call.
    """
    global _whisper_model
    if _whisper_model is not None:
        return _whisper_model
    with _whisper_lock:
        if _whisper_model is not None:
            return _whisper_model
        from faster_whisper import WhisperModel

        size = os.getenv("SAM_WHISPER_MODEL_SIZE", "small")
        device = os.getenv("SAM_WHISPER_DEVICE", "cpu")
        compute = os.getenv("SAM_WHISPER_COMPUTE", "int8")
        cache_dir = os.getenv("SAM_WHISPER_MODEL_DIR") or None

        logger.info(
            "Loading faster-whisper model size=%s device=%s compute=%s cache=%s",
            size, device, compute, cache_dir or "<default>",
        )
        _whisper_model = WhisperModel(
            size, device=device, compute_type=compute,
            download_root=cache_dir,
        )
        logger.info("faster-whisper ready.")
        return _whisper_model


def warmup_whisper() -> None:
    """Force model load at boot so the first user request is fast."""
    try:
        _get_whisper_model()
    except Exception:
        logger.exception("warmup_whisper failed (will retry on first request)")


def transcribe_audio(path: str | Path) -> Dict[str, Any]:
    """
    Transcribe an audio file to text. Returns:
        {"text": str, "language": str, "duration": float}
    Raises on hard failure so the caller can echo a clear message back.
    """
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"Audio not found: {path}")

    model = _get_whisper_model()

    # vad_filter=True drops silence/non-speech segments — important for
    # WhatsApp voice notes where users record then pause before speaking.
    segments_iter, info = model.transcribe(
        str(p),
        vad_filter=True,
        beam_size=1,           # fastest path; small model is small enough
        language=None,         # auto-detect
    )

    text_parts = []
    for seg in segments_iter:
        if seg.text:
            text_parts.append(seg.text.strip())

    return {
        "text": " ".join(text_parts).strip(),
        "language": getattr(info, "language", None),
        "duration": float(getattr(info, "duration", 0.0)),
    }


# ---------------------------------------------------------------------------
# Tesseract OCR
# ---------------------------------------------------------------------------

def _preprocess_image(path: Path):
    """
    Mild preprocessing for phone-camera timetables: grayscale + adaptive
    threshold via Pillow (no OpenCV dependency). Returns a PIL Image.
    """
    from PIL import Image, ImageOps, ImageFilter

    img = Image.open(path)
    # EXIF rotation (phone photos often land sideways).
    img = ImageOps.exif_transpose(img)
    # Convert to grayscale.
    img = ImageOps.grayscale(img)
    # Mild sharpen helps Tesseract on slightly out-of-focus shots.
    img = img.filter(ImageFilter.SHARPEN)
    # Auto-contrast to handle dim photos.
    img = ImageOps.autocontrast(img, cutoff=2)
    return img


def ocr_image(path: str | Path) -> Dict[str, Any]:
    """
    OCR an image to text. Returns:
        {"text": str, "ocr_confidence": Optional[float]}
    Confidence is averaged across word-level scores when available.
    """
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"Image not found: {path}")

    import pytesseract

    img = _preprocess_image(p)
    lang = os.getenv("SAM_TESSERACT_LANG", "eng")

    text = pytesseract.image_to_string(img, lang=lang) or ""

    confidence: Optional[float] = None
    try:
        data = pytesseract.image_to_data(
            img, lang=lang, output_type=pytesseract.Output.DICT
        )
        confs = []
        for c in data.get("conf", []):
            try:
                v = float(c)
            except (TypeError, ValueError):
                continue
            if v >= 0:
                confs.append(v)
        if confs:
            confidence = round(sum(confs) / len(confs), 1)
    except Exception:
        # Non-fatal — confidence is informational only.
        logger.debug("Tesseract image_to_data failed; skipping confidence")

    return {"text": text.strip(), "ocr_confidence": confidence}
