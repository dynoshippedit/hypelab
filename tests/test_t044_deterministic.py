# T-044 un-quarantine CANDIDATE -- deterministic crash-recovery test
#
# Source: /home/dino/Desktop/.queue/work/TEST-2/t044-deterministic-candidate.py
# (TEST-2 Test Engineer, 2026-09-29). Executed per chief task T-044 2026-09-29.
#
# Wrapper note: this is the candidate function verbatim, renamed to
# test_worker_crash_recovery_sha256_deterministic so it can coexist with the
# quarantined original in tests/test_cli.py. Helpers are imported from
# test_cli (same names the candidate assumes). No app-source change.
#
# Criterion mapping vs the quarantined version:
#   (criterion 2: deterministic kill point) SIGKILL now fires only after the
#       worker's PID-unique ffmpeg temp file (9x16.partial-<worker-pid>.mp4)
#       exists with size > 0 while the DB still reads "rendering".
#   (criterion 1: poll-until-lease-expired) the blind time.sleep(12) is gone;
#       after the kill the test reads lease_expires from the jobs row and
#       polls until wall-clock >= lease_expires (timeout: 120 s grace).
#   (criterion 3: 5 consecutive green full-suite runs) is a process gate for
#       the chief -- this candidate does not self-certify.

import array
import hashlib
import math
import os
import re
import signal
import sqlite3
import subprocess
import time
from pathlib import Path

from test_cli import (
    _cli_subprocess,
    _db_state,
    KIT_JSON,
    FIXTURE_SCRIPT,
    FIXTURE_VO,
    FIXTURE_MUSIC,
)


# T-044 audio tolerance (measured 2026-09-29, Threadripper, ffmpeg 8.1.2):
# sidechaincompress (VO ducking in hypelab/render.py:audio_chain) is
# nondeterministic: the last ~25 ms of the audio tail differs by a tiny
# perturbation. Deterministic-ducking experiment (T-044-DET, 2026-09-29):
# 450 renders of the audio chain -> 6 distinct PCM hashes BOTH with and
# without single-threading flags (identical variant set), so single-threading
# is NOT the fix and the flags were not shipped. Measured peak max |d| approx
# -48.6 dBFS. NOTE: this EXCEEDS Dino's approx -50 dBFS user-facing-bug rule
# of thumb by ~1.4 dB -- Dino WAIVED this 2026-09-29 (accepted as inaudible);
# the transient is ~14 dB below local program RMS. Tolerance = 0.01 amplitude
# (-40 dBFS), ~8.6 dB margin over the measured peak. Video frames stay
# bit-identical across renders, so video keeps the exact assertion.
T044_AUDIO_TOL_AMP = 0.01  # ~8.6 dB margin over measured peak -48.6 dBFS
T044_AUDIO_TOL_DBFS = -40.0  # 20*log10(0.01)


def _decode_video_bytes(path):
    p = subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-i", str(path),
         "-map", "0:v", "-f", "rawvideo", "-pix_fmt", "yuv420p", "-"],
        capture_output=True)
    assert p.returncode == 0, f"T-044: video decode failed for {path}"
    return p.stdout


def _decode_audio_f32(path):
    p = subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-i", str(path),
         "-map", "0:a", "-f", "f32le", "-ac", "2", "-ar", "48000", "-"],
        capture_output=True)
    assert p.returncode == 0, f"T-044: audio decode failed for {path}"
    return p.stdout


def _assert_renders_equivalent(ref_path, crash_path):
    """Video bit-identical; audio within the measured T-044 tolerance."""
    rv, cv = _decode_video_bytes(ref_path), _decode_video_bytes(crash_path)
    assert hashlib.sha256(rv).hexdigest() == hashlib.sha256(cv).hexdigest(), \
        "T-044: video bytes differ between recovered and reference render"
    ra, ca = _decode_audio_f32(ref_path), _decode_audio_f32(crash_path)
    assert len(ra) == len(ca), \
        f"T-044: decoded audio length differs: {len(ra)} != {len(ca)}"
    fa, fc = array.array("f", ra), array.array("f", ca)
    worst = 0.0
    for x, y in zip(fa, fc):
        d = x - y
        ad = -d if d < 0 else d
        if ad > worst:
            worst = ad
    worst_db = 20 * math.log10(worst) if worst > 0 else float("-inf")
    assert worst <= T044_AUDIO_TOL_AMP, \
        (f"T-044: audio differs beyond tolerance: max |Δ| = {worst:.6f} "
         f"({worst_db:.1f} dBFS) > {T044_AUDIO_TOL_DBFS:.0f} dBFS "
         f"(tolerance {T044_AUDIO_TOL_AMP})")


def test_worker_crash_recovery_sha256_deterministic(tmp_path):
    """kill -9 mid-render -> lease expiry -> fresh worker reclaims and the
    output is equivalent to a completed render: video bit-identical, audio
    within the measured sidechaincompress tolerance (see T044_AUDIO_TOL_*)."""
    root = tmp_path / "root"
    (root / "work").mkdir(parents=True)
    dbp = tmp_path / "t.db"
    e = {"HYPELAB_DB": str(dbp), "HYPELAB_ROOT": str(root),
         "HYPELAB_LEASE_SECONDS": "8"}

    def run_cli(*args):
        p = _cli_subprocess(e, *args)
        out, _ = p.communicate(timeout=600)
        assert p.returncode == 0, out
        return out

    def utc_now_s():
        # Seconds-precision UTC ISO, lexicographically comparable with the
        # lease_expires strings queue.py writes via util.now().
        return time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime())

    run_cli("migrate")
    run_cli("kit", "new", "cerebratico", "--from", str(KIT_JSON))

    # Module-scoped clips: generate once, reuse for both jobs so the inputs
    # are byte-identical.
    mediadir = tmp_path / "media"
    mediadir.mkdir()
    clips = []
    for i in range(1, 6):
        c = mediadir / f"clip_b{i}.mp4"
        subprocess.run(
            ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
             "-f", "lavfi", "-i", "testsrc2=size=320x568:rate=30:duration=8",
             "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p",
             str(c)], check=True)
        clips.append(str(c))

    def build_job_through_audio():
        out = run_cli("new", "--kit", "cerebratico",
                      "--script", str(FIXTURE_SCRIPT),
                      "--aspect", "9:16", "--max-s", "45")
        job_id = re.search(r"^job (\S+)", out, re.M).group(1)
        for beat_id, clip in zip(("b1", "b2", "b3", "b4", "b5"), clips):
            run_cli("attach", job_id, beat_id, clip)
        run_cli("audio", job_id, "--vo", str(FIXTURE_VO),
                "--music", str(FIXTURE_MUSIC))
        return job_id

    def job_out(job_id):
        return root / "work" / job_id / "out" / "9x16.mp4"

    # Reference: an equivalent job rendered to completion, then gated to ready
    # so the crash-test worker can't claim it (gates outrank render).
    ref_job = build_job_through_audio()
    run_cli("render", ref_job)
    run_cli("gates", ref_job)

    # Crash job: worker A claims the render; we SIGKILL it at a deterministic
    # kill point -- only once its ffmpeg child provably exists and is writing.
    crash_job = build_job_through_audio()
    wa = _cli_subprocess(e, "work", "--once")
    # render.py: tmp = out.with_name(f"{out.stem}.partial-{os.getpid()}{out.suffix}")
    # The pid is the worker python process's own pid, which we know as wa.pid.
    partial = job_out(crash_job).with_name(f"9x16.partial-{wa.pid}.mp4")

    # T-044 evidence fix (QA worker 2026-09-29, test-harness only -- no product
    # source touched, no product assertion changed): the original candidate
    # loop raised "kill point missed" on its first iteration whenever worker A
    # had not yet claimed the job (state still "queued_render"), i.e. it never
    # waited for the claim. The loop now waits for the claim first
    # (state == "rendering"), then arms the missed-kill-point diagnosis only
    # after "rendering" has actually been observed.
    kill_deadline = time.monotonic() + 300
    seen_rendering = False
    while True:
        if wa.poll() is not None:
            # Worker died before the kill point: a harness/setup failure, not
            # a product finding -- attach its output instead of killing blind.
            out, _ = wa.communicate()
            raise AssertionError(
                "T-044 setup: worker A exited "
                f"(rc={wa.returncode}) before the kill point was reached; "
                f"worker output:\n{out}")
        st = _db_state(dbp, crash_job)
        if st is not None and st[0] == "rendering":
            seen_rendering = True
        elif seen_rendering and st is not None and st[0] != "rendering":
            # The kill point was missed: the worker left "rendering" (finished
            # or failed) before we could kill it mid-render. Fail fast with a
            # diagnosis -- this is the old flake, now explicit.
            raise AssertionError(
                "T-044 setup: kill point missed -- job state is "
                f"{st[0]!r}; never observed mid-render (worker too fast or "
                "test loop starved under load).")
        try:
            ffmpeg_writing = partial.stat().st_size > 0
        except FileNotFoundError:
            ffmpeg_writing = False
        if ffmpeg_writing and st is not None and st[0] == "rendering":
            break  # kill point reached: ffmpeg spawned and writing, job held.
        if time.monotonic() > kill_deadline:
            raise AssertionError(
                "T-044 setup: ffmpeg temp file "
                f"{partial} never appeared within 300 s (worker alive: "
                f"{wa.poll() is None}, claim seen: {seen_rendering}, "
                f"last observed state: "
                f"{st[0] if st else None}).")
        time.sleep(0.25)

    wa.send_signal(signal.SIGKILL)
    wa.wait(timeout=30)

    # Lease expiry: poll until the lease worker A stamped at claim time has
    # actually expired (replaces the old blind sleep(12)). Robust to heartbeat
    # restamps: we read the live lease_expires value after the kill.
    cx = sqlite3.connect(str(dbp))
    try:
        lease_expires = cx.execute(
            "SELECT lease_expires FROM jobs WHERE id=?", (crash_job,)
        ).fetchone()[0]
    finally:
        cx.close()
    assert lease_expires, \
        "T-044 setup: worker A never stamped lease_expires on claim"
    expiry_deadline = time.monotonic() + 120
    while utc_now_s() < lease_expires:
        if time.monotonic() > expiry_deadline:
            raise AssertionError(
                f"T-044 setup: lease_expires={lease_expires} never arrived "
                f"(now {utc_now_s()}).")
        time.sleep(0.25)
    st = _db_state(dbp, crash_job)
    assert st[0] == "rendering", \
        f"job left 'rendering' before any reclaim could happen: {st}"
    # Atomic-output regression: the SIGKILLed worker must not have left a
    # corrupt partial file at the final output path. Renders go to a
    # PID-unique temp file first; only completed renders are renamed on top.
    assert not job_out(crash_job).exists(), \
        f"partial render left at final path: {job_out(crash_job)}"

    wb = _cli_subprocess(e, "work", "--once")
    out_b, _ = wb.communicate(timeout=600)
    assert wb.returncode == 0, out_b
    assert f"claimed {crash_job}" in out_b
    st, attempts = _db_state(dbp, crash_job)
    assert st == "queued_gates", (st, out_b)
    assert attempts >= 2  # the reclaim consumed a second attempt

    _assert_renders_equivalent(job_out(ref_job), job_out(crash_job))
