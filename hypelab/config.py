"""Single-root configuration (D3 / T-019, owner-decided 2026-09-29).

One variable owns every path: HYPELAB_HOME. All other paths derive from it
by default; each derived path has a documented HYPELAB_* variable that can
override it individually.

Variables
---------
HYPELAB_HOME        Root of everything. Default: /home/dino/hypelab
                    (the historical dev default, kept so existing flows work).
                    Legacy alias HYPELAB_ROOT is honored; if both are set,
                    HYPELAB_HOME wins.
HYPELAB_DB_PATH     SQLite state & ledger file. Default: <home>/hypelab.db.
                    Legacy alias HYPELAB_DB is honored (HYPELAB_DB_PATH wins).
HYPELAB_WORK_DIR    Job work dirs (work/<job_id>/). Default: <home>/work.
HYPELAB_MODELS_DIR  Read-mostly model caches. Default: /home/dino/hypelab/models
                    (machine-global, NOT under the home: a fresh HYPELAB_HOME
                    must not force model re-downloads, and tests isolate the
                    home while sharing the real model cache).
HYPELAB_OUTPUTS_DIR Build outputs (D4 relocates tracked outputs here).
                    Default: <home>/outputs.
HYPELAB_LOGS_DIR    Log files. Default: <home>/logs.
HYPELAB_TMP_DIR     Ephemeral temp files. Default: <home>/tmp.
HYPELAB_KITS_DIR    Read-only content kits. Default: <home>/kits.

Not owned by this module (unchanged behavior):
HYPELAB_LEASE_SECONDS   worker lease override (seconds, test-only).
HYPELAB_CHROMIUM        browser binary for the carousel prober.
HYPELAB_VERSION         version string.

Secrets
-------
Secrets are NEVER derived from the root. A secret lives in its own
environment variable (e.g. HYPELAB_SOME_API_KEY) and is NEVER printed by
print_config(). There are no secrets in the app today; this rule governs
the day they arrive.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

DEFAULT_HOME = Path("/home/dino/hypelab")

#: (attribute, env var, default relative to home, legacy alias)
_PATH_SPECS = (
    ("db_path", "HYPELAB_DB_PATH", "hypelab.db", "HYPELAB_DB"),
    ("work_dir", "HYPELAB_WORK_DIR", "work", None),
    ("models_dir", "HYPELAB_MODELS_DIR", "models", None),
    ("outputs_dir", "HYPELAB_OUTPUTS_DIR", "outputs", None),
    ("logs_dir", "HYPELAB_LOGS_DIR", "logs", None),
    ("tmp_dir", "HYPELAB_TMP_DIR", "tmp", None),
    ("kits_dir", "HYPELAB_KITS_DIR", "kits", None),
)

#: Derived dirs the app must be able to create (kits/models are read-only
#: inputs and may legitimately be absent, e.g. a fresh HYPELAB_HOME).
_CREATABLE = ("work_dir", "logs_dir", "tmp_dir", "outputs_dir")

#: Defaults that are intentionally NOT under the home: the model cache is a
#: machine-global read-mostly cache. Deriving it from HYPELAB_HOME would
#: force re-downloads on every fresh home and break test isolation, which
#: shares the real cache while pointing the home at a tmp dir.
_ABSOLUTE_DEFAULTS = {
    "models_dir": Path("/home/dino/hypelab/models"),
}


class ConfigError(Exception):
    """Raised when the resolved configuration is unusable. Fail fast."""


@dataclass
class HypeLabConfig:
    home: Path
    db_path: Path
    work_dir: Path
    models_dir: Path
    outputs_dir: Path
    logs_dir: Path
    tmp_dir: Path
    kits_dir: Path
    #: where each value came from, for the startup printout
    sources: dict = field(default_factory=dict, repr=False)

    def as_dict(self) -> dict:
        return {
            "HYPELAB_HOME": str(self.home),
            "HYPELAB_DB_PATH": str(self.db_path),
            "HYPELAB_WORK_DIR": str(self.work_dir),
            "HYPELAB_MODELS_DIR": str(self.models_dir),
            "HYPELAB_OUTPUTS_DIR": str(self.outputs_dir),
            "HYPELAB_LOGS_DIR": str(self.logs_dir),
            "HYPELAB_TMP_DIR": str(self.tmp_dir),
            "HYPELAB_KITS_DIR": str(self.kits_dir),
        }


def _env(env, *names):
    for n in names:
        v = env.get(n)
        if v and v.strip():
            return v.strip(), n
    return None, None


def resolve_config(env=None) -> HypeLabConfig:
    """Resolve the full configuration from the environment.

    One function owns "where does everything live". HYPELAB_HOME is the
    root; every other path derives from it unless its own variable (or
    legacy alias) overrides it. Nothing is cached: callers always see the
    current environment (tests rely on this).
    """
    env = os.environ if env is None else env
    home_raw, home_src = _env(env, "HYPELAB_HOME", "HYPELAB_ROOT")
    home = Path(home_raw).expanduser() if home_raw else DEFAULT_HOME
    home = home.absolute()
    sources = {"HYPELAB_HOME": home_src or "default:/home/dino/hypelab"}

    kwargs = {"home": home, "sources": sources}
    for attr, var, default_rel, legacy in _PATH_SPECS:
        names = (var,) + ((legacy,) if legacy else ())
        raw, src = _env(env, *names)
        if raw:
            kwargs[attr] = Path(raw).expanduser().absolute()
            sources[var] = src
        elif attr in _ABSOLUTE_DEFAULTS:
            kwargs[attr] = _ABSOLUTE_DEFAULTS[attr]
            sources[var] = "default:%s (machine-global)" % _ABSOLUTE_DEFAULTS[attr]
        else:
            kwargs[attr] = (home / default_rel).absolute()
            sources[var] = "default:<home>/%s" % default_rel
    return HypeLabConfig(**kwargs)


def validate_config(cfg: HypeLabConfig) -> HypeLabConfig:
    """Validate the resolved paths; fail fast with a clear message.

    The root must exist or be creatable; the writable derived dirs
    (work/logs/tmp/outputs) and the DB's parent dir must be creatable.
    Kits/models are read-only inputs and may be absent.
    """
    try:
        cfg.home.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        raise ConfigError(f"unusable HYPELAB_HOME {cfg.home}: {e}")
    for attr in _CREATABLE:
        d = getattr(cfg, attr)
        try:
            d.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            raise ConfigError(f"cannot create {attr} {d}: {e}")
    try:
        cfg.db_path.parent.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        raise ConfigError(f"cannot create db dir {cfg.db_path.parent}: {e}")
    return cfg


def print_config(cfg: HypeLabConfig) -> None:
    """Print the resolved configuration. Paths only — never secrets."""
    print("hypelab config:")
    for var, value in cfg.as_dict().items():
        print(f"  {var}={value}  [{cfg.sources.get(var, '?')}]")


def startup(env=None) -> HypeLabConfig:
    """Startup hook: resolve, validate, print. Called from the CLI entrypoint."""
    cfg = validate_config(resolve_config(env))
    print_config(cfg)
    return cfg
