"""Word alignment via local Whisper (CPU). Replaceable: any module that returns
vo.words.json in the contract shape may substitute (WhisperX, API, etc.)."""
from __future__ import annotations
import json
import subprocess
from pathlib import Path

from . import edl as edl_mod
from . import config

def align_words(vo_path: Path, out_path: Path,
                model: str = "tiny", language: str = "en") -> dict:
    """Run whisper with word timestamps. Writes vo.words.json. Returns it."""
    import whisper  # local import: module is only needed for this task
    mdl = whisper.load_model(model)
    result = mdl.transcribe(str(vo_path), word_timestamps=True, language=language,
                            fp16=False)
    words = []
    for seg in result.get("segments", []):
        for w in seg.get("words", []):
            words.append({"w": w["word"].strip(),
                          "t0": round(float(w["start"]), 3),
                          "t1": round(float(w["end"]), 3)})
    data = {"words_version": 1, "src_slot": "vo", "language": language,
            "words": words}
    errors = edl_mod.validate_words(data)
    if errors:
        raise ValueError("alignment produced invalid words.json: " + "; ".join(errors[:5]))
    out_path.write_text(json.dumps(data, indent=1))
    return data
