"""Word alignment for HypeLab.

Two paths, chosen by what is known:

* **Mode A (script known, Book 1):** :func:`force_align_words` — true local
  forced alignment of the *known* script words to the VO audio with a
  wav2vec2 CTC acoustic model (trellis DP via
  ``torchaudio.functional.forced_align`` + backtrack/merge). No ASR
  transcription is involved; the word sequence comes from the script.
* **Book 2 ingest (no script):** :func:`transcribe` — faster-whisper ASR
  (CPU, int8) producing both the transcript and word timings.

:func:`fetch_model` is the ONLY function in this module allowed to touch the
network (one-time wav2vec2 download). Everything else runs fully local and
fails closed when the model cache is absent.

The ``vo.words.json`` contract is produced by :func:`words_doc`.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

#: Default on-disk cache for the wav2vec2 CTC model used by forced alignment.
DEFAULT_CACHE_DIR = "/home/dino/hypelab/models/wav2vec2-base-960h"

#: HF repo id of the CTC acoustic model (downloaded once by fetch_model).
WAV2VEC2_REPO = "facebook/wav2vec2-base-960h"

#: Audio chunk length (s) bounding CPU memory for long inputs.
CHUNK_S = 30.0
#: Audio margin (s) each chunk extends past its word-assignment window so the
#: trellis has room around words near chunk edges.
CHUNK_OVERLAP_S = 2.0

_WORD_RE = re.compile(r"[A-Za-z0-9']+")


class AlignError(Exception):
    """Raised when alignment cannot proceed safely. Never silent."""


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------

def sha256_file(path: str | Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for blk in iter(lambda: f.read(1 << 20), b""):
            h.update(blk)
    return h.hexdigest()


def _script_tokens(script_path: Path | None) -> list[str]:
    if not script_path or not Path(script_path).exists():
        return []
    return _WORD_RE.findall(Path(script_path).read_text())


def _load_16k_mono(wav_path: str | Path) -> tuple["np.ndarray", float]:
    """Load audio as 16 kHz mono float32 numpy array. Returns (audio, duration_s).

    Uses librosa (torchaudio.load needs torchcodec for mp3, which is absent).
    """
    import numpy as np

    import librosa

    audio, _sr = librosa.load(str(wav_path), sr=16000, mono=True)
    audio = np.asarray(audio, dtype=np.float32)
    return audio, float(audio.shape[0] / 16000)


# --------------------------------------------------------------------------
# 1. ASR transcription (Book 2 ingest — no script exists)
# --------------------------------------------------------------------------

#: Defaults for the kit "asr" block (improved Book 1, section 5).
DEFAULT_ASR_CFG = {
    "model": "medium",
    "device": "cpu",
    "compute_type": "int8",
    "vad_filter": True,
}


def _asr_cfg(cfg) -> dict:
    """Normalize an asr_cfg argument to the full {model, device,
    compute_type, vad_filter} dict.

    A bare string is treated as the model name (backwards compatible with
    the old ``model_size`` positional). Missing keys fall back to
    DEFAULT_ASR_CFG.
    """
    if cfg is None:
        return dict(DEFAULT_ASR_CFG)
    if isinstance(cfg, str):
        out = dict(DEFAULT_ASR_CFG)
        out["model"] = cfg
        return out
    if not isinstance(cfg, dict):
        raise AlignError(f"asr_cfg must be a dict or model-name string, got {type(cfg)}")
    out = dict(DEFAULT_ASR_CFG)
    for k in ("model", "device", "compute_type", "vad_filter"):
        if cfg.get(k) is not None:
            out[k] = cfg[k]
    return out


def transcribe(path: str | Path, asr_cfg=None) -> dict:
    """Transcribe audio with faster-whisper, with word timestamps.

    ``asr_cfg`` comes from ``kit["asr"]``:
    ``{model, device, compute_type, vad_filter}``
    (defaults ``medium``/``cpu``/``int8``/``true``). A bare string is
    accepted as the model name for backwards compatibility.

    Returns {"duration", "language", "words": [{"w","t0","t1","p"}]}.
    Note: faster-whisper manages its own model cache internally; this is the
    ASR path, separate from the wav2vec2 forced-alignment model.
    """
    from faster_whisper import WhisperModel

    cfg = _asr_cfg(asr_cfg)
    mdl = WhisperModel(cfg["model"], device=cfg["device"],
                       compute_type=cfg["compute_type"])
    segments, info = mdl.transcribe(
        str(path), language=None, beam_size=5,
        vad_filter=bool(cfg["vad_filter"]), word_timestamps=True
    )
    words: list[dict] = []
    for seg in segments:
        for w in seg.words or []:
            text = w.word.strip()
            if text:
                words.append(
                    {
                        "w": text,
                        "t0": round(float(w.start), 3),
                        "t1": round(float(w.end), 3),
                        "p": round(float(w.probability), 3),
                    }
                )
    return {
        "duration": float(info.duration),
        "language": info.language,
        "words": words,
    }


# --------------------------------------------------------------------------
# 2. one-time model fetch (ONLY network-touching function in this module)
# --------------------------------------------------------------------------

def fetch_model(cache_dir: str = DEFAULT_CACHE_DIR) -> str:
    """Download facebook/wav2vec2-base-960h ONCE into cache_dir.

    This is the only function in this module permitted to use the network.
    Returns the cache dir path.
    """
    from transformers import Wav2Vec2ForCTC, Wav2Vec2Processor

    dest = Path(cache_dir)
    dest.mkdir(parents=True, exist_ok=True)
    model = Wav2Vec2ForCTC.from_pretrained(WAV2VEC2_REPO)
    processor = Wav2Vec2Processor.from_pretrained(WAV2VEC2_REPO)
    model.save_pretrained(str(dest))
    processor.save_pretrained(str(dest))
    return str(dest)


def _check_cache(cache_dir: str) -> Path:
    cache = Path(cache_dir)
    has_weights = (cache / "pytorch_model.bin").exists() or (
        cache / "model.safetensors"
    ).exists()
    if not (cache / "config.json").exists() or not has_weights:
        raise AlignError("wav2vec2 model not cached; run fetch_model first")
    return cache


# --------------------------------------------------------------------------
# 3. forced alignment of KNOWN script words (Mode A)
# --------------------------------------------------------------------------

def _transcript_ids(words: list[str], vocab: dict[str, int]) -> tuple[list[int], list[int]]:
    """Map words -> CTC target id sequence.

    Upper-cases text; the wav2vec2 vocab uses "|" as the word-delimiter char.
    Returns (ids, word_char_counts). Raises AlignError on empty words or
    characters outside the acoustic model's vocabulary (fail closed — never
    silently mangle the script).
    """
    if not words:
        raise AlignError("force_align_words: words must be a non-empty list")
    sep = vocab.get("|")
    if sep is None:
        raise AlignError("wav2vec2 tokenizer vocab has no '|' word delimiter")
    ids: list[int] = []
    counts: list[int] = []
    for w in words:
        if not w or not w.strip():
            raise AlignError("force_align_words: empty word in input")
        n_chars = 0
        for ch in w.strip().upper():
            c = "|" if ch == " " else ch
            if c not in vocab:
                raise AlignError(
                    f"character {ch!r} in word {w!r} not in wav2vec2 vocabulary"
                )
            ids.append(vocab[c])
            n_chars += 1
        counts.append(n_chars)
        ids.append(sep)
    return ids, counts


def _align_chunk(
    logits, ids: list[int], blank_id: int
) -> list:
    """Run trellis forced alignment on one chunk's logits; return TokenSpans."""
    import torch
    import torchaudio

    log_probs = torch.log_softmax(logits, dim=-1).unsqueeze(0)  # (1, T, C)
    targets = torch.tensor([ids], dtype=torch.int32)
    input_lengths = torch.tensor([log_probs.shape[1]], dtype=torch.int32)
    target_lengths = torch.tensor([len(ids)], dtype=torch.int32)
    paths, scores = torchaudio.functional.forced_align(
        log_probs, targets, input_lengths, target_lengths, blank=blank_id
    )
    return torchaudio.functional.merge_tokens(paths[0], scores[0], blank=blank_id)


def force_align_words(
    wav_path: str | Path,
    words: list[str],
    cache_dir: str = DEFAULT_CACHE_DIR,
    chunk_s: float = CHUNK_S,
    asr_cfg=None,
) -> list[dict]:
    """Forced-align KNOWN script words to audio with a local wav2vec2 CTC model.

    Genuine forced alignment: the word sequence is fixed (from the script),
    and a CTC trellis DP (torchaudio.functional.forced_align) finds the most
    likely frame path through the acoustic model's emissions; TokenSpans are
    backtracked/merged into word spans. No ASR decoding is involved.

    ``asr_cfg`` (from ``kit["asr"]``) is accepted for API symmetry with
    :func:`transcribe`; the forced-alignment path always uses the cached
    wav2vec2 CTC model, so the whisper-oriented keys are currently unused
    (reserved for future align-model selection).

    Returns [{"w": original_word, "t0", "t1", "p"}] with p = mean emission
    probability over the word's frames. Timings are monotonic and clipped to
    [0, duration + 0.5]. Long audio is processed in ~chunk_s windows.
    """
    import math

    import numpy as np
    import torch
    import torchaudio  # noqa: F401  (ensures functional API present)

    _asr_cfg(asr_cfg)  # validate the shape; whisper keys unused on this path
    cache = _check_cache(cache_dir)

    from transformers import Wav2Vec2ForCTC, Wav2Vec2Processor

    processor = Wav2Vec2Processor.from_pretrained(str(cache), local_files_only=True)

    vocab = processor.tokenizer.get_vocab()
    blank_id = vocab.get("<pad>", 0)
    sep_id = vocab["|"]
    ids, char_counts = _transcript_ids(words, vocab)  # fail fast on bad input

    model = Wav2Vec2ForCTC.from_pretrained(str(cache), local_files_only=True)
    model.eval()

    audio, duration = _load_16k_mono(wav_path)
    sr = 16000
    frame_shift = float(np.prod(model.config.conv_stride)) / sr  # 0.02 s

    # --- chunk plan: words assigned to chunks by uniform-rate midpoint estimate
    n_words = len(words)
    n_chunks = max(1, math.ceil(duration / chunk_s))
    chunk_word_lists: list[list[int]] = [[] for _ in range(n_chunks)]
    for i in range(n_words):
        est_mid = (i + 0.5) / n_words * duration
        k = min(int(est_mid // chunk_s), n_chunks - 1)
        chunk_word_lists[k].append(i)

    out: list[dict] = []
    prev_t1 = 0.0
    for k in range(n_chunks):
        idxs = chunk_word_lists[k]
        if not idxs:
            continue
        # audio window with margin so edge words have trellis room
        c0 = max(0.0, k * chunk_s - (CHUNK_OVERLAP_S if k > 0 else 0.0))
        c1 = min(duration, (k + 1) * chunk_s + CHUNK_OVERLAP_S)
        s0, s1 = int(c0 * sr), int(c1 * sr)
        chunk_audio = audio[s0:s1]
        if chunk_audio.shape[0] == 0:
            raise AlignError(f"force_align_words: empty audio chunk {k}")

        chunk_words = [words[i] for i in idxs]
        chunk_ids, chunk_counts = _transcript_ids(chunk_words, vocab)
        with torch.no_grad():
            logits = model(
                torch.from_numpy(chunk_audio).unsqueeze(0)
            ).logits.squeeze(0)
        spans = _align_chunk(logits, chunk_ids, blank_id)

        # group char spans into words on the "|" delimiter
        wi = 0
        cur: list = []
        for sp in spans:
            if sp.token == sep_id:
                if cur:
                    out.append(_word_entry(words[idxs[wi]], cur, c0, frame_shift))
                    wi += 1
                    cur = []
                continue
            cur.append(sp)
        if cur:
            out.append(_word_entry(words[idxs[wi]], cur, c0, frame_shift))
            wi += 1
        if wi != len(idxs):
            raise AlignError(
                f"force_align_words: chunk {k} produced {wi} words, "
                f"expected {len(idxs)}"
            )

    if len(out) != n_words:
        raise AlignError(
            f"force_align_words: produced {len(out)} words, expected {n_words}"
        )

    # --- monotonicity + bounds pass
    fixed: list[dict] = []
    prev_t1 = 0.0
    for e in out:
        t0 = max(0.0, min(e["t0"], duration + 0.5))
        t1 = max(0.0, min(e["t1"], duration + 0.5))
        t0 = max(t0, prev_t1)
        if not t1 > t0:
            t1 = t0 + frame_shift
        fixed.append({"w": e["w"], "t0": round(t0, 3), "t1": round(t1, 3),
                      "p": e["p"]})
        prev_t1 = t1
    return fixed


def _word_entry(word: str, spans: list, chunk_offset: float, frame_shift: float) -> dict:
    import math

    t0 = chunk_offset + spans[0].start * frame_shift
    t1 = chunk_offset + spans[-1].end * frame_shift
    probs = [math.exp(sp.score) for sp in spans]
    p = sum(probs) / len(probs)
    return {"w": word, "t0": t0, "t1": t1, "p": round(min(max(p, 0.0), 1.0), 3)}


# --------------------------------------------------------------------------
# 4. vo.words.json contract
# --------------------------------------------------------------------------

_METHODS = ("forced_align", "faster_whisper")

#: Book 1 improved section 8 timing labels, keyed by words_doc method.
#: faster-whisper word timestamps are the recognizer's own estimate
#: ("asr_approximate"); the wav2vec2 path is true forced alignment
#: ("forced_aligned").
_TIMING_LABELS = {
    "forced_align": "forced_aligned",
    "faster_whisper": "asr_approximate",
}


def words_doc(
    words: list[dict],
    *,
    method: str,
    model: str,
    transcript_source: str,
    audio_sha256: str,
    cache_dir: str | None = None,
) -> dict:
    """Build the vo.words.json contract dict.

    ``timing`` carries the Book 1 section 8 label: ``"asr_approximate"``
    for the faster-whisper path, ``"forced_aligned"`` for the wav2vec2
    forced-alignment path. The ``method``/``model`` fields are unchanged.
    """
    if method not in _METHODS:
        raise AlignError(f"words_doc: unknown method {method!r} (expected one of {_METHODS})")
    confs = [w["p"] for w in words if isinstance(w.get("p"), (int, float))]
    mean_conf = sum(confs) / len(confs) if confs else 0.0
    return {
        "method": method,
        "timing": _TIMING_LABELS[method],
        "model": model,
        "model_cache": cache_dir,
        "transcript_source": transcript_source,
        "audio_sha256": audio_sha256,
        "mean_confidence": round(mean_conf, 4),
        "n_words": len(words),
        "words": words,
    }


def low_confidence_beats(
    words_doc: dict,
    beats: list[dict],
    min_word_prob: float = 0.5,
) -> list[dict]:
    """Flag beats containing a word below ``min_word_prob``.

    Each beat's line word-count is mapped onto the sequential word stream
    (same greedy mapping as :func:`retime_beats`). Returns a list of
    ``{"beat_id", "line", "min_word_p"}`` for beats whose minimum word
    probability is below the threshold. The CLI/work layer routes flagged
    jobs to ``gate_failed`` with the reason (not ``failed``).

    ``min_word_prob`` comes from the kit (default 0.5).
    """
    words = (words_doc or {}).get("words") or []
    flagged: list[dict] = []
    i = 0
    for b in beats:
        n = len(str(b.get("line", "")).split())
        span = words[i : i + n]
        if len(span) < n:
            raise AlignError(
                f"low_confidence_beats: ran out of words at beat {b.get('id')}"
            )
        probs = [w["p"] for w in span if isinstance(w.get("p"), (int, float))]
        mp = min(probs) if probs else 1.0
        if mp < min_word_prob:
            flagged.append({
                "beat_id": b.get("id"),
                "line": b.get("line"),
                "min_word_p": round(mp, 3),
            })
        i += n
    return flagged


# --------------------------------------------------------------------------
# 5. beat retiming (Book 1 §8)
# --------------------------------------------------------------------------

def retime_beats(
    beats: list[dict], words: list[dict], min_gap: float = 0.12
) -> list[dict]:
    """Greedily map each beat's line word-count onto sequential words.

    b["t_in"] = first word's t0, b["t_out"] = last word's t1. Beats are kept
    contiguous (a beat never starts before the previous beat ended). Beats
    shorter than min_gap are extended to min_gap. Raises AlignError when the
    word stream runs out mid-beat ("ran out of words at beat ...").
    """
    if not words:
        raise AlignError("retime_beats: no words to map")
    out: list[dict] = []
    i = 0
    prev_out: float | None = None
    for bi, b in enumerate(beats):
        n = len(str(b.get("line", "")).split())
        if n == 0:
            raise AlignError(f"retime_beats: beat {bi} has an empty line")
        span = words[i : i + n]
        if len(span) < n:
            raise AlignError(
                f"ran out of words at beat {bi} (need {n}, have {len(span)})"
            )
        t_in = float(span[0]["t0"])
        t_out = float(span[-1]["t1"])
        if prev_out is not None and t_in < prev_out:
            t_in = prev_out  # keep beats contiguous
        if t_out - t_in < min_gap:
            t_out = t_in + min_gap
        nb = dict(b)
        nb["t_in"] = round(t_in, 3)
        nb["t_out"] = round(t_out, 3)
        out.append(nb)
        prev_out = t_out
        i += n
    return out


# --------------------------------------------------------------------------
# pipeline entry
# --------------------------------------------------------------------------

def align_words(
    vo_path: Path,
    out_path: Path,
    model: str = "tiny",
    language: str = "en",
    script_path: Path | None = None,
    asr_cfg: dict | None = None,
) -> dict:
    """Word-timestamp the VO and write vo.words.json.

    Script present (Mode A) → true forced alignment of script tokens.
    No script (Book 2) → faster-whisper ASR transcription.

    ``asr_cfg`` (from ``kit["asr"]``) configures the ASR path; when absent
    it is built from ``model`` with the remaining keys at their defaults.
    """
    vo_path, out_path = Path(vo_path), Path(out_path)
    cfg = _asr_cfg(asr_cfg if asr_cfg is not None else model)
    tokens = _script_tokens(script_path)
    if tokens:
        words = force_align_words(vo_path, tokens)
        data = words_doc(
            words,
            method="forced_align",
            model=f"wav2vec2:{WAV2VEC2_REPO}",
            transcript_source=str(script_path),
            audio_sha256=sha256_file(vo_path),
            cache_dir=DEFAULT_CACHE_DIR,
        )
        data["language"] = language
    else:
        t = transcribe(vo_path, cfg)
        data = words_doc(
            t["words"],
            method="faster_whisper",
            model=f"faster-whisper:{cfg['model']}",
            transcript_source="asr",
            audio_sha256=sha256_file(vo_path),
        )
        data["language"] = t["language"]
    data["words_version"] = 1
    data["src_slot"] = "vo"
    _check_words_sane(data["words"])
    out_path.write_text(json.dumps(data, indent=1))
    return data


def _check_words_sane(words: list[dict]) -> None:
    """Fail closed on malformed word lists (was edl.validate_words)."""
    if not words:
        raise AlignError("alignment produced an empty word list")
    prev_t1 = -1.0
    for i, w in enumerate(words):
        if not w.get("w"):
            raise AlignError(f"words[{i}].w: missing")
        t0, t1 = w.get("t0"), w.get("t1")
        if not isinstance(t0, (int, float)) or not isinstance(t1, (int, float)):
            raise AlignError(f"words[{i}]: t0/t1 must be numbers")
        if not t1 > t0:
            raise AlignError(f"words[{i}]: t1 must be > t0")
        if t0 < prev_t1 - 1e-6:
            raise AlignError(f"words[{i}].t0: overlaps previous word")
        prev_t1 = t1


# --------------------------------------------------------------------------
# legacy: ASR-text snapping kept for existing regression tests
# --------------------------------------------------------------------------

def _constrain_to_script(
    asr_words: list[dict], script_tokens: list[str]
) -> tuple[list[dict], dict]:
    """Legacy helper (pre-forced-alignment). Kept for test_regressions.py.

    Snaps ASR word *text* to supplied script tokens, keeping ASR timing.
    New code should use force_align_words instead.
    """
    import difflib

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
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "equal":
            for k in range(i2 - i1):
                w = dict(asr_words[i1 + k])
                w["w"] = script_tokens[j1 + k]
                out.append(w)
        else:
            n_asr, n_script = i2 - i1, j2 - j1
            for k in range(n_asr):
                w = dict(asr_words[i1 + k])
                if tag == "replace" and n_asr == n_script:
                    w["w"] = script_tokens[j1 + k]
                out.append(w)
    info["script_constrained"] = True
    return out, info
