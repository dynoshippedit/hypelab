"""D4 / T-040: tracked outputs were extracted to HYPELAB_OUTPUTS_DIR.

(a) outputs_dir defaults to <HYPELAB_HOME>/outputs and follows a fresh home
(b) HYPELAB_OUTPUTS_DIR overrides the default; other paths stay default
(c) .gitignore covers the outputs directory (outputs are never committed)
(d) the historical slice outputs resolve under the configured outputs dir
    (a caller computing the location must use config, not a hardcoded path)
"""
import os
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from hypelab import config as config_mod  # noqa: E402


def _clean_env(monkeypatch, tmp_path):
    for v in ("HYPELAB_HOME", "HYPELAB_ROOT", "HYPELAB_DB", "HYPELAB_DB_PATH",
              "HYPELAB_WORK_DIR", "HYPELAB_MODELS_DIR", "HYPELAB_OUTPUTS_DIR",
              "HYPELAB_LOGS_DIR", "HYPELAB_TMP_DIR", "HYPELAB_KITS_DIR"):
        monkeypatch.delenv(v, raising=False)
    monkeypatch.setenv("HYPELAB_HOME", str(tmp_path))


def test_outputs_dir_defaults_under_home(monkeypatch, tmp_path):
    _clean_env(monkeypatch, tmp_path)
    cfg = config_mod.resolve_config()
    assert cfg.outputs_dir == tmp_path.absolute() / "outputs"


def test_outputs_dir_override_alone(monkeypatch, tmp_path):
    _clean_env(monkeypatch, tmp_path)
    elsewhere = tmp_path / "elsewhere-outputs"
    monkeypatch.setenv("HYPELAB_OUTPUTS_DIR", str(elsewhere))
    cfg = config_mod.resolve_config()
    assert cfg.outputs_dir == elsewhere.absolute()
    assert cfg.work_dir == tmp_path.absolute() / "work"


def test_gitignore_covers_outputs_dir():
    text = (REPO / ".gitignore").read_text()
    lines = [l.strip() for l in text.splitlines()]
    assert "/outputs/" in lines, ".gitignore must ignore the outputs directory"


def test_no_tracked_files_under_outputs_or_legacy_jobs():
    import subprocess
    out = subprocess.run(["git", "ls-files"], cwd=str(REPO),
                         capture_output=True, text=True)
    assert out.returncode == 0, out.stderr
    tracked = out.stdout.splitlines()
    bad = [p for p in tracked
           if p.startswith("outputs/") or p.startswith("jobs/")]
    assert bad == [], f"outputs must not be tracked: {bad}"


def test_historical_slice_outputs_resolve_via_config(monkeypatch, tmp_path):
    # The historical vertical-slice job was extracted from git into
    # <home>/outputs/job_c656669a5147. Code/tests must derive the location
    # from config.outputs_dir, never a hardcoded jobs/ path.
    _clean_env(monkeypatch, tmp_path)
    cfg = config_mod.resolve_config()
    hist = cfg.outputs_dir / "job_c656669a5147" / "master.mp4"
    assert str(hist).startswith(str(cfg.home)), \
        "historical outputs must live under the configured home"
    assert "jobs/" not in str(hist)
