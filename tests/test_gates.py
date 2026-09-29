"""Quality-gate tests (Book 1 section 11).

All media is generated with real ffmpeg on the Threadripper; no mocks of
media behavior. Covers the frozen-frame root-cause fix:

- old gate used freezedetect (n=0.01:d=1.0), which false-positived on valid
  synthetic movement (fresh testsrc2 MP4 classified "frozen");
- old gate_first_frame() ignored ffmpeg's nonzero return code, so
  truncated/corrupt MP4s passed as (True, "clean"). Unreadable media must
  FAIL the gate, never pass.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from hypelab import gates, db  # noqa: E402

W, H, FPS = 1080, 1920, 30


def _ffmpeg(*args: str) -> None:
    subprocess.run(["ffmpeg", "-y", *args], check=True,
                   capture_output=True, text=True, timeout=300)


# Raw `sine` source measures -21.82 LUFS integrated on this ffmpeg build
# (deterministic), so these gains land the fixtures where the tests need them:
# good ~= -14 LUFS (inside the +/-1.0 budget), loud ~= -8 LUFS (outside it).
_VOLUME_GOOD_DB = 7.82
_VOLUME_LOUD_DB = 13.82


def _av(path: Path, size: str = f"{W}x{H}", volume_db: float = _VOLUME_GOOD_DB,
        duration: float = 5.0, src: str = "testsrc2") -> Path:
    """Synthetic A/V clip: moving test pattern + sine tone at a controlled
    level."""
    _ffmpeg(
        "-f", "lavfi", "-i",
        f"{src}=size={size}:rate={FPS}:duration={duration}",
        "-f", "lavfi", "-i", f"sine=frequency=440:duration={duration}",
        "-map", "0:v", "-map", "1:a",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
        "-pix_fmt", "yuv420p",
        "-af", f"volume={volume_db}dB", "-c:a", "aac",
        "-shortest", str(path))
    return path


def _edl(clip_paths, mode="clip", max_duration_s=8.0, loudness=-14.0,
         hook_dur=1.5, w=W, h=H, fps=FPS) -> dict:
    beats = []
    t = 0.0
    for i, cp in enumerate(clip_paths):
        d = hook_dur if i == 0 else 1.5
        beats.append({"id": f"b{i}", "role": "hook" if i == 0 else "body",
                      "t_in": t, "t_out": t + d,
                      "clip_slot": f"beat:b{i}", "clip_fit": "cover",
                      "clip_path": str(cp), "line": f"line {i}"})
        t += d
    return {"edl_version": 1, "mode": mode, "kit": "k@1",
            "target": {"aspect": "9:16", "w": w, "h": h, "fps": fps,
                       "max_duration_s": max_duration_s,
                       "loudness_lufs": loudness},
            "captions": {"style": "line", "size": 48,
                         "safe_top_pct": 10, "safe_bottom_pct": 10,
                         "max_chars_per_card": 40},
            "beats": beats}


_ASS_HEAD = """[Script Info]
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,Arial,{fontsize},&H00FFFFFF,&H000000FF,&H00000000,&H00000000,0,0,0,0,100,100,0,0,1,2,2,2,10,10,{margin_v},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""


def _write_ass(path: Path, dialogues, fontsize: int = 48,
               margin_v: int = 232) -> Path:
    # margin_v default mirrors the real pipeline (captions.words_to_ass):
    # safe_bottom_pct of height + 40px breathing room = 192 + 40.
    body = "".join(
        f"Dialogue: 0,{s},{e},Default,,0,0,0,,{t}\n"
        for s, e, t in dialogues)
    path.write_text(_ASS_HEAD.format(fontsize=fontsize, margin_v=margin_v)
                    + body)
    return path


@pytest.fixture(scope="module")
def media(tmp_path_factory):
    d = tmp_path_factory.mktemp("media")
    m = {}
    m["good"] = _av(d / "good.mp4")                              # ~-14 LUFS
    m["loud"] = _av(d / "loud.mp4", volume_db=_VOLUME_LOUD_DB)   # ~-8 LUFS
    m["small"] = _av(d / "small.mp4", size="720x1280")

    # opens on 0.5 s of black, then movement
    _ffmpeg("-f", "lavfi", "-i",
            f"color=black:size={W}x{H}:rate={FPS}:duration=0.5",
            "-f", "lavfi", "-i",
            f"testsrc2=size={W}x{H}:rate={FPS}:duration=4.5",
            "-filter_complex", "[0:v][1:v]concat=n=2:v=1:a=0[out]",
            "-map", "[out]", "-c:v", "libx264", "-preset", "veryfast",
            "-pix_fmt", "yuv420p", str(d / "blackopen.mp4"))
    m["blackopen"] = d / "blackopen.mp4"

    # frozen open: frame 0 duplicated for 2 s. Encoded LOSSLESS (crf 0):
    # at normal lossy settings x264's P-skip reconstruction differs from the
    # I-frame by a few hundred bytes, so byte-identical comparison (per the
    # Book 1 spec) needs a lossless fixture to trigger deterministically.
    _ffmpeg("-i", str(m["good"]), "-vf", "select=eq(n\\,0)",
            "-vframes", "1", str(d / "f0.png"))
    _ffmpeg("-loop", "1", "-framerate", str(FPS), "-i", str(d / "f0.png"),
            "-t", "2", "-c:v", "libx264", "-preset", "ultrafast", "-crf", "0",
            "-pix_fmt", "yuv420p", str(d / "frozen.mp4"))
    m["frozen"] = d / "frozen.mp4"

    # truncated / corrupt: first 10% of bytes of a valid mp4
    src = m["good"].read_bytes()
    (d / "trunc.mp4").write_bytes(src[:len(src) // 10])
    m["trunc"] = d / "trunc.mp4"
    return m


@pytest.fixture()
def work(tmp_path):
    w = tmp_path / "work"
    w.mkdir()
    return w


# ------------------------------------------------------- first_frame (the fix)

def test_first_frame_passes_on_moving_synthetic(media, work):
    ok, detail = gates.gate_first_frame(_edl([media["good"]]),
                                        media["good"], work)
    assert ok, detail
    assert detail == "ok: frame 0 is not black and differs from frame 1"


def test_first_frame_fails_on_black_open(media, work):
    ok, detail = gates.gate_first_frame(_edl([media["blackopen"]]),
                                        media["blackopen"], work)
    assert not ok
    assert "black" in detail


def test_first_frame_fails_on_frozen_open(media, work):
    ok, detail = gates.gate_first_frame(_edl([media["frozen"]]),
                                        media["frozen"], work)
    assert not ok
    assert "frozen" in detail


def test_first_frame_fails_closed_on_corrupt_input(media, work):
    """REGRESSION: truncated MP4s (ffprobe/ffmpeg fail) must FAIL the gate,
    never pass as clean."""
    ok, detail = gates.gate_first_frame(_edl([media["trunc"]]),
                                        media["trunc"], work)
    assert not ok
    assert "unreadable" in detail


# ------------------------------------------------------- the other gates

def test_duration_gate_catches_overlong(media, work):
    edl = _edl([media["good"]], max_duration_s=4.0)  # clip is 5 s
    ok, detail = gates.gate_duration(edl, media["good"], work)
    assert not ok
    assert "5.0" in detail and "4.0" in detail


def test_duration_gate_fails_closed_on_corrupt(media, work):
    ok, detail = gates.gate_duration(_edl([media["trunc"]]),
                                     media["trunc"], work)
    assert not ok
    assert "unreadable" in detail


def test_loudness_gate_catches_loud_render(media, work):
    edl = _edl([media["loud"]], loudness=-14.0)  # tone is ~-8 LUFS
    ok, detail = gates.gate_loudness(edl, media["loud"], work)
    assert not ok, detail
    assert "-8" in detail and "-14" in detail


def test_loudness_gate_passes_on_target_level(media, work):
    ok, detail = gates.gate_loudness(_edl([media["good"]]),
                                     media["good"], work)
    assert ok, detail


def test_hook_budget_catches_long_hook(media, work):
    edl = _edl([media["good"]], mode="clip", hook_dur=5.0)
    ok, detail = gates.gate_hook_budget(edl, media["good"], work)
    assert not ok
    assert "5.00" in detail and "2.0" in detail


def test_slots_filled_catches_missing_file(tmp_path, media, work):
    edl = _edl([media["good"], tmp_path / "nope.mp4"])
    ok, detail = gates.gate_slots_filled(edl, media["good"], work)
    assert not ok
    assert "missing clip for beat b1" in detail


def test_check_slots_standalone(tmp_path, media):
    assert gates.check_slots(_edl([media["good"]])) == []
    problems = gates.check_slots(_edl([media["good"], tmp_path / "nope.mp4"]))
    assert len(problems) == 1 and "b1" in problems[0]
    edl = _edl([media["good"]])
    del edl["beats"][0]["clip_slot"]
    problems = gates.check_slots(edl)
    assert len(problems) == 1 and "b0" in problems[0]


def test_geometry_catches_wrong_size(media, work):
    ok, detail = gates.gate_geometry(_edl([media["small"]]),
                                     media["small"], work)
    assert not ok
    assert "720x1280" in detail and "1080x1920" in detail


def test_geometry_passes_on_exact_target(media, work):
    ok, detail = gates.gate_geometry(_edl([media["good"]]),
                                     media["good"], work)
    assert ok, detail


def test_caption_safe_passes_normal_captions(media, work):
    _write_ass(work / "captions.ass",
               [("0:00:00.00", "0:00:02.00", "hello world")])
    ok, detail = gates.gate_caption_safe(_edl([media["good"]]),
                                         media["good"], work)
    assert ok, detail


def test_caption_safe_passes_with_no_ass_file(media, work):
    ok, detail = gates.gate_caption_safe(_edl([media["good"]]),
                                         media["good"], work)
    assert ok
    assert "no captions" in detail


def test_caption_safe_catches_overflow(media, work):
    # Failure mode: caption margins that do NOT respect the safe area --
    # a bottom-anchored event sunk into the bottom danger zone (the real
    # pipeline writes margin_v = safe_bottom + 40, which always passes).
    _write_ass(work / "captions.ass",
               [("0:00:00.00", "0:00:02.00", "HUGE CAPTION")],
               fontsize=200, margin_v=20)
    ok, detail = gates.gate_caption_safe(_edl([media["good"]]),
                                         media["good"], work)
    assert not ok
    assert "safe" in detail and "margin" in detail


# ------------------------------------------------------- run_all

def _mk_job(cx, job_id: str) -> None:
    # gate_results.job_id REFERENCES jobs(id): the parent row must exist.
    cx.execute(
        "INSERT INTO jobs(id, mode, state, kit_id, kit_version, title,"
        " created_at, updated_at) VALUES (?,?,?,?,?,?,?,?)",
        (job_id, "clip", "gating", "k", 1, "t",
         "2026-09-28T00:00:00+00:00", "2026-09-28T00:00:00+00:00"))


def test_run_all_records_gate_results(media, work, tmp_path):
    cx = db.connect(tmp_path / "gates.db")
    db.migrate(cx)
    _mk_job(cx, "job-1")
    _write_ass(work / "captions.ass",
               [("0:00:00.00", "0:00:02.00", "hello world")])
    edl = _edl([media["good"]])
    results = gates.run_all(cx, "job-1", edl, media["good"], work)
    assert [n for n, _, _ in results] == gates.GATES + gates.EXTRA_GATES
    assert all(ok for _, ok, _ in results), \
        [(n, d) for n, ok, d in results if not ok]
    rows = cx.execute(
        "SELECT gate, passed, detail, at FROM gate_results").fetchall()
    assert len(rows) == len(results)
    assert {r["gate"] for r in rows} == set(gates.GATES)
    assert all(r["passed"] == 1 for r in rows)
    assert all(r["at"] for r in rows)


def test_run_all_records_failed_gate(media, work, tmp_path):
    cx = db.connect(tmp_path / "gates.db")
    db.migrate(cx)
    _mk_job(cx, "job-2")
    edl = _edl([media["small"]])  # geometry will fail vs 1080x1920 target
    results = gates.run_all(cx, "job-2", edl, media["small"], work)
    by_name = dict((n, (ok, d)) for n, ok, d in results)
    assert by_name["geometry"][0] is False
    row = cx.execute(
        "SELECT passed, detail FROM gate_results "
        "WHERE job_id='job-2' AND gate='geometry'").fetchone()
    assert row["passed"] == 0
    assert "720x1280" in row["detail"]


# ------------------------------------------------------- word_confidence

def _write_words(work, words):
    (work / "vo.words.json").write_text(json.dumps({"words": words}))


def _wc_edl(**kw):
    edl = _edl([], **kw)
    edl["beats"] = [
        {"id": "b0", "line": "hello world"},
        {"id": "b1", "line": "again"},
    ]
    return edl


def test_gate_word_confidence_flags_low_prob_beat(work):
    _write_words(work, [
        {"w": "hello", "t0": 0.0, "t1": 0.4, "p": 0.95},
        {"w": "world", "t0": 0.4, "t1": 0.9, "p": 0.20},
        {"w": "again", "t0": 0.9, "t1": 1.3, "p": 0.88},
    ])
    ok, detail = gates.gate_word_confidence(_wc_edl(), None, work)
    assert ok is False
    assert "b0" in detail and "min_word_prob=0.5" in detail


def test_gate_word_confidence_passes_clean_words(work):
    _write_words(work, [
        {"w": "hello", "t0": 0.0, "t1": 0.4, "p": 0.95},
        {"w": "world", "t0": 0.4, "t1": 0.9, "p": 0.90},
        {"w": "again", "t0": 0.9, "t1": 1.3, "p": 0.88},
    ])
    ok, detail = gates.gate_word_confidence(_wc_edl(), None, work)
    assert ok is True
    assert "min_word_prob=0.5" in detail


def test_gate_word_confidence_respects_kit_threshold(work):
    words = [
        {"w": "hello", "t0": 0.0, "t1": 0.4, "p": 0.80},
        {"w": "world", "t0": 0.4, "t1": 0.9, "p": 0.85},
        {"w": "again", "t0": 0.9, "t1": 1.3, "p": 0.88},
    ]
    _write_words(work, words)
    ok, _ = gates.gate_word_confidence(_wc_edl(), None, work)
    assert ok is True  # 0.80 >= default 0.5
    edl = _wc_edl()
    edl["min_word_prob"] = 0.9  # kit raised the bar
    ok, detail = gates.gate_word_confidence(edl, None, work)
    assert ok is False
    assert "min_word_prob=0.9" in detail


def test_gate_word_confidence_skips_without_words_doc(work):
    ok, detail = gates.gate_word_confidence(_wc_edl(), None, work)
    assert ok is True
    assert "not judged" in detail


def test_gate_word_confidence_malformed_doc_fails(work):
    (work / "vo.words.json").write_text("{not json")
    ok, detail = gates.gate_word_confidence(_wc_edl(), None, work)
    assert ok is False
    assert "malformed" in detail


def test_run_all_records_word_confidence_failure(work, tmp_path):
    # A flagged job fails the word_confidence GATE (recorded in
    # gate_results with the reason) — the work layer routes this to
    # gate_failed, never to failed.
    cx = db.connect(tmp_path / "gates-wc.db")
    db.migrate(cx)
    _mk_job(cx, "job-wc")
    _write_words(work, [
        {"w": "hello", "t0": 0.0, "t1": 0.4, "p": 0.95},
        {"w": "world", "t0": 0.4, "t1": 0.9, "p": 0.10},
        {"w": "again", "t0": 0.9, "t1": 1.3, "p": 0.88},
    ])
    results = gates.run_all(cx, "job-wc", _wc_edl(), None, work)
    by_name = dict((n, (ok, d)) for n, ok, d in results)
    assert by_name["word_confidence"][0] is False
    assert "b0" in by_name["word_confidence"][1]
    row = cx.execute(
        "SELECT passed, detail FROM gate_results "
        "WHERE job_id='job-wc' AND gate='word_confidence'").fetchone()
    assert row["passed"] == 0
    assert "b0" in row["detail"]


def test_loudness_gate_records_measurement_in_manifest(media, work):
    # Improved §11: the measured value AND the renderer's loudnorm params
    # land in manifest.json — not just the gate_results row.
    ok, detail = gates.gate_loudness(_edl([media["good"]]),
                                     media["good"], work)
    assert ok, detail
    man = json.loads((work / "manifest.json").read_text())
    meas = [m for m in man["measurements"] if m["name"] == "loudness"]
    assert len(meas) == 1
    m = meas[0]
    assert m["passed"] is True
    assert abs(m["integrated_lufs"] - (-14.0)) <= 1.0
    assert m["target_lufs"] == -14.0
    assert m["renderer_params"] == {"I": -14.0, "TP": -1.5, "LRA": 11.0}
    assert m["at"]
