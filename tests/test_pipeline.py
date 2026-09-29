"""Book-1 content pipeline tests: kits / edl / script / captions / render.

Real ffmpeg/ffprobe runs only in the render + fixture paths; everything
else is pure-function.
"""
from __future__ import annotations

import copy
import json
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from hypelab import captions as cap_mod
from hypelab import edl as edl_mod
from hypelab import kits as kits_mod
from hypelab import manifests as manifests_mod
from hypelab import render as render_mod
from hypelab import script as script_mod
from hypelab.edl import EDLError
from hypelab.render import RenderError


# ------------------------------------------------------------------ helpers

def _target(**kw):
    t = {
        "aspect": "9:16", "w": 360, "h": 640, "fps": 30,
        "max_duration_s": 60.0, "loudness_lufs": -16.0,
    }
    t.update(kw)
    return t


def _beat(i, t_in, t_out, role="body", clip="/tmp/x.mp4"):
    return {
        "id": f"b{i}", "role": role, "t_in": t_in, "t_out": t_out,
        "line": f"line {i}", "clip": clip, "clip_in": 0.0,
        "clip_fit": "cover", "prompt_used": None, "ref_image": None,
    }


def _edl(beats, **kw):
    return edl_mod.build_edl(
        mode="clip", kit_ref="cerebratico@1", target=_target(),
        beats=beats, **kw,
    )


@pytest.fixture(scope="module")
def media(tmp_path_factory):
    """Real tiny fixtures: 2 video clips + vo + music, generated with ffmpeg."""
    d = tmp_path_factory.mktemp("media")

    def run(*args):
        subprocess.run(list(args), check=True, capture_output=True, timeout=120)

    clip0, clip1 = d / "clip0.mp4", d / "clip1.mp4"
    for c in (clip0, clip1):
        run("ffmpeg", "-y", "-v", "error",
            "-f", "lavfi", "-i", "testsrc=size=320x576:rate=30:duration=3",
            "-pix_fmt", "yuv420p", "-c:v", "libx264", "-preset", "veryfast",
            str(c))
    vo, mus = d / "vo.wav", d / "music.wav"
    run("ffmpeg", "-y", "-v", "error",
        "-f", "lavfi", "-i", "sine=frequency=440:duration=5", str(vo))
    run("ffmpeg", "-y", "-v", "error",
        "-f", "lavfi", "-i", "sine=frequency=220:duration=5", str(mus))
    return {"clip0": clip0, "clip1": clip1, "vo": vo, "music": mus}


def _render_edl(media):
    beats = [
        {"id": "b1", "role": "hook", "t_in": 0.0, "t_out": 2.0,
         "line": "hook line", "clip": str(media["clip0"]), "clip_in": 0.0,
         "clip_fit": "cover", "prompt_used": None, "ref_image": None},
        {"id": "b2", "role": "cta", "t_in": 2.0, "t_out": 4.0,
         "line": "cta line", "clip": str(media["clip1"]), "clip_in": 0.0,
         "clip_fit": "cover", "prompt_used": None, "ref_image": None},
    ]
    audio = {"vo": {"path": str(media["vo"])},
             "music": {"path": str(media["music"]), "duck_db": -12.0}}
    captions = {"style": "word_pop", "font": "DejaVu Sans", "size": 48,
                "fill": "#FFFFFF", "highlight": "#39FF88",
                "outline": "#000000", "outline_w": 2,
                "safe_top_pct": 12, "safe_bottom_pct": 20,
                "max_chars_per_card": 24,
                "words": [{"w": "hello", "t0": 0.1, "t1": 0.5},
                          {"w": "world", "t0": 0.6, "t1": 1.0}]}
    return edl_mod.build_edl(mode="clip", kit_ref="cerebratico@1",
                             target=_target(), beats=beats, audio=audio,
                             captions=captions, overlays=[])


# ------------------------------------------------------------------ edl

def test_validate_valid_passes():
    e = _edl([_beat(1, 0.0, 2.0, "hook"), _beat(2, 2.0, 4.0, "cta")])
    assert edl_mod.validate(e) is True


def test_validate_gapped_timeline_fails():
    e = _edl([_beat(1, 0.0, 2.0, "hook"), _beat(2, 2.5, 4.0, "cta")])
    with pytest.raises(EDLError) as ei:
        edl_mod.validate(e)
    assert any("gap" in m for m in ei.value.errors)


def test_validate_overlapping_timeline_fails():
    e = _edl([_beat(1, 0.0, 2.0, "hook"), _beat(2, 1.9, 4.0, "cta")])
    with pytest.raises(EDLError) as ei:
        edl_mod.validate(e)
    assert any("overlap" in m for m in ei.value.errors)


def test_validate_two_hooks_fails():
    e = _edl([_beat(1, 0.0, 2.0, "hook"), _beat(2, 2.0, 4.0, "hook")])
    with pytest.raises(EDLError):
        edl_mod.validate(e)


def test_validate_hook_must_be_first():
    e = _edl([_beat(1, 0.0, 2.0, "body"), _beat(2, 2.0, 4.0, "cta")])
    with pytest.raises(EDLError):
        edl_mod.validate(e)


def test_render_hash_changes_on_caption_edit(tmp_path):
    f = tmp_path / "a.bin"
    f.write_bytes(b"1234")
    prov = {"ffmpeg": "ffmpeg version test", "libass": "unknown",
            "asr": "not-recorded", "hypelab": "0.2.0"}
    e1 = _edl([_beat(1, 0.0, 2.0, "hook"), _beat(2, 2.0, 4.0, "cta")],
              captions={"style": "word_pop", "note": "hello"})
    e2 = copy.deepcopy(e1)
    e2["captions"]["note"] = "hallo"  # one char
    h1 = manifests_mod.render_hash(e1, [f], prov)
    assert h1 == manifests_mod.render_hash(e1, [f], prov)  # deterministic
    assert len(h1) == 32
    assert manifests_mod.render_hash(e2, [f], prov) != h1


# ------------------------------------------------------------------ script

def test_to_beats_roles_and_durations():
    kit = {"generator": {"max_clip_s": 10.0}, "reference_image": "ref.png"}
    beats = script_mod.to_beats(
        "Stop scrolling. This is the second sentence with more words in it. "
        "Buy now.",
        kit, 60.0,
    )
    assert [b["role"] for b in beats] == ["hook", "body", "cta"]
    assert beats[0]["t_in"] == 0.0
    for a, b in zip(beats, beats[1:]):
        assert b["t_in"] == a["t_out"]  # contiguous
    for b in beats:
        assert b["t_out"] > b["t_in"]
        assert b["clip"] is None and b["clip_fit"] == "cover"
        assert b["ref_image"] == "ref.png"
    # 2 words -> clamped to the 1.2s floor; 10 words -> 10/2.6
    assert (beats[0]["t_out"] - beats[0]["t_in"]) == pytest.approx(1.2)
    assert (beats[1]["t_out"] - beats[1]["t_in"]) == pytest.approx(
        round(10 / 2.6, 3))  # boundaries round to ms
    # to_beats output satisfies the EDL validator
    assert edl_mod.validate(_edl(beats)) is True


def test_to_beats_scales_to_target():
    kit = {"generator": {"max_clip_s": 30.0}}
    beats = script_mod.to_beats(
        "One two three four five six. Seven eight nine ten eleven twelve.",
        kit, 4.0,
    )
    assert beats[-1]["t_out"] == pytest.approx(4.0)


# ------------------------------------------------------------------ captions

def test_group_into_cards_pause_rule():
    words = [{"w": "hi", "t0": 0.0, "t1": 0.3},
             {"w": "there", "t0": 0.8, "t1": 1.1}]  # 0.5s gap > 0.45
    cards = cap_mod.group_into_cards(words, 100)
    assert len(cards) == 2
    assert cards[0] == [words[0]] and cards[1] == [words[1]]


def test_group_into_cards_char_budget():
    words = [{"w": "aaa", "t0": 0.0, "t1": 0.2},
             {"w": "bbb", "t0": 0.3, "t1": 0.5}]
    assert len(cap_mod.group_into_cards(words, 5)) == 2
    assert len(cap_mod.group_into_cards(words, 8)) == 1


def test_build_ass_smoke(tmp_path):
    words = [{"w": "hello", "t0": 0.1, "t1": 0.5},
             {"w": "world", "t0": 0.6, "t1": 1.0}]
    caps = {"font": "DejaVu Sans", "size": 48, "fill": "#FFFFFF",
            "highlight": "#39FF88", "outline": "#000000", "outline_w": 2,
            "safe_bottom_pct": 20, "max_chars_per_card": 24}
    out = cap_mod.build_ass(words, caps, {"w": 360, "h": 640},
                            tmp_path / "c.ass")
    txt = out.read_text(encoding="utf-8")
    assert "WordPop" in txt and "\\k" in txt and "hello" in txt


# ------------------------------------------------------------------ kits

def test_kits_seed_load_bump(tmp_path):
    conn = sqlite3.connect(tmp_path / "k.db")
    data = {"appearance": "x",
            "generator": {"max_clip_s": 10.0, "prompt_prefix": "a"},
            "captions": {"size": 72}}
    assert kits_mod.seed(conn, "k1", data) == 1
    got = kits_mod.load(conn, "k1")
    assert got["id"] == "k1" and got["version"] == 1
    assert got["generator"]["prompt_prefix"] == "a"
    with pytest.raises(ValueError):
        kits_mod.seed(conn, "k1", data)
    assert kits_mod.bump(conn, "k1", generator={"max_clip_s": 8.0}) == 2
    got2 = kits_mod.load(conn, "k1")
    assert got2["version"] == 2
    assert got2["generator"]["max_clip_s"] == 8.0
    assert got2["generator"]["prompt_prefix"] == "a"  # deep merge kept it
    old = kits_mod.load(conn, "k1", version=1)
    assert old["generator"]["max_clip_s"] == 10.0  # old row untouched
    with pytest.raises(KeyError):
        kits_mod.load(conn, "nope")


# ------------------------------------------------------------------ render

def test_build_command_sidechain(tmp_path):
    touched = {}
    for name in ("c0.mp4", "c1.mp4", "vo.wav", "music.wav"):
        p = tmp_path / name
        p.touch()
        touched[name] = p
    e = _render_edl(touched_map(touched))
    cmd, rhash = render_mod.build_command(e, tmp_path / "work",
                                          tmp_path / "out.mp4")
    assert cmd[0] == "ffmpeg" and "-filter_complex" in cmd
    fc = cmd[cmd.index("-filter_complex") + 1]
    assert "sidechaincompress" in fc
    assert "asplit" in fc
    assert "loudnorm=I=-16.0:TP=-1.5:LRA=11" in fc
    assert "[vout]" in cmd and "[aout]" in cmd
    assert len(rhash) == 32


def touched_map(touched):
    return {"clip0": touched["c0.mp4"], "clip1": touched["c1.mp4"],
            "vo": touched["vo.wav"], "music": touched["music.wav"]}


def test_render_missing_clip_gate(tmp_path, monkeypatch, media):
    def boom(*a, **k):
        raise AssertionError("ffmpeg must not run before the slots gate")

    monkeypatch.setattr(render_mod.subprocess, "run", boom)
    e = _render_edl(media)
    e["beats"][1]["clip"] = str(tmp_path / "nope.mp4")
    with pytest.raises(RenderError, match="b2"):
        render_mod.render(e, tmp_path / "work", tmp_path / "out.mp4")


def test_render_and_skip(media, tmp_path, monkeypatch):
    conn = sqlite3.connect(tmp_path / "t.db")
    e = _render_edl(media)
    assert edl_mod.validate(e) is True
    work, out = tmp_path / "work", tmp_path / "out.mp4"

    r1 = render_mod.render(e, work, out, conn=conn, job_id="j_test")
    assert r1["skipped"] is False
    assert Path(r1["path"]).is_file()
    assert len(r1["render_hash"]) == 32
    n_edl = conn.execute(
        "SELECT COUNT(*) FROM edls WHERE job_id='j_test'").fetchone()[0]
    n_ren = conn.execute(
        "SELECT COUNT(*) FROM renders WHERE job_id='j_test'").fetchone()[0]
    assert (n_edl, n_ren) == (1, 1)
    mj = conn.execute(
        "SELECT manifest_json FROM renders WHERE job_id='j_test'").fetchone()[0]
    assert mj is not None
    entry = json.loads(mj)
    assert entry["render_hash"] == r1["render_hash"]
    assert set(entry) == {"render_hash", "provenance", "ffmpeg_argv",
                          "started_at", "finished_at", "input_hashes"}
    assert entry["provenance"]["hypelab"] == "0.2.0"

    calls = []
    real_run = render_mod.subprocess.run

    def spy(*a, **k):
        calls.append(a)
        return real_run(*a, **k)

    monkeypatch.setattr(render_mod.subprocess, "run", spy)
    r2 = render_mod.render(e, work, out, conn=conn, job_id="j_test")
    assert r2["skipped"] is True
    assert r2["render_hash"] == r1["render_hash"]
    assert calls == []  # ffmpeg never invoked on the skip path
