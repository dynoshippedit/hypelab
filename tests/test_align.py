"""Tests for hypelab.align: forced alignment, ASR fallback, words contract, beats.

Real models, real audio. Requires the wav2vec2 cache (fetch_model) for the
forced-alignment tests; faster-whisper medium for the transcribe smoke test.
"""
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

from hypelab.align import (
    AlignError,
    DEFAULT_CACHE_DIR,
    fetch_model,
    force_align_words,
    retime_beats,
    sha256_file,
    transcribe,
    words_doc,
)

REPO = Path(__file__).resolve().parents[1]
VO = REPO / "jobs/job_c656669a5147/assets/vo.mp3"
SCRIPT = REPO / "fixtures/script.txt"

_WORD_RE = re.compile(r"[A-Za-z0-9']+")


def _cache_ready() -> bool:
    c = Path(DEFAULT_CACHE_DIR)
    return (c / "config.json").exists() and (
        (c / "pytorch_model.bin").exists() or (c / "model.safetensors").exists()
    )


needs_cache = pytest.mark.skipif(not _cache_ready(), reason="wav2vec2 not cached")


def _script_tokens() -> list[str]:
    return _WORD_RE.findall(SCRIPT.read_text())


# ---------------------------------------------------------------- words_doc

def test_words_doc_contract():
    words = [
        {"w": "hello", "t0": 0.0, "t1": 0.4, "p": 0.9},
        {"w": "world", "t0": 0.5, "t1": 0.9, "p": 0.7},
    ]
    doc = words_doc(
        words,
        method="forced_align",
        model="wav2vec2:facebook/wav2vec2-base-960h",
        transcript_source="fixtures/script.txt",
        audio_sha256="abc123",
        cache_dir=DEFAULT_CACHE_DIR,
    )
    assert set(doc) == {
        "method", "timing", "model", "model_cache", "transcript_source",
        "audio_sha256", "mean_confidence", "n_words", "words",
    }
    assert doc["method"] == "forced_align"
    assert doc["timing"] == "forced_aligned"  # Book 1 section 8 label
    assert doc["n_words"] == 2
    assert doc["words"] == words
    assert 0.0 <= doc["mean_confidence"] <= 1.0
    assert doc["mean_confidence"] == pytest.approx(0.8)


def test_words_doc_asr_timing_label():
    doc = words_doc(
        [{"w": "hi", "t0": 0.0, "t1": 0.3, "p": 0.5}],
        method="faster_whisper",
        model="faster-whisper:medium",
        transcript_source="asr",
        audio_sha256="abc123",
    )
    assert doc["timing"] == "asr_approximate"


def test_asr_cfg_defaults_and_overrides():
    from hypelab.align import _asr_cfg

    d = _asr_cfg(None)
    assert d == {"model": "medium", "device": "cpu",
                 "compute_type": "int8", "vad_filter": True}
    assert _asr_cfg("small")["model"] == "small"  # bare-string compat
    assert _asr_cfg("small")["device"] == "cpu"
    k = _asr_cfg({"model": "large-v3", "device": "cuda",
                  "compute_type": "float16", "vad_filter": False})
    assert k == {"model": "large-v3", "device": "cuda",
                 "compute_type": "float16", "vad_filter": False}
    # partial dicts fill the rest from defaults
    assert _asr_cfg({"model": "tiny"})["vad_filter"] is True


def test_low_confidence_beats_flags_low_prob_words():
    from hypelab.align import low_confidence_beats

    doc = {"words": [
        {"w": "hello", "t0": 0.0, "t1": 0.4, "p": 0.95},
        {"w": "world", "t0": 0.4, "t1": 0.9, "p": 0.20},  # low
        {"w": "again", "t0": 0.9, "t1": 1.3, "p": 0.88},
    ]}
    beats = [
        {"id": "b1", "line": "hello world"},
        {"id": "b2", "line": "again"},
    ]
    flagged = low_confidence_beats(doc, beats, min_word_prob=0.5)
    assert flagged == [{"beat_id": "b1", "line": "hello world",
                        "min_word_p": 0.2}]
    assert low_confidence_beats(doc, beats, min_word_prob=0.1) == []


def test_words_doc_rejects_unknown_method():
    with pytest.raises(AlignError):
        words_doc([], method="telepathy", model="x",
                  transcript_source="x", audio_sha256="x")


# ------------------------------------------------------------- retime_beats

def _mk_words(n, start=0.0, step=0.5, dur=0.4):
    return [
        {"w": f"w{i}", "t0": round(start + i * step, 3),
         "t1": round(start + i * step + dur, 3), "p": 0.9}
        for i in range(n)
    ]


def test_retime_beats_contiguous_and_first_starts_at_zero():
    words = _mk_words(10)
    beats = [{"line": "w0 w1 w2"}, {"line": "w3 w4"}, {"line": "w5 w6 w7 w8 w9"}]
    out = retime_beats(beats, words)
    assert out[0]["t_in"] == 0
    assert out[0]["t_out"] == pytest.approx(1.4)
    for a, b in zip(out, out[1:]):
        assert b["t_in"] >= a["t_out"]  # contiguous: never starts before prev end
    assert out[1]["t_in"] == pytest.approx(1.5)
    assert out[2]["t_out"] == pytest.approx(4.9)


def test_retime_beats_clamps_overlap():
    words = _mk_words(6)
    words[3]["t0"] = 0.5  # overlaps beat 0's span -> must be clamped
    out = retime_beats([{"line": "a b c"}, {"line": "d e f"}], words)
    assert out[1]["t_in"] >= out[0]["t_out"]


def test_retime_beats_raises_on_word_exhaustion():
    words = _mk_words(4)
    with pytest.raises(AlignError, match=r"ran out of words at beat 1"):
        retime_beats([{"line": "a b"}, {"line": "c d e"}], words)


def test_retime_beats_rejects_empty_line():
    with pytest.raises(AlignError):
        retime_beats([{"line": "   "}], _mk_words(3))


# -------------------------------------------------------- force_align_words

def test_force_align_fail_closed_without_cache(tmp_path):
    with pytest.raises(AlignError, match="run fetch_model first"):
        force_align_words(VO, ["hello"], cache_dir=str(tmp_path / "nope"))


@needs_cache
def test_force_align_rejects_out_of_vocab_char():
    with pytest.raises(AlignError, match="not in wav2vec2 vocabulary"):
        force_align_words(VO, ["hello", "w0rld3"], cache_dir=DEFAULT_CACHE_DIR)


@needs_cache
def test_force_align_fixture_vo():
    tokens = _script_tokens()
    assert len(tokens) >= 10
    words = force_align_words(VO, tokens, cache_dir=DEFAULT_CACHE_DIR)
    assert len(words) == len(tokens)
    assert [w["w"] for w in words] == tokens  # original words preserved
    import librosa

    duration = librosa.get_duration(path=str(VO))
    prev_t1 = 0.0
    for w in words:
        assert w["t1"] > w["t0"]
        assert w["t0"] >= prev_t1  # monotonic, non-overlapping
        assert 0.0 <= w["t0"] <= duration + 0.5
        assert 0.0 <= w["t1"] <= duration + 0.5
        assert 0.0 <= w["p"] <= 1.0
        prev_t1 = w["t1"]


# --------------------------------------------------------------- transcribe

def test_transcribe_smoke_short_clip(tmp_path):
    import librosa
    import soundfile as sf

    y, _ = librosa.load(str(VO), sr=16000, mono=True, duration=6.0)
    clip = tmp_path / "clip.wav"
    sf.write(str(clip), y, 16000)
    r = transcribe(clip, {"model": "medium"})
    assert r["duration"] > 0
    assert len(r["words"]) > 0
    for w in r["words"]:
        assert set(w) == {"w", "t0", "t1", "p"}
        assert w["t1"] > w["t0"] >= 0


# ---------------------------------------------------------------- fetch_model

def test_fetch_model_cache_present():
    # fetch_model ran before the suite; this asserts it really downloaded.
    c = Path(DEFAULT_CACHE_DIR)
    assert (c / "config.json").exists()
    assert (c / "pytorch_model.bin").exists() or (c / "model.safetensors").exists()
    assert (c / "vocab.json").exists()
    assert callable(fetch_model)


@needs_cache
def test_align_words_pipeline_entry(tmp_path):
    # exercises the align pipeline entry point end-to-end on the fixture
    from hypelab.align import align_words

    out = tmp_path / "vo.words.json"
    data = align_words(VO, out, script_path=SCRIPT)
    assert out.exists()
    assert data["method"] == "forced_align"
    assert data["words_version"] == 1
    assert data["n_words"] == len(_script_tokens())
    assert len(sha256_file(VO)) == 64
