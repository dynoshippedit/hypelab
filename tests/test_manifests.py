"""Tests for hypelab.manifests: content-hash identity, attach/verify,
quarantine, and render_hash sensitivity.

Media fixtures are generated with real ffmpeg/ffprobe on the Threadripper;
no media behavior is mocked.
"""
from __future__ import annotations

import copy
import json
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from hypelab import manifests as man_mod  # noqa: E402
from hypelab.manifests import (  # noqa: E402
    ManifestError,
    attach_asset,
    provenance,
    record_measurement,
    record_render,
    render_hash,
    sha256_file,
    verify_manifest,
)


@pytest.fixture(scope="module")
def clip(tmp_path_factory):
    d = tmp_path_factory.mktemp("man_media")
    p = d / "clip.mp4"
    subprocess.run(
        ["ffmpeg", "-y", "-v", "error",
         "-f", "lavfi", "-i", "testsrc=duration=1:size=64x64:rate=30",
         "-f", "lavfi", "-i", "sine=frequency=440:duration=1",
         "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac",
         "-shortest", str(p)],
        check=True, timeout=120,
    )
    return p


def _work(tmp_path, name="j_man1"):
    return tmp_path / "work" / name


# ------------------------------------------------------------------ attach

def test_attach_round_trip(clip, tmp_path):
    work = _work(tmp_path)
    entry = attach_asset(clip, work, "clip.mp4")
    assert entry["name"] == "clip.mp4"
    assert entry["sha256"] == sha256_file(clip)
    assert entry["bytes"] == clip.stat().st_size
    assert entry["w"] == 64 and entry["h"] == 64
    assert entry["fps"] == pytest.approx(30.0, rel=0.02)
    assert entry["codec"] == "h264"
    assert (work / "assets" / "clip.mp4").is_file()
    # manifest.json entry carries the mandated fields
    man = json.loads((work / "manifest.json").read_text())
    assert set(man["assets"]["clip.mp4"]) == {
        "name", "sha256", "bytes", "duration_s", "w", "h", "fps",
        "sar", "codec",
    }
    assert man["assets"]["clip.mp4"]["sha256"] == entry["sha256"]
    # verify passes on the untouched asset
    assert verify_manifest(work)["assets"]["clip.mp4"]["sha256"] == entry["sha256"]
    # no temp litter
    assert list((work / "assets").glob(".tmp.*")) == []


def test_attach_with_matching_expected_sha256(clip, tmp_path):
    work = _work(tmp_path)
    entry = attach_asset(clip, work, "clip.mp4",
                         expected_sha256=sha256_file(clip))
    assert entry["sha256"] == sha256_file(clip)


def test_out_of_band_mismatch_quarantines_and_fails_closed(clip, tmp_path):
    work = _work(tmp_path)
    with pytest.raises(ManifestError, match="quarantined"):
        attach_asset(clip, work, "clip.mp4",
                     expected_sha256="0" * 64)
    assert not (work / "assets" / "clip.mp4").exists()
    qfiles = list((work / "quarantine").glob("clip.mp4*"))
    assert len(qfiles) == 1  # the bytes are preserved for forensics
    man = json.loads((work / "manifest.json").read_text())
    assert "clip.mp4" not in man["assets"]
    assert man["quarantined"][0]["expected_sha256"] == "0" * 64
    assert man["quarantined"][0]["actual_sha256"] == sha256_file(clip)


def test_verify_manifest_quarantines_tampered_asset_and_fails_closed(
        clip, tmp_path):
    work = _work(tmp_path)
    attach_asset(clip, work, "clip.mp4")
    p = work / "assets" / "clip.mp4"
    original = sha256_file(p)
    data = bytearray(p.read_bytes())
    data[len(data) // 2] ^= 0xFF  # flip one byte out-of-band
    p.write_bytes(bytes(data))
    tampered = sha256_file(p)
    assert tampered != original
    with pytest.raises(ManifestError, match="quarantined"):
        verify_manifest(work)
    # fail closed: the tampered bytes are quarantined, never left in assets
    assert not p.exists()
    qfiles = list((work / "quarantine").glob("clip.mp4*"))
    assert len(qfiles) == 1
    assert sha256_file(qfiles[0]) == tampered
    man = json.loads((work / "manifest.json").read_text())
    assert "clip.mp4" not in man["assets"]
    assert man["quarantined"][-1]["expected_sha256"] == original
    assert man["quarantined"][-1]["actual_sha256"] == tampered


def test_verify_manifest_raises_on_missing_asset(clip, tmp_path):
    work = _work(tmp_path)
    attach_asset(clip, work, "clip.mp4")
    (work / "assets" / "clip.mp4").unlink()
    with pytest.raises(ManifestError, match="missing on disk"):
        verify_manifest(work)


def test_verify_manifest_absent_is_nothing_to_verify(tmp_path):
    assert verify_manifest(_work(tmp_path)) is None


# ---------------------------------------------------------------- render_hash

def _edl(**kw):
    e = {
        "mode": "clip", "kit": "cerebratico@1",
        "target": {"aspect": "9:16", "w": 360, "h": 640, "fps": 30},
        "beats": [{"id": "b1", "line": "hello world"}],
        "captions": {"style": "word_pop"},
    }
    e.update(kw)
    return e


def _prov(**kw):
    p = {"ffmpeg": "ffmpeg version test", "libass": "unknown",
         "asr": {"model": "medium"}, "hypelab": "0.2.0"}
    p.update(kw)
    return p


def test_render_hash_shape_and_determinism(clip):
    h1 = render_hash(_edl(), [clip], _prov())
    assert len(h1) == 32 and all(c in "0123456789abcdef" for c in h1)
    assert render_hash(_edl(), [clip], _prov()) == h1


def test_render_hash_changes_on_caption_char_change(clip):
    e1 = _edl()
    e2 = copy.deepcopy(e1)
    e2["captions"]["style"] = "word_poq"  # one char
    assert render_hash(e2, [clip], _prov()) != render_hash(e1, [clip], _prov())


def test_render_hash_changes_on_provenance_change(clip):
    p1, p2 = _prov(), _prov(hypelab="0.3.0")
    assert render_hash(_edl(), [clip], p2) != render_hash(_edl(), [clip], p1)


def test_render_hash_changes_on_input_byte_change(clip, tmp_path):
    other = tmp_path / "other.mp4"
    other.write_bytes(clip.read_bytes() + b"\x00")
    assert render_hash(_edl(), [other], _prov()) != \
        render_hash(_edl(), [clip], _prov())


def test_render_hash_input_order_independent(clip, tmp_path):
    c2 = tmp_path / "c2.mp4"
    c2.write_bytes(b"second-input-bytes")
    a = render_hash(_edl(), [clip, c2], _prov())
    b = render_hash(_edl(), [c2, clip], _prov())
    assert a == b


# ---------------------------------------------------------------- provenance

def test_provenance_shape():
    kit = {"asr": {"model": "medium", "device": "cpu",
                   "compute_type": "int8", "vad_filter": True}}
    p = provenance(kit)
    assert set(p) == {"ffmpeg", "libass", "asr", "hypelab"}
    assert p["asr"] == kit["asr"]
    assert p["hypelab"] == "0.2.0"
    assert p["ffmpeg"].startswith("ffmpeg version")
    assert isinstance(p["libass"], str) and p["libass"]


def test_provenance_without_kit_does_not_invent_asr():
    p = provenance(None)
    assert p["asr"] == "not-recorded"


# ---------------------------------------------------------------- record_render

def test_record_render_appends_entry(tmp_path):
    work = _work(tmp_path)
    entry = {
        "render_hash": "ab" * 16,
        "provenance": _prov(),
        "ffmpeg_argv": ["ffmpeg", "-y"],
        "started_at": "2026-09-28T00:00:00+00:00",
        "finished_at": "2026-09-28T00:00:01+00:00",
        "input_hashes": {"clip.mp4": "ff" * 32},
    }
    record_render(work, entry)
    man = json.loads((work / "manifest.json").read_text())
    assert man["renders"] == [entry]
    assert set(man["renders"][0]) == {
        "render_hash", "provenance", "ffmpeg_argv", "started_at",
        "finished_at", "input_hashes",
    }


def test_record_measurement_appends_to_manifest(tmp_path):
    work = _work(tmp_path)
    rec = record_measurement(work, "loudness",
                             {"integrated_lufs": -14.2, "passed": True})
    assert rec["name"] == "loudness"
    assert rec["integrated_lufs"] == -14.2
    assert rec["at"]
    man = json.loads((work / "manifest.json").read_text())
    assert man["measurements"][-1]["name"] == "loudness"
    # history is append-only
    record_measurement(work, "loudness", {"integrated_lufs": -13.9})
    man = json.loads((work / "manifest.json").read_text())
    assert len(man["measurements"]) == 2
