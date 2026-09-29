"""Ingest (Book 2, section 5 + 5a).

Ingest order of preference (section 5a):
  1. campaign-supplied or expressly authorized source files first
     (direct file, press kit, creator-provided) — the clean path;
  2. platform-provided download mechanisms where they exist;
  3. yt-dlp on third-party uploads — ONLY with explicit recorded clearance,
     never silently.

require_rights() fails closed: no manifest, or basis == "needs_clearance"
with no recorded clearance, means no download. The content hash
(source_items.content_sha256) proves WHICH bytes were ingested under that
manifest, so a later dispute is about a specific file, not a vague memory.

Ingest writes: work/source.mp4, work/source.words.json (Book 1 align word
timings), work/signals.json (heatmap/comments may be None — the blind path).
"""
from __future__ import annotations

import json
import shutil
import sqlite3
import subprocess
from pathlib import Path

from .util import intake_asset, now, sha256_file

#: Rights bases that authorize a download without further clearance.
CLEAR_BASES = ("campaign_supplied", "platform_mechanism", "explicit_permission")


class RightsError(Exception):
    """Raised when ingest is refused: no manifest or no clearance."""


class IngestError(Exception):
    """Raised when the download/transcribe pipeline itself fails."""


# ------------------------------------------------------------------ rights

def source_for_job(conn: sqlite3.Connection, job_id: str) -> sqlite3.Row:
    row = conn.execute(
        "SELECT s.* FROM sources s "
        "JOIN source_items si ON si.source_id = s.id "
        "WHERE si.job_id = ?",
        (job_id,),
    ).fetchone()
    if row is None:
        # Fall back: the newest source_item for this job (watcher sets
        # job_id only via poll; tests may set it directly).
        row = conn.execute(
            "SELECT s.* FROM sources s WHERE s.id = ("
            " SELECT source_id FROM source_items WHERE job_id=? LIMIT 1)",
            (job_id,),
        ).fetchone()
    if row is None:
        raise RightsError(
            f"job {job_id} has no source_item: cannot establish rights"
        )
    return row


def item_for_job(conn: sqlite3.Connection, job_id: str):
    return conn.execute(
        "SELECT * FROM source_items WHERE job_id=? LIMIT 1", (job_id,)
    ).fetchone()


def get_manifest(source) -> dict:
    raw = source["authorization"]
    if not raw:
        return {}
    try:
        return json.loads(raw)
    except ValueError:
        return {}


def require_rights(conn: sqlite3.Connection, job_id: str) -> dict:
    """Fail closed on the rights manifest. Returns the manifest dict.

    Raises RightsError when:
      - the job has no source / the source has no manifest, or
      - basis == "needs_clearance" and no clearance object is recorded.
    """
    source = source_for_job(conn, job_id)
    manifest = get_manifest(source)
    basis = manifest.get("basis")
    if not basis:
        raise RightsError(
            f"source {source['id']}: no rights manifest recorded — "
            "ingest refused (record one with 'hypelab source add' / clearance)"
        )
    if basis == "needs_clearance" and not manifest.get("clearance"):
        raise RightsError(
            f"source {source['id']}: rights basis is 'needs_clearance' with "
            "no recorded clearance — ingest refused. yt-dlp on third-party "
            "uploads does not run silently; record explicit clearance first."
        )
    if basis not in CLEAR_BASES and basis != "needs_clearance":
        raise RightsError(
            f"source {source['id']}: unknown rights basis {basis!r} — "
            "ingest refused"
        )
    return manifest


# ------------------------------------------------------------------ download

def ytdlp_json(url: str, comments: bool = True) -> dict:
    """Full yt-dlp metadata JSON for a URL. NETWORK. Not exercised in tests."""
    cmd = ["yt-dlp", "--dump-json"]
    if not comments:
        cmd.append("--no-comments")
    cmd.append(url)
    try:
        proc = subprocess.run(
            cmd, capture_output=True, text=True, timeout=300, shell=False
        )
    except FileNotFoundError as e:
        raise IngestError(f"yt-dlp binary not found: {e}")
    if proc.returncode != 0:
        raise IngestError(
            f"yt-dlp metadata failed: {proc.stderr.strip()[:300]}"
        )
    try:
        return json.loads(proc.stdout)
    except ValueError as e:
        raise IngestError(f"yt-dlp returned non-JSON metadata: {e}")


def ytdlp_download(url: str, out_path: Path) -> None:
    """Download ≤1080p mp4 via yt-dlp. NETWORK. Only runs after
    require_rights() passed — never silently."""
    cmd = [
        "yt-dlp", "-f", "bv*[height<=1080]+ba/b",
        "--merge-output-format", "mp4",
        "-o", str(out_path), url,
    ]
    proc = subprocess.run(
        cmd, capture_output=True, text=True, timeout=7200, shell=False
    )
    if proc.returncode != 0:
        raise IngestError(
            f"yt-dlp download failed: {proc.stderr.strip()[-500:]}"
        )


def _run(cmd: list[str], what: str) -> subprocess.CompletedProcess:
    """Validated argv array only: plain non-empty strings, never shell=True."""
    for a in cmd:
        if not isinstance(a, str) or not a:
            raise IngestError(f"invalid argv element for {what}: {a!r}")
    try:
        proc = subprocess.run(
            cmd, capture_output=True, text=True, timeout=3600, shell=False
        )
    except FileNotFoundError as e:
        raise IngestError(f"binary not found for {what}: {e}")
    if proc.returncode != 0:
        raise IngestError(f"{what} failed: {proc.stderr.strip()[-500:]}")
    return proc


# ------------------------------------------------------------------ ingest

def _fixture_item_info(source, item) -> tuple[dict | None, dict | None]:
    """For kind=manual sources, re-read the listing file to find this item's
    info (chapters/heatmap/comments) and fixture word timings.

    Returns (info_dict_or_None, words_list_or_None). Production kinds ignore
    fixture sidecars entirely."""
    if source["kind"] != "manual":
        return None, None
    try:
        listing = json.loads(Path(source["url"]).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None, None
    for it in listing.get("items", []):
        if str(it.get("id")) == str(item["id"]):
            info = None
            words = None
            if it.get("info_path"):
                try:
                    info = json.loads(
                        Path(it["info_path"]).read_text(encoding="utf-8"))
                except (OSError, ValueError):
                    info = None
            if it.get("words_path"):
                try:
                    doc = json.loads(
                        Path(it["words_path"]).read_text(encoding="utf-8"))
                    words = doc.get("words") if isinstance(doc, dict) else doc
                except (OSError, ValueError):
                    words = None
            return info, words
    return None, None


def _transcribe_words(source_mp4: Path, work: Path, asr_cfg=None) -> list[dict]:
    """Book 1 align path: 16 kHz mono (all Whisper uses) -> word timings."""
    from . import align as align_mod

    wav = work / "tmp_16k.wav"
    _run([
        "ffmpeg", "-y", "-v", "error", "-i", str(source_mp4),
        "-ar", "16000", "-ac", "1", "-c:a", "pcm_s16le", str(wav),
    ], "16k mono extraction")
    try:
        doc = align_mod.transcribe(str(wav), asr_cfg=asr_cfg)
    finally:
        try:
            wav.unlink()
        except OSError:
            pass
    words = doc.get("words") or []
    if not words:
        raise IngestError("transcription produced no words")
    return words


def ingest(conn: sqlite3.Connection, job_id: str, work,
           asr_cfg=None) -> dict:
    """Ingest a job's source: rights gate -> bytes -> hash -> words -> signals.

    ``work`` is the job's work dir. Writes source.mp4, source.words.json,
    signals.json. Updates source_items.content_sha256. Returns the signals
    dict.

    Fixture path (tests/acceptance only): kind=manual sources whose listing
    carries words_path/info_path sidecars use those instead of the network
    and the ASR model. Production kinds (yt_channel/rss) use yt-dlp metadata
    and Book 1 transcription.
    """
    from . import signals as signals_mod

    work = Path(work)
    work.mkdir(parents=True, exist_ok=True)
    manifest = require_rights(conn, job_id)
    source = source_for_job(conn, job_id)
    item = item_for_job(conn, job_id)
    if item is None:
        raise IngestError(f"job {job_id} has no source_items row")

    url = item["url"]
    dest = work / "source.mp4"
    info = None
    fixture_words = None

    if source["kind"] == "manual" and url and Path(url).is_file():
        # Campaign-supplied file (preference 1 in §5a): local intake, no
        # network. The rights manifest documents the grant.
        entry = intake_asset(url, work, "source.mp4")
        dest = Path(entry["path"])
        info, fixture_words = _fixture_item_info(source, item)
    elif manifest.get("basis") in CLEAR_BASES and url.startswith("http"):
        # yt-dlp only runs here — after an explicit rights basis, never
        # silently (preference 3 in §5a).
        info = ytdlp_json(url, comments=True)
        ytdlp_download(url, dest)
    else:
        raise IngestError(
            f"no ingest path for source kind={source['kind']} "
            f"basis={manifest.get('basis')}"
        )

    if not dest.is_file():
        raise IngestError(f"ingest produced no file at {dest}")

    sha = sha256_file(dest)
    conn.execute(
        "UPDATE source_items SET content_sha256=?, job_id=? WHERE id=?",
        (sha, job_id, item["id"]),
    )

    if fixture_words is not None:
        words = fixture_words
        words_doc = {"words": words, "n_words": len(words),
                     "timing": "fixture", "model": "fixture"}
    else:
        words = _transcribe_words(dest, work, asr_cfg=asr_cfg)
        words_doc = {"words": words, "n_words": len(words),
                     "timing": "asr_approximate", "model": "faster-whisper"}

    (work / "source.words.json").write_text(
        json.dumps(words_doc, indent=2), encoding="utf-8"
    )

    signals = {
        "heatmap": signals_mod.extract_heatmap(info),
        "comments": signals_mod.comment_timestamps(info),
        "duration": (info or {}).get("duration"),
        "chapters": (info or {}).get("chapters") or [],
        "audio_provenance": manifest.get("audio_provenance", "unknown"),
        "tier3_source": "fixture" if info is not None and
        source["kind"] == "manual" else ("ytdlp" if info else None),
    }
    if signals["duration"] is None:
        # Fall back to probing the file; never invent a duration.
        try:
            from .util import ffprobe as _ffprobe

            signals["duration"] = _ffprobe(dest)["duration_s"]
        except Exception:
            signals["duration"] = 0.0
    (work / "signals.json").write_text(
        json.dumps(signals, indent=2), encoding="utf-8"
    )
    return signals
