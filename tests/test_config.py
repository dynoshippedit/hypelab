"""D3 / T-019: HYPELAB_HOME single-root configuration.

(a) defaults derive every path from the root
(b) each per-path override takes effect alone, others stay default
(c) startup validation fails fast on an unusable root
(d) the printed config never contains secret values
(e) a fresh HYPELAB_HOME boots: startup + migrate smoke
+ legacy HYPELAB_ROOT / HYPELAB_DB aliases keep working
"""
import os
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from hypelab import config as config_mod  # noqa: E402
from hypelab.config import ConfigError  # noqa: E402


def _clean_env(monkeypatch, tmp_path):
    for v in ("HYPELAB_HOME", "HYPELAB_ROOT", "HYPELAB_DB", "HYPELAB_DB_PATH",
              "HYPELAB_WORK_DIR", "HYPELAB_MODELS_DIR", "HYPELAB_OUTPUTS_DIR",
              "HYPELAB_LOGS_DIR", "HYPELAB_TMP_DIR", "HYPELAB_KITS_DIR"):
        monkeypatch.delenv(v, raising=False)
    monkeypatch.setenv("HYPELAB_HOME", str(tmp_path))


def test_defaults_derive_from_root(monkeypatch, tmp_path):
    _clean_env(monkeypatch, tmp_path)
    cfg = config_mod.resolve_config()
    home = tmp_path.absolute()
    assert cfg.home == home
    assert cfg.db_path == home / "hypelab.db"
    assert cfg.work_dir == home / "work"
    # models_dir is intentionally machine-global (not under the home) so a
    # fresh/isolated HYPELAB_HOME shares the real model cache.
    assert cfg.models_dir == Path("/home/dino/hypelab/models")
    assert cfg.outputs_dir == home / "outputs"
    assert cfg.logs_dir == home / "logs"
    assert cfg.tmp_dir == home / "tmp"
    assert cfg.kits_dir == home / "kits"


@pytest.mark.parametrize("var,attr", [
    ("HYPELAB_DB_PATH", "db_path"),
    ("HYPELAB_WORK_DIR", "work_dir"),
    ("HYPELAB_MODELS_DIR", "models_dir"),
    ("HYPELAB_OUTPUTS_DIR", "outputs_dir"),
    ("HYPELAB_LOGS_DIR", "logs_dir"),
    ("HYPELAB_TMP_DIR", "tmp_dir"),
    ("HYPELAB_KITS_DIR", "kits_dir"),
])
def test_each_override_alone(monkeypatch, tmp_path, var, attr):
    _clean_env(monkeypatch, tmp_path)
    custom = tmp_path / "custom"
    monkeypatch.setenv(var, str(custom))
    cfg = config_mod.resolve_config()
    home = tmp_path.absolute()
    # the overridden path takes effect...
    assert getattr(cfg, attr) == custom.absolute()
    # ...and every other path still derives from the root
    assert cfg.home == home
    for other_var, other_attr in [
        ("HYPELAB_DB_PATH", "db_path"), ("HYPELAB_WORK_DIR", "work_dir"),
        ("HYPELAB_MODELS_DIR", "models_dir"), ("HYPELAB_OUTPUTS_DIR", "outputs_dir"),
        ("HYPELAB_LOGS_DIR", "logs_dir"), ("HYPELAB_TMP_DIR", "tmp_dir"),
        ("HYPELAB_KITS_DIR", "kits_dir"),
    ]:
        if other_attr == attr:
            continue
        if other_attr == "models_dir":
            # machine-global default, not under the home
            assert getattr(cfg, other_attr) == Path("/home/dino/hypelab/models")
            continue
        default_rel = {"db_path": "hypelab.db", "work_dir": "work",
                       "outputs_dir": "outputs",
                       "logs_dir": "logs", "tmp_dir": "tmp",
                       "kits_dir": "kits"}[other_attr]
        assert getattr(cfg, other_attr) == home / default_rel


def test_legacy_aliases(monkeypatch, tmp_path):
    for v in ("HYPELAB_HOME", "HYPELAB_ROOT", "HYPELAB_DB", "HYPELAB_DB_PATH"):
        monkeypatch.delenv(v, raising=False)
    monkeypatch.setenv("HYPELAB_ROOT", str(tmp_path))
    monkeypatch.setenv("HYPELAB_DB", str(tmp_path / "legacy.db"))
    cfg = config_mod.resolve_config()
    assert cfg.home == tmp_path.absolute()
    assert cfg.db_path == (tmp_path / "legacy.db").absolute()
    # HYPELAB_HOME wins over HYPELAB_ROOT when both are set
    monkeypatch.setenv("HYPELAB_HOME", str(tmp_path / "newhome"))
    cfg2 = config_mod.resolve_config()
    assert cfg2.home == (tmp_path / "newhome").absolute()


def test_validation_fails_fast_on_unusable_root(monkeypatch, tmp_path):
    _clean_env(monkeypatch, tmp_path)
    blocker = tmp_path / "afile"
    blocker.write_text("x")
    monkeypatch.setenv("HYPELAB_HOME", str(blocker / "sub"))
    cfg = config_mod.resolve_config()
    with pytest.raises(ConfigError, match="unusable HYPELAB_HOME"):
        config_mod.validate_config(cfg)


def test_printed_config_has_no_secrets(monkeypatch, tmp_path, capsys):
    _clean_env(monkeypatch, tmp_path)
    monkeypatch.setenv("HYPELAB_FAKE_SECRET", "s3cr3t-value-xyz")
    monkeypatch.setenv("HYPELAB_API_KEY", "key-abc-123")
    cfg = config_mod.resolve_config()
    config_mod.print_config(cfg)
    out = capsys.readouterr().out
    assert "s3cr3t-value-xyz" not in out
    assert "key-abc-123" not in out
    assert str(tmp_path) in out  # but the paths ARE printed


def test_fresh_home_startup_and_migrate(monkeypatch, tmp_path):
    """(e) A brand-new HYPELAB_HOME boots: validate + print + migrate."""
    _clean_env(monkeypatch, tmp_path)
    fresh = tmp_path / "fresh"
    assert not fresh.exists()
    monkeypatch.setenv("HYPELAB_HOME", str(fresh))
    cfg = config_mod.startup()
    assert fresh.is_dir()
    assert (fresh / "work").is_dir()
    # init/migrate smoke: the app's real DB boots on the fresh root
    from hypelab import db as db_mod
    cx = db_mod.connect()
    try:
        tables = {r[0] for r in cx.execute(
            "select name from sqlite_master where type='table'")}
        assert "jobs" in tables
        assert "schema_migrations" in tables
    finally:
        cx.close()


def test_db_connect_uses_configured_path(monkeypatch, tmp_path):
    _clean_env(monkeypatch, tmp_path)
    from hypelab import db as db_mod
    custom = tmp_path / "custom.db"
    monkeypatch.setenv("HYPELAB_DB_PATH", str(custom))
    cx = db_mod.connect()
    try:
        assert custom.is_file()
    finally:
        cx.close()
