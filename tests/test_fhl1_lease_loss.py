"""F-HL-1 regression: lease-loss / concurrent-worker render safety.

Principal Reviewer finding F-HL-1 (full-review-2026-09-29): a worker that
loses its lease keeps rendering, and a reclaimed job can therefore be
rendered by two workers concurrently. Chief repair direction: the render
output goes to a PID-unique temp file and is atomically renamed onto the
final path only on success -- ffmpeg must never ``-y`` onto the shared
output. (The heartbeat/lease policy itself is unchanged by chief decision.)

These tests simulate the lease-loss scenario at the render() level, where
the temp-file + atomic-rename mechanism lives (hypelab/render.py: render):

1. test_concurrent_workers_no_partial_final_output -- two worker PROCESSES
   (faithful to production: separate PIDs, same job work dir, same final
   path) render the same job concurrently. The final file must be a
   complete, valid render -- video bit-identical to a single reference
   render per the T-044 determinism result -- and no ``.partial-*`` temp
   files may remain.
2. test_killed_worker_leaves_final_output_intact -- a worker killed
   mid-render (its torn ffmpeg write lands on the temp file only) leaves a
   pre-existing final output byte-identical.
3. test_ffmpeg_never_targets_final_path -- the ffmpeg argv emitted by
   render() writes to a ``.partial-<pid>`` temp sibling, never to ``out``
   itself; ``-y`` is retained for temp-file reuse on PID recycle only.

Each test FAILS against the broken implementation (ffmpeg ``-y`` straight
onto the shared path): (1) interleaved concurrent writes corrupt the final
file, (2) the torn write lands on the final path, (3) the argv target is
the final path.
"""
from __future__ import annotations

import hashlib
import multiprocessing as mp
import shutil
import subprocess
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from hypelab import edl as edl_mod
from hypelab import render as render_mod


# ------------------------------------------------------------------ fixtures

def _target(**kw):
    t = {
        "aspect": "9:16", "w": 360, "h": 640, "fps": 30,
        "max_duration_s": 60.0, "loudness_lufs": -16.0,
    }
    t.update(kw)
    return t


@pytest.fixture(scope="module")
def media(tmp_path_factory):
    """Real tiny fixtures: 2 video clips + vo + music, generated with ffmpeg."""
    d = tmp_path_factory.mktemp("fhl1-media")

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
    return edl_mod.build_edl(mode="clip", kit_ref="cerebratico@1",
                             target=_target(), beats=beats, audio=audio,
                             overlays=[])


def _decode_video_bytes(path):
    p = subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-i", str(path),
         "-map", "0:v", "-f", "rawvideo", "-pix_fmt", "yuv420p", "-"],
        capture_output=True)
    assert p.returncode == 0, f"F-HL-1: video decode failed for {path}"
    return p.stdout


def _video_sha(path):
    return hashlib.sha256(_decode_video_bytes(path)).hexdigest()


# ------------------------------------------------------------------ test 1

def _child_render(edl, work, out, q):
    """Worker-process entry: render the job exactly like a real worker."""
    try:
        rec = render_mod.render(edl, work, out)
        q.put(("ok", rec["render_hash"]))
    except Exception as e:  # noqa: BLE001 -- ferry the failure to the parent
        q.put(("error", repr(e)))


def test_concurrent_workers_no_partial_final_output(media, tmp_path):
    """Two workers (separate PIDs) render the same job concurrently.

    Lease-loss scenario: worker A keeps rendering after its lease expired;
    the reaper hands the job to worker B. Both ffmpeg processes must write
    to PID-unique temp files; the final path only ever receives complete
    renders via atomic rename.
    """
    work, out = str(tmp_path / "work"), str(tmp_path / "out.mp4")
    edl = _render_edl(media)

    # Reference: single render; video is bit-identical across renders (T-044).
    render_mod.render(edl, work, out)
    ref_video_sha = _video_sha(out)
    Path(out).unlink()

    # spawn (not fork): the child re-imports this module cleanly, avoiding
    # fork-in-multi-threaded-process deadlock hazards under pytest.
    ctx = mp.get_context("spawn")
    q = ctx.Queue()
    p1 = ctx.Process(target=_child_render, args=(edl, work, out, q))
    p2 = ctx.Process(target=_child_render, args=(edl, work, out, q))
    p1.start()
    time.sleep(0.5)  # ensure both ffmpeg processes are in flight together
    p2.start()
    p1.join(timeout=300)
    p2.join(timeout=300)
    for p in (p1, p2):
        if p.is_alive():
            p.terminate()
            pytest.fail("F-HL-1: worker render hung")

    results = sorted(q.get() for _ in range(2))
    assert results[0][0] == "ok" and results[1][0] == "ok", \
        f"F-HL-1: concurrent renders failed: {results}"

    final = Path(out)
    assert final.is_file(), "F-HL-1: final output missing after concurrent renders"
    # Complete, valid render: decodable and video-identical to the reference.
    assert _video_sha(final) == ref_video_sha, \
        "F-HL-1: concurrent renders left a torn/interleaved final output"
    # Temp files are renamed away on success; none may remain.
    partials = list(final.parent.glob("*.partial-*"))
    assert partials == [], f"F-HL-1: temp files left behind: {partials}"


# ------------------------------------------------------------------ test 2

def test_killed_worker_leaves_final_output_intact(media, tmp_path, monkeypatch):
    """A worker killed mid-render must not touch the final output path.

    Simulates the SIGKILL case: ffmpeg's torn write lands on the worker's
    temp file; the pre-existing (other worker's) final output stays
    byte-identical.
    """
    work, out = tmp_path / "work", tmp_path / "out.mp4"
    edl = _render_edl(media)
    render_mod.render(edl, work, out)  # the good, pre-existing output
    before = out.read_bytes()
    ref_video_sha = _video_sha(out)  # sanity: it is a valid render

    real_run = render_mod.subprocess.run

    def fake_run(cmd, **kw):
        if cmd[0] != "ffmpeg" or "-version" in cmd:
            return real_run(cmd, **kw)  # ffprobe / version pin: real
        target = Path(cmd[-1])
        target.write_bytes(b"TORN" * 16384)  # torn write: temp file only
        raise subprocess.TimeoutExpired(cmd, 5)  # worker killed mid-render

    monkeypatch.setattr(render_mod.subprocess, "run", fake_run)
    with pytest.raises(subprocess.TimeoutExpired):
        render_mod.render(edl, work, out)
    monkeypatch.undo()  # decode helpers below need the real ffmpeg

    assert out.read_bytes() == before, \
        "F-HL-1: killed worker's partial write reached the final output"
    partials = [p for p in out.parent.glob("*.partial-*") if p != out]
    assert partials, "F-HL-1: expected the killed worker's temp file to exist"
    assert _video_sha(out) == ref_video_sha  # still a valid, complete render


# ------------------------------------------------------------------ test 3

def test_ffmpeg_never_targets_final_path(media, tmp_path, monkeypatch):
    """render() must never `-y` onto the shared output: ffmpeg's target is
    always a `.partial-<pid>` temp sibling; the final path is only ever
    written by atomic rename."""
    work, out = tmp_path / "work", tmp_path / "out.mp4"
    edl = _render_edl(media)

    tiny = tmp_path / "tiny.mp4"
    subprocess.run(
        ["ffmpeg", "-y", "-v", "error", "-f", "lavfi",
         "-i", "testsrc=size=320x576:rate=30:duration=1",
         "-pix_fmt", "yuv420p", "-c:v", "libx264", "-preset", "veryfast",
         str(tiny)],
        check=True, capture_output=True, timeout=120)

    real_run = render_mod.subprocess.run
    captured = {}

    def fake_run(cmd, **kw):
        if cmd[0] != "ffmpeg" or "-version" in cmd:
            return real_run(cmd, **kw)  # ffprobe / version pin: real
        captured["cmd"] = list(cmd)
        shutil.copyfile(tiny, cmd[-1])  # stand-in for a successful ffmpeg
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(render_mod.subprocess, "run", fake_run)
    rec = render_mod.render(edl, work, out)

    cmd = captured["cmd"]
    assert cmd[0] == "ffmpeg" and "-y" in cmd  # -y kept for temp-file reuse
    target = Path(cmd[-1])
    assert target != out, "F-HL-1: ffmpeg targets the shared final path"
    assert target.parent == out.parent
    assert ".partial-" in target.name, \
        f"F-HL-1: ffmpeg target is not a PID-unique temp file: {target.name}"
    assert rec["skipped"] is False
    assert out.is_file() and out.read_bytes() == tiny.read_bytes()
