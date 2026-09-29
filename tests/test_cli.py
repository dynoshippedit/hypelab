"""CLI acceptance tests — Book 1 improved, sections 12-13.

The Click CLI is exercised two ways:
  * CliRunner (in-process) against an isolated DB/root via HYPELAB_DB /
    HYPELAB_ROOT for the fast command tests;
  * real subprocesses for the kill -9 crash-recovery test (a real process
    must die; HYPELAB_LEASE_SECONDS shortens the 30-minute lease).

Media fixtures are generated locally with ffmpeg/espeak-ng (no network).
The forced-alignment tests use the real local wav2vec2 model.
"""

import json
import os
import re
import signal
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from click.testing import CliRunner  # noqa: E402

from hypelab.cli import cli, normalize_numbers  # noqa: E402
from hypelab import util as util_mod  # noqa: E402

FIXTURE_SCRIPT = REPO / "fixtures" / "script.txt"
KIT_JSON = REPO / "kits" / "cerebratico" / "kit.json"
FIXTURE_VO = REPO / "tests" / "fixtures" / "vo.mp3"
FIXTURE_MUSIC = REPO / "tests" / "fixtures" / "music.mp3"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def env(tmp_path, monkeypatch):
    """Isolated DB + repo root with the cerebratico kit seeded."""
    root = tmp_path / "root"
    (root / "work").mkdir(parents=True)
    dbp = tmp_path / "t.db"
    monkeypatch.setenv("HYPELAB_DB", str(dbp))
    monkeypatch.setenv("HYPELAB_ROOT", str(root))
    runner = CliRunner()
    r = runner.invoke(cli, ["migrate"])
    assert r.exit_code == 0, r.output
    r = runner.invoke(cli, ["kit", "new", "cerebratico", "--from", str(KIT_JSON)])
    assert r.exit_code == 0, r.output
    assert "seeded at v1" in r.output
    return {"root": root, "db": dbp, "runner": runner}


@pytest.fixture(scope="module")
def media(tmp_path_factory):
    """Locally generated media: 5 beat clips, fixture VO/music, espeak VO."""
    d = tmp_path_factory.mktemp("climedia")
    clips = []
    for i in range(1, 6):
        c = d / f"clip_b{i}.mp4"
        subprocess.run(
            ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
             "-f", "lavfi", "-i",
             "testsrc2=size=320x568:rate=30:duration=8",
             "-c:v", "libx264", "-preset", "veryfast",
             "-pix_fmt", "yuv420p", str(c)],
            check=True,
        )
        clips.append(c)

    # espeak VO for the numbers test: speak the NORMALIZED text so the
    # acoustic content matches what the aligner expects after normalization.
    num_script = "I counted 3 stars. There were 42 ships. The year was 1999."
    norm_spoken = normalize_numbers(num_script)
    num_wav = d / "numbers_vo.wav"
    subprocess.run(
        ["espeak-ng", "-v", "en", "-s", "150", "-w", str(num_wav), norm_spoken],
        check=True,
    )
    num_mp3 = d / "numbers_vo.mp3"
    subprocess.run(
        ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
         "-i", str(num_wav), "-c:a", "libmp3lame", "-b:a", "128k",
         str(num_mp3)],
        check=True,
    )
    return {
        "dir": d,
        "clips": clips,
        "num_script": num_script,
        "num_vo": num_mp3,
    }


def _db_state(dbp, job_id):
    cx = sqlite3.connect(str(dbp))
    try:
        return cx.execute(
            "SELECT state, attempts FROM jobs WHERE id=?", (job_id,)
        ).fetchone()
    finally:
        cx.close()


def _make_job(runner, script_path, aspect="9:16", max_s="45"):
    r = runner.invoke(cli, [
        "new", "--kit", "cerebratico", "--script", str(script_path),
        "--aspect", aspect, "--max-s", max_s,
    ])
    assert r.exit_code == 0, r.output
    m = re.search(r"^job (\S+)", r.output, re.M)
    assert m, r.output
    return m.group(1)


def _attach_all(runner, job_id, clips, beats=("b1", "b2", "b3", "b4", "b5")):
    for beat_id, clip in zip(beats, clips):
        r = runner.invoke(cli, ["attach", job_id, beat_id, str(clip)])
        assert r.exit_code == 0, r.output
        assert "sha256:" in r.output


def _full_pipeline_to_render(runner, env, media, aspect="9:16"):
    """new -> attach x5 -> audio -> render.  Returns (job_id, out_path)."""
    job_id = _make_job(runner, FIXTURE_SCRIPT, aspect=aspect)
    _attach_all(runner, job_id, media["clips"])
    r = runner.invoke(cli, [
        "audio", job_id, "--vo", str(FIXTURE_VO),
        "--music", str(FIXTURE_MUSIC),
    ])
    assert r.exit_code == 0, r.output
    assert "aligned 60 words" in r.output
    r = runner.invoke(cli, ["render", job_id])
    assert r.exit_code == 0, r.output
    assert "rendered" in r.output
    out = env["root"] / "work" / job_id / "out" / f"{aspect.replace(':', 'x')}.mp4"
    assert out.is_file()
    return job_id, out


# ---------------------------------------------------------------------------
# Command basics
# ---------------------------------------------------------------------------

def test_migrate_prints_versions(env):
    r = env["runner"].invoke(cli, ["migrate"])
    assert r.exit_code == 0, r.output
    assert "0001_book1_foundation" in r.output


def test_kit_new_duplicate_fails_cleanly(env):
    r = env["runner"].invoke(cli,
                             ["kit", "new", "cerebratico", "--from", str(KIT_JSON)])
    assert r.exit_code != 0
    assert "already exists" in r.output


def test_new_creates_job_and_beats(env):
    runner = env["runner"]
    job_id = _make_job(runner, FIXTURE_SCRIPT)
    assert _db_state(env["db"], job_id)[0] == "scripted"
    edl = json.loads(
        (env["root"] / "work" / job_id / "render.json").read_text())
    assert len(edl["beats"]) == 5
    assert edl["kit"] == "cerebratico@1"
    assert (env["root"] / "work" / job_id / "script.txt").is_file()


def test_new_unknown_kit_fails(env):
    r = env["runner"].invoke(cli, [
        "new", "--kit", "nosuchkit", "--script", str(FIXTURE_SCRIPT)])
    assert r.exit_code != 0
    assert "not found" in r.output


def test_shots_prints_numbered_prompts(env):
    runner = env["runner"]
    job_id = _make_job(runner, FIXTURE_SCRIPT)
    r = runner.invoke(cli, ["shots", job_id])
    assert r.exit_code == 0, r.output
    assert "[1/5]" in r.output and "[5/5]" in r.output
    assert "reference_image:" in r.output
    assert f"hypelab attach {job_id} b1" in r.output


def test_attach_unknown_beat_fails(env, media):
    runner = env["runner"]
    job_id = _make_job(runner, FIXTURE_SCRIPT)
    r = runner.invoke(cli, ["attach", job_id, "b9", str(media["clips"][0])])
    assert r.exit_code != 0
    assert "unknown beat" in r.output


def test_attach_records_sha256_and_clip_fields(env, media):
    runner = env["runner"]
    job_id = _make_job(runner, FIXTURE_SCRIPT)
    clip = media["clips"][0]
    r = runner.invoke(cli, ["attach", job_id, "b1", str(clip)])
    assert r.exit_code == 0, r.output
    m = re.search(r"sha256: ([0-9a-f]{64})", r.output)
    assert m, r.output
    assert m.group(1) == util_mod.sha256_file(str(clip))
    edl = json.loads(
        (env["root"] / "work" / job_id / "render.json").read_text())
    b1 = next(b for b in edl["beats"] if b["id"] == "b1")
    # Renderer reads clip; gates.check_slots reads clip_slot/clip_path.
    assert b1["clip"] and b1["clip_slot"] == "b1" and b1["clip_path"]
    assert Path(b1["clip"]).is_file()


def test_costs_empty(env):
    r = env["runner"].invoke(cli, ["costs"])
    assert r.exit_code == 0, r.output
    assert "no cost rows" in r.output


# ---------------------------------------------------------------------------
# Number normalization (wav2vec2 has no digits)
# ---------------------------------------------------------------------------

def test_normalize_numbers():
    assert normalize_numbers("I counted 3 stars.") == "I counted three stars."
    assert normalize_numbers("There were 42 ships.") == \
        "There were forty two ships."
    assert normalize_numbers("The year was 1999.") == \
        "The year was nineteen ninety nine."
    assert normalize_numbers("It costs 3.14.") == "It costs three point one four."
    assert normalize_numbers("Save 20% today.") == "Save twenty percent today."
    # Thousands separator forces cardinal reading, never a year.
    assert "one thousand nine hundred ninety nine" in normalize_numbers(
        "1,999 people came.")


def test_audio_aligns_script_with_digits(env, media):
    """A script containing 3/42/1999 aligns without AlignError (espeak VO)."""
    runner = env["runner"]
    script = media["dir"] / "numbers.txt"
    script.write_text(media["num_script"])
    job_id = _make_job(runner, script)
    _attach_all(runner, job_id, media["clips"][:3], beats=("b1", "b2", "b3"))
    r = runner.invoke(cli, ["audio", job_id, "--vo", str(media["num_vo"])])
    assert r.exit_code == 0, r.output  # no AlignError
    words_path = env["root"] / "work" / job_id / "vo.words.json"
    assert words_path.is_file()
    doc = json.loads(words_path.read_text())
    assert doc["timing"] == "forced_aligned"
    assert doc["n_words"] > 0
    # The aligned stream is the normalized vocabulary: no digits survive.
    assert not any(re.search(r"\d", w["w"]) for w in doc["words"])
    # The spelled-out numbers made it into the stream.
    text = " ".join(w["w"] for w in doc["words"])
    assert "three" in text and "forty two" in text
    assert "nineteen ninety nine" in text


# ---------------------------------------------------------------------------
# Render hash-skip + the 7-gate table
# ---------------------------------------------------------------------------

def test_render_skip(env, media):
    runner = env["runner"]
    job_id, out = _full_pipeline_to_render(runner, env, media)
    first_hash = util_mod.sha256_file(str(out))
    r = runner.invoke(cli, ["render", job_id])
    assert r.exit_code == 0, r.output
    assert "hash unchanged, skipping" in r.output
    assert util_mod.sha256_file(str(out)) == first_hash


def test_gates_prints_seven_pass_rows(env, media):
    runner = env["runner"]
    job_id, out = _full_pipeline_to_render(runner, env, media)
    r = runner.invoke(cli, ["gates", job_id])
    assert r.exit_code == 0, r.output
    for gate in ("duration", "loudness", "first_frame", "hook_budget",
                 "caption_safe", "slots_filled", "geometry"):
        assert re.search(rf"^{gate} PASS\b", r.output, re.M), \
            f"missing PASS row for {gate}:\n{r.output}"
    assert _db_state(env["db"], job_id)[0] == "ready"


# ---------------------------------------------------------------------------
# Worker: --once and kill -9 crash recovery
# ---------------------------------------------------------------------------

def _cli_subprocess(env_extra, *args, cwd=REPO):
    e = dict(os.environ)
    e.update(env_extra)
    return subprocess.Popen(
        [sys.executable, "-m", "hypelab.cli", *args],
        cwd=str(cwd), env=e,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)


def test_work_once_claims_single_job(env, media):
    runner = env["runner"]
    job_id = _make_job(runner, FIXTURE_SCRIPT)
    _attach_all(runner, job_id, media["clips"])
    r = runner.invoke(cli, ["audio", job_id, "--vo", str(FIXTURE_VO)])
    assert r.exit_code == 0, r.output
    assert _db_state(env["db"], job_id)[0] == "queued_render"

    e = {"HYPELAB_DB": str(env["db"]), "HYPELAB_ROOT": str(env["root"])}
    p = _cli_subprocess(e, "work", "--once")
    out, _ = p.communicate(timeout=600)
    assert p.returncode == 0, out
    assert f"claimed {job_id}" in out
    # --once handled exactly one job: it rendered, then queued gates.
    assert _db_state(env["db"], job_id)[0] == "queued_gates"


