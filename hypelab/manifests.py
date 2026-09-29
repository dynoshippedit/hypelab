"""Content-addressed asset manifests (Book 1 improved, section 6).

Every render input is identified by its SHA-256 content hash — never by
size+mtime (that is a cache key, not an identity). This module owns:

- ``sha256_file`` — streamed hex SHA-256 of a file (re-export of the
  util.py implementation; the single implementation lives there).
- ``render_hash(edl, inputs, provenance)`` — 32 hex chars binding the
  canonical EDL JSON + the SHA-256 of every input file + the tool/model
  provenance to one fingerprint. Any caption-character change, input-byte
  change, or provenance change flips the hash.
- ``provenance(kit)`` — ``{ffmpeg, libass, asr, hypelab}`` tool record.
- ``attach_asset`` — atomic intake of a file into ``work/<job_id>/assets/``
  plus a ``manifest.json`` entry; out-of-band hash mismatch quarantines
  the file and raises (fail closed).
- ``record_render`` — appends a render entry to ``manifest.json``.
- ``verify_manifest`` — re-hashes every manifest asset; raises
  ``ManifestError`` on any mismatch. Called by ``render.build_command``
  before any ffmpeg argv is built.
"""
from __future__ import annotations

import hashlib
import json
import secrets
import subprocess
from functools import lru_cache
from pathlib import Path

from . import HYPELAB_VERSION
from .util import now, sha256_file  # noqa: F401  (re-exported API)

__all__ = [
    "ManifestError",
    "sha256_file",
    "render_hash",
    "provenance",
    "attach_asset",
    "record_render",
    "verify_manifest",
]


class ManifestError(Exception):
    """Raised when a manifest is missing, malformed, or fails verification.

    Fail closed: a hash mismatch quarantines the asset and aborts the
    operation — it never silently proceeds.
    """


# ------------------------------------------------------------------ hashing

def _canonical(obj) -> bytes:
    """Canonical JSON bytes: sorted keys, compact separators."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":")).encode("utf-8")


def render_hash(edl: dict, inputs, provenance: dict) -> str:
    """Bind an EDL to its input bytes and tool provenance.

    ``sha256(canonical(edl) + canonical(provenance) + sha256(each input))``,
    first 32 hex chars. Deterministic: identical EDL + inputs + provenance
    always yield the identical hash.
    """
    h = hashlib.sha256()
    h.update(b"edl\x00")
    h.update(_canonical(edl))
    h.update(b"\x00provenance\x00")
    h.update(_canonical(provenance or {}))
    # Content-addressed: only the sorted input digests feed the hash.
    # Paths are identity, not content — two checkouts of the same bytes
    # must hash the same.
    for digest in sorted(sha256_file(p) for p in (inputs or [])):
        h.update(b"\x00input\x00" + bytes.fromhex(digest))
    return h.hexdigest()[:32]


# ---------------------------------------------------------------- provenance

@lru_cache(maxsize=1)
def _ffmpeg_version() -> str:
    try:
        p = subprocess.run(
            ["ffmpeg", "-version"], capture_output=True, text=True,
            timeout=30, shell=False,
        )
        line = (p.stdout or "").splitlines()
        if p.returncode == 0 and line:
            return line[0].strip()
    except (OSError, subprocess.TimeoutExpired):
        pass
    return "unknown"


@lru_cache(maxsize=1)
def _libass_version() -> str:
    """libass version via pkg-config; 'unknown' when not discoverable.

    Never fabricated: when the build metadata is absent we say so.
    """
    for cmd in (["pkg-config", "--modversion", "libass"],
                ["pkgconf", "--modversion", "libass"]):
        try:
            p = subprocess.run(
                cmd, capture_output=True, text=True, timeout=15, shell=False,
            )
            if p.returncode == 0 and p.stdout.strip():
                return p.stdout.strip()
        except (OSError, subprocess.TimeoutExpired):
            continue
    return "unknown"


def provenance(kit: dict | None = None) -> dict:
    """Tool/model provenance record: ``{ffmpeg, libass, asr, hypelab}``.

    ``kit`` supplies the ``asr`` block when available; without a kit the
    asr entry is ``"not-recorded"`` (never invented).
    """
    asr = (kit or {}).get("asr") if isinstance(kit, dict) else None
    return {
        "ffmpeg": _ffmpeg_version(),
        "libass": _libass_version(),
        "asr": asr if asr is not None else "not-recorded",
        "hypelab": HYPELAB_VERSION,
    }


# ---------------------------------------------------------------- manifest IO

def _manifest_path(work) -> Path:
    return Path(work) / "manifest.json"


def _read_manifest(work) -> dict:
    """Read manifest.json; return the blank shape when absent.

    Raises ManifestError on malformed JSON (fail closed).
    """
    mp = _manifest_path(work)
    if not mp.exists():
        return {"assets": {}, "renders": [], "quarantined": [],
                "measurements": []}
    try:
        data = json.loads(mp.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        raise ManifestError(f"manifest.json unreadable: {e}") from e
    if not isinstance(data, dict):
        raise ManifestError("manifest.json is not a JSON object")
    data.setdefault("assets", {})
    data.setdefault("renders", [])
    data.setdefault("quarantined", [])
    data.setdefault("measurements", [])
    return data


def _write_manifest(work, data: dict) -> None:
    """Write manifest.json atomically: tmp + fsync + os.replace."""
    import os

    mp = _manifest_path(work)
    mp.parent.mkdir(parents=True, exist_ok=True)
    tmp = mp.with_name(f".tmp.manifest.{secrets.token_hex(8)}.json")
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(json.dumps(data, indent=2, sort_keys=True))
            f.write("\n")
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, mp)
    finally:
        try:
            if tmp.exists():
                tmp.unlink()
        except OSError:
            pass


# ---------------------------------------------------------------- attach

def _video_codec(path: Path) -> str | None:
    try:
        p = subprocess.run(
            ["ffprobe", "-v", "error", "-select_streams", "v:0",
             "-show_entries", "stream=codec_name", "-of",
             "default=noprint_wrappers=1:nokey=1", str(path)],
            capture_output=True, text=True, timeout=60, shell=False,
        )
        out = (p.stdout or "").strip()
        return out or None
    except (OSError, subprocess.TimeoutExpired):
        return None


def _audio_probe(path: Path) -> dict:
    """Best-effort probe for audio-only assets (video fields stay None)."""
    from .util import MediaError

    p = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "a:0",
         "-show_entries", "stream=codec_name:format=duration",
         "-of", "json", str(path)],
        capture_output=True, text=True, timeout=60, shell=False,
    )
    if p.returncode != 0:
        raise MediaError(f"ffprobe failed on {path}: {p.stderr.strip()[:200]}")
    try:
        info = json.loads(p.stdout)
    except json.JSONDecodeError as e:
        raise MediaError(f"ffprobe returned non-JSON for {path}: {e}") from e
    streams = info.get("streams") or []
    if not streams:
        raise MediaError(f"no audio stream in {path}")
    dur = (info.get("format") or {}).get("duration")
    return {
        "duration_s": float(dur) if dur is not None else None,
        "codec": streams[0].get("codec_name"),
    }


def _quarantine(work: Path, name: str, src: Path,
                expected_sha256: str, actual_sha256: str) -> dict:
    """Move ``src`` to ``work/quarantine/`` and log the quarantine event.

    Returns the quarantine record appended to ``manifest.json``.
    """
    qdir = work / "quarantine"
    qdir.mkdir(parents=True, exist_ok=True)
    qname = name
    i = 0
    while (qdir / qname).exists():
        i += 1
        qname = f"{name}.quarantined-{i}"
    src.rename(qdir / qname)
    data = _read_manifest(work)
    record = {
        "name": name,
        "quarantined_as": qname,
        "expected_sha256": expected_sha256.lower(),
        "actual_sha256": actual_sha256,
        "at": now(),
    }
    data["quarantined"].append(record)
    _write_manifest(work, data)
    return record


def attach_asset(src, work, name: str, expected_sha256: str | None = None) -> dict:
    """Atomically attach a file as a job asset.

    The file is intaken (tmp + fsync + atomic rename) into
    ``work/assets/<name>``, probed, and recorded in ``manifest.json``
    under ``assets[name]`` with
    ``{name, sha256, bytes, duration_s, w, h, fps, sar, codec}``.

    When ``expected_sha256`` is given and the intaken bytes do not match,
    the file is moved to ``work/quarantine/`` and ``ManifestError`` is
    raised — the mismatch is quarantined, never attached.
    """
    from . import util as _util

    work = Path(work)
    if Path(name).name != str(name):
        raise ValueError(f"unsafe asset name: {name!r}")
    assets = work / "assets"
    rec = _util.intake_asset(src, assets, name)
    actual = rec["sha256"]
    dest = assets / name

    if expected_sha256 is not None and expected_sha256.lower() != actual.lower():
        _quarantine(work, name, dest, expected_sha256, actual)
        raise ManifestError(
            f"out-of-band mismatch for {name}: expected "
            f"{expected_sha256[:16]}..., got {actual[:16]}... — quarantined"
        )

    try:
        probe = _util.ffprobe(dest)
        entry = {
            "name": name,
            "sha256": actual,
            "bytes": rec["bytes"],
            "duration_s": probe["duration_s"],
            "w": probe["width"],
            "h": probe["height"],
            "fps": probe["fps"],
            "sar": probe["sar"],
            "codec": _video_codec(dest),
        }
    except _util.MediaError as video_err:
        # Audio-only assets have no video stream: record what exists.
        try:
            aprobe = _audio_probe(dest)
        except _util.MediaError:
            raise video_err
        entry = {
            "name": name,
            "sha256": actual,
            "bytes": rec["bytes"],
            "duration_s": aprobe["duration_s"],
            "w": None,
            "h": None,
            "fps": None,
            "sar": None,
            "codec": aprobe["codec"],
        }
    data = _read_manifest(work)
    data["assets"][name] = entry
    _write_manifest(work, data)
    return entry


# ---------------------------------------------------------------- render log

def record_render(work, entry: dict) -> dict:
    """Append a render entry to ``manifest.json``'s ``renders`` list.

    Entry shape: ``{render_hash, provenance, ffmpeg_argv, started_at,
    finished_at, input_hashes}``.
    """
    data = _read_manifest(work)
    data["renders"].append(dict(entry))
    _write_manifest(work, data)
    return entry


def record_measurement(work, name: str, measurement: dict) -> dict:
    """Append a gate measurement to ``manifest.json``'s ``measurements``.

    Used for values the spec wants in the manifest alongside the render
    entry — e.g. the loudness gate's measured integrated LUFS plus the
    renderer's loudnorm parameters. Additive; never rewrites history.
    """
    data = _read_manifest(work)
    record = {"name": name, "at": now(), **dict(measurement)}
    data["measurements"].append(record)
    _write_manifest(work, data)
    return record


# ------------------------------------------------------------------ verify

def verify_manifest(work) -> dict | None:
    """Re-hash every manifest asset; raise ManifestError on any mismatch.

    A tampered asset (hash mismatch vs the manifest) is QUARANTINED: the
    file is moved to ``work/quarantine/``, the quarantine is logged in
    ``manifest.json``, the asset entry is dropped, and ManifestError is
    raised — fail closed, never render from suspect bytes.

    Returns the manifest dict. A missing ``manifest.json`` means nothing
    has been attached yet — returns ``None`` (nothing to verify).
    Called by ``render.build_command`` before any ffmpeg argv is built.
    """
    work = Path(work)
    mp = _manifest_path(work)
    if not mp.exists():
        return None
    data = _read_manifest(work)
    assets = data.get("assets") or {}
    if not isinstance(assets, dict):
        raise ManifestError("manifest.json 'assets' is not an object")
    for name, entry in assets.items():
        if not isinstance(entry, dict) or "sha256" not in entry:
            raise ManifestError(f"manifest asset {name!r}: malformed entry")
        p = work / "assets" / name
        if not p.is_file():
            raise ManifestError(f"manifest asset missing on disk: {name}")
        actual = sha256_file(p)
        if actual.lower() != str(entry["sha256"]).lower():
            expected = str(entry["sha256"])
            _quarantine(work, name, p, expected, actual)
            data = _read_manifest(work)
            data["assets"].pop(name, None)
            _write_manifest(work, data)
            raise ManifestError(
                f"manifest hash mismatch for {name}: manifest "
                f"{expected[:16]}... != disk {actual[:16]}... — quarantined"
            )
    return data
