"""BUG-011 regression: a punctuation-only script must fail fast in `_do_align`
with AlignError BEFORE the faster-whisper ASR path (and its multi-hundred-MB
model download) is ever reached.

The test bombs the network (monkeypatched ``socket.socket``) and pins
``hypelab.align.transcribe`` to raise, then drives the real ``audio`` command
via CliRunner. The AlignError from ``_do_align`` must surface before either
trap fires: ``transcribe`` is never called and no socket is ever created.
"""
import re
import socket
import sys
from pathlib import Path

import pytest
from click.testing import CliRunner

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from hypelab import align as align_mod  # noqa: E402
from hypelab.cli import cli              # noqa: E402

KIT_JSON = REPO / "kits" / "cerebratico" / "kit.json"
FIXTURE_VO = REPO / "tests" / "fixtures" / "vo.mp3"


@pytest.fixture()
def env(tmp_path, monkeypatch):
    """Isolated DB + repo root with the cerebratico kit seeded."""
    root = tmp_path / "root"
    (root / "work").mkdir(parents=True)
    dbp = tmp_path / "t.db"
    # Isolate fully: canonical vars win over the legacy aliases, so clear any
    # inherited overrides and point the canonical ones at tmp_path.
    for var in ("HYPELAB_DB_PATH", "HYPELAB_WORK_DIR", "HYPELAB_OUTPUTS_DIR",
                "HYPELAB_LOGS_DIR", "HYPELAB_TMP_DIR", "HYPELAB_KITS_DIR"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("HYPELAB_HOME", str(root))
    monkeypatch.setenv("HYPELAB_DB_PATH", str(dbp))
    monkeypatch.setenv("HYPELAB_DB", str(dbp))
    monkeypatch.setenv("HYPELAB_ROOT", str(root))
    runner = CliRunner()
    r = runner.invoke(cli, ["migrate"])
    assert r.exit_code == 0, r.output
    r = runner.invoke(cli, ["kit", "new", "cerebratico", "--from", str(KIT_JSON)])
    assert r.exit_code == 0, r.output
    assert "seeded at v1" in r.output
    return {"root": root, "db": dbp, "runner": runner}


def _make_job(runner, script_path, aspect="9:16", max_s="45"):
    r = runner.invoke(cli, [
        "new", "--kit", "cerebratico", "--script", str(script_path),
        "--aspect", aspect, "--max-s", max_s,
    ])
    assert r.exit_code == 0, r.output
    m = re.search(r"^job (\S+)", r.output, re.M)
    assert m, r.output
    return m.group(1)


def test_punct_only_script_fails_fast_before_asr(env, tmp_path, monkeypatch):
    runner = env["runner"]

    # "... !!!" is not blank (passes `new`'s empty check); to_beats splits it
    # into punctuation-only beats, but number-normalization still yields zero
    # alignable word tokens -> the degenerate-script trap.
    punct_script = tmp_path / "punct_script.txt"
    punct_script.write_text("... !!!")
    assert punct_script.read_text().strip()

    job_id = _make_job(runner, punct_script)

    # Zero network: any socket creation fails the test.
    def _boom_socket(*a, **k):
        raise AssertionError("network call attempted before AlignError")
    monkeypatch.setattr(socket, "socket", _boom_socket)

    # transcribe() must NEVER be reached: if it is, fail loudly.
    transcribe_calls = []

    def _transcribe_must_not_run(*a, **k):
        transcribe_calls.append((a, k))
        raise AssertionError("transcribe must not be called")
    monkeypatch.setattr(align_mod, "transcribe", _transcribe_must_not_run)

    r = runner.invoke(cli, ["audio", job_id, "--vo", str(FIXTURE_VO)])

    # `_do_align` raises AlignError -> `audio` surfaces it via _die (nonzero).
    assert r.exit_code != 0
    assert "no alignable words" in r.output
    # Both network/ASR traps prove the ASR path was never taken.
    assert not transcribe_calls, "transcribe was called"
    assert "transcribe must not be called" not in r.output
    assert "network call attempted before AlignError" not in r.output
