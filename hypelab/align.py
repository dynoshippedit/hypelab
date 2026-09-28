"""Word alignment via local faster-whisper (CPU, int8). Replaceable: any module
that returns vo.words.json in the contract shape may substitute (WhisperX,
API, TTS-native timings, etc.)."""
from __future__ import annotations
import json
import difflib
import json
import re
from pathlib import Path

from . import edl as edl_mod

_WORD_RE = re.compile(r"[A-Za-z0-9']+")

def _script_tokens(script_path: Path | None) -> list[str]:
    if not script_path or not script_path.exists():
        return []
    return _WORD_RE.findall(script_path.read_text())

def _constrain_to_script(asr_words: list[dict], script_tokens: list[str]) -> tuple[list[dict], dict]:
    """Snap ASR word *text* to the supplied script tokens, keeping ASR timing.

    Uses difflib on lowercased token streams. Only applied when the match
    ratio is >= 0.6; otherwise the ASR words are kept verbatim and the
    fallback is reported. This makes captions script-faithful while the
    timestamps remain ASR-derived (a full script-constrained forced aligner
    can replace this step without changing the words.json contract).
    """
    info = {"script_constrained": False, "match_ratio": 0.0, "fallback": None}
    if not script_tokens or not asr_words:
        info["fallback"] = "no script tokens" if not script_tokens else "no asr words"
        return asr_words, info
    asr_tok = [_WORD_RE.search(w["w"].lower()) for w in asr_words]
    asr_tok = [m.group(0) if m else "" for m in asr_tok]
    script_low = [t.lower() for t in script_tokens]
    sm = difflib.SequenceMatcher(None, asr_tok, script_low, autojunk=False)
    ratio = sm.ratio()
    info["match_ratio"] = round(ratio, 3)
    if ratio < 0.6:
        info["fallback"] = f"match_ratio {ratio:.2f} < 0.6 — kept ASR words"
        return asr_words, info
    out = []
    script_idx = 0
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "equal":
            for k in range(i2 - i1):
                w = dict(asr_words[i1 + k])
                w["w"] = script_tokens[j1 + k]  # script spelling/casing wins
                out.append(w)
        else:
            # insertions/deletions/replacements: keep ASR timing, but for
            # replacements prefer the script token when counts line up.
            n_asr, n_script = i2 - i1, j2 - j1
            for k in range(n_asr):
                w = dict(asr_words[i1 + k])
                if tag == "replace" and n_asr == n_script:
                    w["w"] = script_tokens[j1 + k]
                out.append(w)
        script_idx = j2
    info["script_constrained"] = True
    return out, info

def align_words(vo_path: Path, out_path: Path,
                model: str = "tiny", language: str = "en",
                script_path: Path | None = None) -> dict:
    """Word-timestamp the VO. Timestamps come from faster-whisper (CPU);
    when a script is supplied, word *text* is snapped to the script tokens
    (script-constrained spelling) while timestamps stay ASR-derived.
    Writes vo.words.json. Returns it."""
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
    script_tokens = _script_tokens(script_path)
    words, align_info = _constrain_to_script(words, script_tokens)
    data = {"words_version": 1, "src_slot": "vo", "language": language,
            "alignment": align_info, "words": words}
    errors = edl_mod.validate_words(data)
    if errors:
        raise ValueError("alignment produced invalid words.json: " + "; ".join(errors[:5]))
    out_path.write_text(json.dumps(data, indent=1))
    return data
