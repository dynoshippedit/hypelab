"""Word alignment via local faster-whisper (CPU, int8). Replaceable: any module
that returns vo.words.json in the contract shape may substitute (WhisperX,
API, TTS-native timings, etc.)."""
from __future__ import annotations
import json
from pathlib import Path

from . import edl as edl_mod

def align_words(vo_path: Path, out_path: Path,
                model: str = "tiny", language: str = "en") -> dict:
    """Transcribe with word timestamps. Writes vo.words.json. Returns it."""
    from faster_whisper import WhisperModel  # local import: only needed here
    mdl = WhisperModel(model, device="cpu", compute_type="int8")
    segments, _info = mdl.transcribe(str(vo_path), language=language,
                                     word_timestamps=True)
    words = []
    for seg in segments:
        for w in seg.words or []:
            text = w.word.strip()
            if text:
                words.append({"w": text,
                              "t0": round(float(w.start), 3),
                              "t1": round(float(w.end), 3)})
    data = {"words_version": 1, "src_slot": "vo", "language": language,
            "words": words}
    errors = edl_mod.validate_words(data)
    if errors:
        raise ValueError("alignment produced invalid words.json: " + "; ".join(errors[:5]))
    out_path.write_text(json.dumps(data, indent=1))
    return data
