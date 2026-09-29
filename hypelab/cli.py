#!/usr/bin/env python3
"""HypeLab CLI — the only front door (Book 1 improved, section 12).

Invoke:
    python3 -m hypelab.cli <command> [args]
    hypelab <command> [args]          # via the /home/dino/.local/bin/hypelab shim

This module supersedes the old argparse CLI (the previous cli.py), worker.py,
tasks_lab.py and services.py.  None of those are imported here.

Write domains (improved Book 1, section 1):
    work/<job_id>/   job artifacts — atomic tmp -> fsync -> rename only
    hypelab.db       state & ledger — only via jobs/queue ops
    models/, ~/.cache  read-mostly model caches
    work/<job_id>/tmp/ temp files
    kits/, user media  READ ONLY (never written by this CLI)

Test isolation (no landed-module changes needed):
    HYPELAB_DB             sqlite path (default: the repo hypelab.db)
    HYPELAB_ROOT           repo root used for work/ dirs (default: /home/dino/hypelab)
    HYPELAB_LEASE_SECONDS  worker lease seconds (default 1800; tests use a short one)
"""

import copy
import json
import os
import re
import socket
import sqlite3
import sys
import threading
import time
from pathlib import Path

import click

from hypelab import align as align_mod
from hypelab import db as db_mod
from hypelab import edl as edl_mod
from hypelab import gates as gates_mod
from hypelab import jobs as jobs_mod
from hypelab import kits as kits_mod
from hypelab import manifests as manifests_mod
from hypelab import queue as queue_mod
from hypelab import render as render_mod


# Book 2: versioned scoring weights live next to the package.
_WEIGHTS_DIR = Path(__file__).resolve().parent / "weights"
from hypelab import script as script_mod
from hypelab import util as util_mod

DEFAULT_ROOT = "/home/dino/hypelab"
FPS = 30
ASPECT_DIMS = {
    "9:16": (1080, 1920),
    "1:1": (1080, 1080),
    "16:9": (1920, 1080),
}
# The seven Book 1 section-11 gates, in book order.  The landed gates.run_all
# also evaluates an eighth gate (word_confidence); the table below prints only
# the seven the book mandates, while the ready|gate_failed routing still
# considers every gate run_all reports (defense in depth: word confidence is
# enforced at align time, so a failure here means something regressed).
BOOK7_GATES = [
    "duration",
    "loudness",
    "first_frame",
    "hook_budget",
    "caption_safe",
    "slots_filled",
    "geometry",
]


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------

def _die(msg, code=1):
    """Print an error to stderr and exit nonzero (Click-friendly)."""
    print(f"error: {msg}", file=sys.stderr)
    raise SystemExit(code)


def _repo_root():
    return os.environ.get("HYPELAB_ROOT", DEFAULT_ROOT)


def _conn():
    return db_mod.connect(os.environ.get("HYPELAB_DB") or None)


def _lease_seconds():
    return queue_mod.LEASE_TTL_S


# Test-only lease override.  queue.py hardcodes LEASE_TTL_S = 1800; the
# crash-recovery test needs a short lease without waiting 30 minutes.
# Setting HYPELAB_LEASE_SECONDS reconfigures the queue module for this
# process only; the 1800s default is untouched when the variable is absent.
try:
    _lease_override = int(os.environ.get("HYPELAB_LEASE_SECONDS", "") or 0)
except ValueError:
    _lease_override = 0
if _lease_override > 0:
    queue_mod.LEASE_TTL_S = _lease_override


def _work_dir(job_id):
    return util_mod.work_dir(job_id, root=_repo_root())


def _edl_path(work):
    return Path(work) / "render.json"


def _load_edl(work):
    p = _edl_path(work)
    if not p.is_file():
        _die(f"no EDL at {p} (run 'hypelab new' first)")
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        _die(f"cannot read EDL at {p}: {e}")


def _save_edl(work, edl):
    # Atomic tmp -> fsync -> rename; never a partial render.json.
    util_mod.write_json(_edl_path(work), edl)


def _write_text_atomic(path, text):
    tmp = Path(str(path) + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    with open(tmp, "rb") as f:
        os.fsync(f.fileno())
    d = os.open(str(tmp.parent), os.O_DIRECTORY)
    try:
        os.rename(tmp, path)
        os.fsync(d)
    finally:
        os.close(d)


def _get_job(conn, job_id):
    row = jobs_mod.get(conn, job_id)
    if row is None:
        _die(f"unknown job {job_id!r}")
    return row


def _get_kit(conn, job):
    try:
        return kits_mod.load(conn, job["kit_id"], job["kit_version"])
    except KeyError as e:
        _die(str(e))


def _transition(conn, job_id, to, note=None):
    try:
        jobs_mod.transition(conn, job_id, to, note=note)
    except ValueError as e:
        _die(str(e))
    print(f"  state -> {to}" + (f" ({note})" if note else ""))


# ---------------------------------------------------------------------------
# Number normalization for forced alignment.
#
# The local wav2vec2 vocabulary has no digits, so any digits in the script
# would make align_words raise AlignError.  Normalize integers, decimals,
# years and percentages to words first.  Normalization EXPANDS the word
# stream, so beat lines used for retiming must be the normalized text too
# (handled in _do_align).
# ---------------------------------------------------------------------------

_ONES = [
    "zero", "one", "two", "three", "four", "five", "six", "seven", "eight",
    "nine", "ten", "eleven", "twelve", "thirteen", "fourteen", "fifteen",
    "sixteen", "seventeen", "eighteen", "nineteen",
]
_TENS = [
    "", "", "twenty", "thirty", "forty", "fifty", "sixty", "seventy",
    "eighty", "ninety",
]


def _int_to_words(n: int) -> str:
    if n < 0:
        return "minus " + _int_to_words(-n)
    if n < 20:
        return _ONES[n]
    if n < 100:
        return _TENS[n // 10] + ("" if n % 10 == 0 else " " + _ONES[n % 10])
    if n < 1000:
        rem = n % 100
        return _ONES[n // 100] + " hundred" + ("" if rem == 0 else " " + _int_to_words(rem))
    if n < 1_000_000:
        hi, rem = divmod(n, 1000)
        return _int_to_words(hi) + " thousand" + ("" if rem == 0 else " " + _int_to_words(rem))
    if n < 1_000_000_000:
        hi, rem = divmod(n, 1_000_000)
        return _int_to_words(hi) + " million" + ("" if rem == 0 else " " + _int_to_words(rem))
    hi, rem = divmod(n, 1_000_000_000)
    return _int_to_words(hi) + " billion" + ("" if rem == 0 else " " + _int_to_words(rem))


def _year_to_words(tok: str) -> str:
    y = int(tok)
    if y < 1000:
        return _int_to_words(y)
    if y % 100 == 0:
        if y < 2000:
            return _int_to_words(y // 100) + " hundred"  # 1900 -> nineteen hundred
        return _int_to_words(y)  # 2000 -> two thousand
    if 2000 <= y < 2010:
        return "two thousand " + _ONES[y % 10]  # 2005 -> two thousand five
    if y < 2000:
        # 1999 -> nineteen ninety nine; 1066 -> ten sixty six
        return _int_to_words(y // 100) + " " + _int_to_words(y % 100)
    return _int_to_words(y)  # 2015 -> two thousand fifteen


def _num_words(tok: str, allow_year: bool = True) -> str:
    if "." in tok:
        ip, _, fp = tok.partition(".")
        return _int_to_words(int(ip)) + " point" + "".join(
            " " + _ONES[int(d)] for d in fp
        )
    n = int(tok)
    if allow_year and len(tok) == 4 and 1000 <= n <= 2099:
        return _year_to_words(tok)
    return _int_to_words(n)


_NUM_RE = re.compile(
    r"(?P<pct>\d[\d,]*(?:\.\d+)?\s*%)"  # 12% / 12.5 %
    r"|(?P<num>\d[\d,]*(?:\.\d+)?)"     # 3 / 42 / 1,999 / 3.14 / 1999
)


def normalize_numbers(text: str) -> str:
    """Spell out integers, decimals, years and percentages as words.

    A thousands separator forces cardinal reading ("1,999" -> "one thousand
    nine hundred ninety nine", never a year).  Percentages always read as
    cardinals ("12%" -> "twelve percent").
    """
    def _sub(m):
        if m.group("pct") is not None:
            tok = m.group("pct").replace("%", "").strip().replace(",", "")
            return _num_words(tok, allow_year=False) + " percent"
        raw = m.group("num")
        return _num_words(raw.replace(",", ""), allow_year=("," not in raw))

    return _NUM_RE.sub(_sub, text)


# ---------------------------------------------------------------------------
# Alignment core (shared by `hypelab audio` and the `hypelab work` handler)
# ---------------------------------------------------------------------------

def _do_align(conn, job_id, kit, work, edl):
    """Force-align the VO to the (number-normalized) script.

    Writes work/vo.words.json atomically (tmp -> rename) — the location the
    word_confidence gate reads — retimes beats to the aligned word stream, forces beat contiguity, stores the aligned words
    on captions.words, and saves the EDL atomically.

    Returns (words_doc, flagged) where flagged is a list of
    {"beat_id","line","min_word_p"} for beats whose mean word probability is
    below the kit threshold (the book's low-confidence rule, section 10).
    """
    beats = edl["beats"]
    if not beats:
        raise align_mod.AlignError("EDL has no beats")

    # Normalize numbers FIRST: wav2vec2 has no digits, and normalization
    # expands the word stream, so the retimer must see normalized lines.
    norm_lines = [normalize_numbers(str(b.get("line") or "")) for b in beats]
    norm_text = "\n".join(norm_lines)

    tmpdir = Path(work) / "tmp"
    tmpdir.mkdir(parents=True, exist_ok=True)
    norm_path = tmpdir / "script_normalized.txt"
    _write_text_atomic(norm_path, norm_text)

    vo_node = (edl.get("audio") or {}).get("vo") or {}
    vo_path = vo_node.get("path") or str(Path(work) / "assets" / "vo.mp3")

    words_tmp = tmpdir / "vo.words.json.tmp"
    words_final = Path(work) / "vo.words.json"  # gate reads work/vo.words.json
    asr_cfg = kit.get("asr") or {}
    doc = align_mod.align_words(
        vo_path, words_tmp, script_path=str(norm_path),
        asr_cfg=asr_cfg, language="en",
    )
    os.replace(words_tmp, words_final)  # atomic publish

    # Retime against the NORMALIZED beats, then force contiguity: the
    # retimer's zero-gap guarantee is best-effort, so pin t_in explicitly.
    norm_beats = [dict(b, line=nl) for b, nl in zip(beats, norm_lines)]
    retimed = align_mod.retime_beats(norm_beats, doc["words"])
    prev_out = 0.0
    for b, rb in zip(beats, retimed):
        t_in = prev_out
        t_out = float(rb["t_out"])
        if not t_out > t_in:  # never a zero/negative beat
            t_out = t_in + 0.04
        b["t_in"], b["t_out"] = t_in, t_out
        prev_out = t_out

    edl["captions"]["words"] = doc["words"]
    _save_edl(work, edl)

    # Low-confidence rule: MEAN word probability per beat (book section 10).
    # (landed low_confidence_beats uses the minimum; the book mandates the
    # mean, so compute it here explicitly.)
    thresh = float(kit.get("min_word_prob", 0.5))
    by_beat = align_mod.low_confidence_beats(doc, retimed, min_word_prob=0.0)
    flagged = []
    for entry, rb in zip(by_beat, retimed):
        words = [
            w for w in doc["words"]
            if w["t0"] >= rb["t_in"] - 1e-6 and w["t1"] <= rb["t_out"] + 1e-6
        ]
        probs = [w.get("p", 0.0) for w in words]
        mean_p = sum(probs) / len(probs) if probs else 0.0
        if mean_p < thresh:
            flagged.append({
                "beat_id": entry["beat_id"],
                "line": entry["line"],
                "mean_word_p": round(mean_p, 4),
            })
    return doc, flagged


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

@click.group()
def cli():
    """HypeLab — the only front door (Book 1)."""


@cli.command()
def migrate():
    """Apply pending migrations and print applied versions."""
    conn = _conn()
    try:
        rows = conn.execute(
            "SELECT version, name, applied_at FROM schema_migrations ORDER BY version"
        ).fetchall()
    except sqlite3.Error as e:
        _die(f"cannot read migration state: {e}")
    for r in rows:
        print(f"v{r['version']}  {r['name']}  ({r['applied_at']})")
    print(f"{len(rows)} migration(s) applied")


@cli.group()
def kit():
    """Brand kit commands."""


@kit.command("new")
@click.argument("kit_id")
@click.option("--from", "from_path", required=True,
              type=click.Path(exists=True, dir_okay=False),
              help="Path to the kit JSON to adapt and seed.")
def kit_new(kit_id, from_path):
    """Adapt a kit JSON and seed it as immutable v1 (fails cleanly if it exists)."""
    conn = _conn()
    try:
        raw = json.loads(Path(from_path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        _die(f"cannot read kit JSON: {e}")
    if not isinstance(raw, dict):
        _die("kit JSON must be an object")
    data = raw
    if not all(k in raw for k in ("generator", "asr", "captions", "audio")):
        # Shipped kits/ JSON is adapted, never mutated on disk.
        data = kits_mod._adapt_cerebratico(raw)
    try:
        version = kits_mod.seed(conn, kit_id, data)
    except ValueError as e:
        _die(str(e))
    print(f"kit {kit_id} seeded at v{version}")


@cli.command()
@click.option("--kit", "kit_id", required=True, help="Kit id (must already be seeded).")
@click.option("--script", "script_path", required=True,
              type=click.Path(exists=True, dir_okay=False))
@click.option("--aspect", type=click.Choice(sorted(ASPECT_DIMS)), default="9:16",
              show_default=True)
@click.option("--max-s", "max_s", type=float, default=45.0, show_default=True)
@click.option("--title", default=None)
def new(kit_id, script_path, aspect, max_s, title):
    """Create a job: pin kit version, save script + EDL atomically, beat-split."""
    conn = _conn()
    try:
        kit = kits_mod.load(conn, kit_id)
    except KeyError:
        _die(f"kit {kit_id!r} not found (run 'hypelab kit new' first)")

    try:
        text = Path(script_path).read_text(encoding="utf-8")
    except OSError as e:
        _die(f"cannot read script: {e}")
    if not text.strip():
        _die("script is empty")

    w, h = ASPECT_DIMS[aspect]
    target = {
        "aspect": aspect,
        "w": w,
        "h": h,
        "fps": FPS,
        "max_duration_s": float(max_s),
        "loudness_lufs": float((kit.get("audio") or {}).get("loudness_lufs", -16.0)),
    }
    try:
        beats_in = script_mod.to_beats(text, kit, float(max_s))
    except ValueError as e:
        _die(str(e))

    beats = []
    for b in beats_in:
        bb = dict(b)
        # build_edl defaults clip_in but not clip_fit; the schema requires it.
        bb.setdefault("clip_fit", "cover")
        bb.setdefault("clip_in", 0.0)
        beats.append(bb)

    edl = edl_mod.build_edl(
        mode="original",
        kit_ref=f"{kit_id}@{kit['version']}",
        target=target,
        beats=beats,
        audio={"vo": None, "music": None},
        captions=dict(kit.get("captions") or {}),
        overlays=[],
        min_word_prob=float(kit.get("min_word_prob", 0.5)),
    )
    try:
        edl_mod.validate(edl)
    except edl_mod.EDLError as e:
        _die(str(e))

    job_id = jobs_mod.new(
        conn, mode="original", kit_id=kit_id, kit_version=kit["version"],
        title=title or Path(script_path).stem,
    )
    work = _work_dir(job_id)
    _save_edl(work, edl)
    _write_text_atomic(_edl_path(work).parent / "script.txt", text)
    _transition(conn, job_id, "scripted",
                f"{len(beats)} beats from {Path(script_path).name}")
    print(f"job {job_id}")
    print(f"{len(beats)} beats")


@cli.command()
@click.argument("job_id")
def shots(job_id):
    """Print numbered, paste-ready shot prompts for every beat."""
    conn = _conn()
    job = _get_job(conn, job_id)
    kit = _get_kit(conn, job)
    edl = _load_edl(_work_dir(job_id))
    beats = edl["beats"]

    gen = kit.get("generator") or {}
    prefix = (gen.get("prompt_prefix") or "").strip()
    suffix = (gen.get("prompt_suffix") or "").strip()
    appearance = kit.get("appearance", "")
    never = ", ".join((kit.get("guardrails") or {}).get("never", []))
    # kits/ is read-only: report the reference-image field as-is (the shipped
    # cerebratico kit leaves it null — say so instead of inventing a path).
    ref = kit.get("reference_image") or "none configured"

    n = len(beats)
    for i, b in enumerate(beats, 1):
        dur = b["t_out"] - b["t_in"]
        prompt = " ".join(
            p for p in [prefix, str(b.get("line") or "").strip(), suffix] if p
        )
        print(f"[{i}/{n}] beat {b['id']} · {b.get('role')} · "
              f"{b['t_in']:.3f}s–{b['t_out']:.3f}s ({dur:.2f}s)")
        print(f"  line: {b.get('line', '')}")
        print(f"  prompt: {prompt}")
        if appearance:
            print(f"  style: {appearance}")
        if never:
            print(f"  never: {never}")
        print(f"  reference_image: {ref}")
        print(f"  attach with: hypelab attach {job_id} {b['id']} <file>")
        print()


@cli.command()
@click.argument("job_id")
@click.argument("beat_id")
@click.argument("src", type=click.Path(exists=True, dir_okay=False))
def attach(job_id, beat_id, src):
    """Attach a clip to a beat (atomic, manifest-verified). Prints the SHA-256."""
    conn = _conn()
    job = _get_job(conn, job_id)
    if job["state"] not in ("scripted", "awaiting_media", "gate_failed"):
        _die(f"cannot attach in state {job['state']!r}")

    work = _work_dir(job_id)
    edl = _load_edl(work)
    beat = next((b for b in edl["beats"] if b.get("id") == beat_id), None)
    if beat is None:
        _die(f"unknown beat {beat_id!r} "
             f"(beats: {', '.join(b.get('id', '?') for b in edl['beats'])})")

    name = f"{beat_id}.mp4"
    try:
        entry = manifests_mod.attach_asset(src, work, name)
    except (manifests_mod.ManifestError, util_mod.MediaError,
            util_mod.IntegrityError) as e:
        _die(str(e))

    clip_path = str(Path(work) / "assets" / name)
    # Renderer reads beat["clip"]; gates.check_slots reads clip_slot/clip_path.
    # Carry all three so both agree.
    beat["clip"] = clip_path
    beat["clip_slot"] = beat_id
    beat["clip_path"] = clip_path
    _save_edl(work, edl)

    # Warn if the clip is shorter than the beat needs; never silently pad.
    need = beat["t_out"] - beat["t_in"]
    dur = entry.get("duration_s")
    if dur is None:
        print("warning: could not probe clip duration")
    elif dur < need - 1e-6:
        print(f"warning: clip {dur:.2f}s shorter than beat need {need:.2f}s "
              f"(attached anyway; never silently padded)")

    if job["state"] == "scripted":
        _transition(conn, job_id, "awaiting_media", f"clip attached for {beat_id}")
    elif job["state"] == "gate_failed":
        _transition(conn, job_id, "awaiting_media",
                    f"clip re-attached for {beat_id}")

    print(f"attached {beat_id} -> assets/{name}")
    print(f"sha256: {entry['sha256']}")


@cli.command()
@click.argument("job_id")
@click.option("--vo", "vo_src", required=True,
              type=click.Path(exists=True, dir_okay=False))
@click.option("--music", "music_src", default=None,
              type=click.Path(exists=True, dir_okay=False))
def audio(job_id, vo_src, music_src):
    """Attach VO/music, force-align the script, retime beats.

    Low-confidence beats (mean word probability below the kit threshold)
    route to gate_failed with the reason — never to failed.
    """
    conn = _conn()
    job = _get_job(conn, job_id)
    if job["state"] not in ("scripted", "awaiting_media", "gate_failed"):
        _die(f"cannot run audio in state {job['state']!r}")
    kit = _get_kit(conn, job)
    work = _work_dir(job_id)
    edl = _load_edl(work)

    # 1. Atomic, manifest-verified media attach.
    try:
        vo_entry = manifests_mod.attach_asset(vo_src, work, "vo.mp3")
    except (manifests_mod.ManifestError, util_mod.MediaError,
            util_mod.IntegrityError) as e:
        _die(f"vo attach failed: {e}")
    print(f"vo sha256: {vo_entry['sha256']}")
    music_entry = None
    if music_src:
        try:
            music_entry = manifests_mod.attach_asset(music_src, work, "music.mp3")
        except (manifests_mod.ManifestError, util_mod.MediaError,
                util_mod.IntegrityError) as e:
            _die(f"music attach failed: {e}")
        print(f"music sha256: {music_entry['sha256']}")

    vo_node = {"path": str(Path(work) / "assets" / "vo.mp3"), "src": "vo.mp3"}
    mus_node = None
    if music_entry:
        mus_node = {
            "path": str(Path(work) / "assets" / "music.mp3"),
            "src": "music.mp3",
            "duck_db": float((kit.get("audio") or {}).get("music_duck_db", -12.0)),
        }
    edl["audio"] = {"vo": vo_node, "music": mus_node}
    _save_edl(work, edl)

    # 2. Drive the queue states explicitly (visible in `hypelab work` too).
    state = jobs_mod.get(conn, job_id)["state"]
    if state == "gate_failed":
        _transition(conn, job_id, "awaiting_media", "re-drive after gate failure")
        state = "awaiting_media"
    if state == "scripted":
        _transition(conn, job_id, "awaiting_media", "media attaching")
    _transition(conn, job_id, "queued_align", "VO present")
    _transition(conn, job_id, "aligning", "forced alignment running")

    # 3. Local wav2vec2 forced alignment (words are the normalized tokens).
    try:
        doc, flagged = _do_align(conn, job_id, kit, work, edl)
    except align_mod.AlignError as e:
        # Genuine alignment failure (no speech, script/VO mismatch): this is a
        # processing error, surfaced loudly — not a silent gate pass.
        _die(f"alignment failed: {e}")
    print(f"aligned {doc['n_words']} words "
          f"(timing={doc['timing']}, model={doc['model']}, "
          f"mean_p={doc['mean_confidence']:.3f}, "
          f"min_p={min((w.get('p', 0.0) for w in doc['words']), default=0.0):.3f})")

    # 4. Book section 10: low confidence is a GATE outcome, never a crash.
    if flagged:
        reasons = "; ".join(
            f"{f['beat_id']} mean_p={f['mean_word_p']}" for f in flagged
        )
        _transition(conn, job_id, "gate_failed",
                    f"low word confidence: {reasons}")
        print(f"gate_failed: low-confidence beats: {reasons}")
        return

    _transition(conn, job_id, "aligned", f"{doc['n_words']} words retimed")
    _transition(conn, job_id, "queued_render", "ready to render")


def _retarget_edl(edl, aspect):
    """Return a copy of the EDL retargeted to another aspect (not persisted)."""
    w, h = ASPECT_DIMS[aspect]
    ed = copy.deepcopy(edl)
    ed["target"] = {**ed["target"], "aspect": aspect, "w": w, "h": h}
    return ed


# States from which `hypelab render` may run.  queued_render is the normal
# entry; the post-render states exist so the command is idempotent
# ("hash unchanged, skipping") and so --aspect variants can be rendered
# after the book-aspect output.
RENDER_ENTRY_STATES = (
    "queued_render", "rendered", "queued_gates", "ready", "gate_failed",
)


def _render_job(conn, job_id, aspect=None, heartbeat_owner=None):
    """Shared render implementation for `hypelab render` and the worker."""
    job = _get_job(conn, job_id)
    entry = job["state"]
    kit = _get_kit(conn, job)
    work = _work_dir(job_id)
    edl = _load_edl(work)

    tgt_aspect = edl["target"]["aspect"]
    if aspect is None:
        aspect = tgt_aspect
    if aspect != tgt_aspect:
        edl = _retarget_edl(edl, aspect)  # derived EDL; render.json keeps book aspect

    # Preflight: name the missing slots instead of failing deep in ffmpeg.
    missing = [b["id"] for b in edl["beats"]
               if not (b.get("clip") or b.get("clip_path"))]
    if missing:
        _die(f"missing clips for beats: {', '.join(missing)} "
             f"(attach with 'hypelab attach {job_id} <beat_id> <file)')")

    slug = aspect.replace(":", "x")
    out = Path(work) / "out" / f"{slug}.mp4"
    out.parent.mkdir(parents=True, exist_ok=True)

    if jobs_mod.get(conn, job_id)["state"] == "queued_render":
        _transition(conn, job_id, "rendering", f"aspect {aspect}")

    stop = threading.Event()
    beat_thread = None
    if heartbeat_owner:
        # Long renders heartbeat on a SEPARATE DB connection so the render's
        # own connection state is never shared across threads.
        def _beat():
            c2 = _conn()
            try:
                while not stop.wait(60):
                    if not queue_mod.heartbeat(c2, job_id, heartbeat_owner):
                        print(f"  heartbeat lost for {job_id} — lease expired")
                        break
            finally:
                c2.close()

        beat_thread = threading.Thread(target=_beat, daemon=True)
        beat_thread.start()

    try:
        rec = render_mod.render(
            edl, work, out, conn=conn, job_id=job_id,
            provenance=manifests_mod.provenance(kit),
        )
    except (render_mod.RenderError, manifests_mod.ManifestError) as e:
        _die(f"render failed: {e}")
    finally:
        if beat_thread is not None:
            stop.set()
            beat_thread.join()

    if rec["skipped"]:
        # Exact message the book's acceptance greps for.  A skip means the
        # output is already current, so the state is left untouched.
        print("hash unchanged, skipping")
        return rec

    print(f"rendered {out}")
    print(f"sha256: {rec['render_hash']}")

    # Hash changed: the output is new, so it must be re-gated.
    state = jobs_mod.get(conn, job_id)["state"]
    if state == "rendering":
        _transition(conn, job_id, "rendered", out.name)
        state = "rendered"
    if state == "rendered":
        _transition(conn, job_id, "queued_gates", "ready for gates")
    elif state == "queued_gates":
        pass  # already where a fresh render belongs
    else:
        # Unreachable via this CLI (attach/audio are blocked in ready and
        # gate_failed, so the hash cannot change there); fail open with a
        # warning rather than a bogus transition.
        print(f"warning: re-rendered from {entry}; state left as {state} — "
              f"re-run 'hypelab gates {job_id}' after re-driving the pipeline")
    return rec


@cli.command("render")
@click.argument("job_id")
@click.option("--aspect", type=click.Choice(sorted(ASPECT_DIMS)), default=None,
              help="Render a different aspect than the job's target.")
def render_cmd(job_id, aspect):
    """Render the job's EDL (hash-skip when nothing changed)."""
    conn = _conn()
    job = _get_job(conn, job_id)
    if job["state"] not in RENDER_ENTRY_STATES:
        _die(f"cannot render in state {job['state']!r}")
    _render_job(conn, job_id, aspect=aspect)


def _run_gates(conn, job_id):
    """Run gates.run_all on the latest render; print the 7-gate table.

    Returns True when every gate run_all reported passed.
    """
    work = _work_dir(job_id)
    rrow = conn.execute(
        "SELECT * FROM renders WHERE job_id=? ORDER BY rowid DESC LIMIT 1",
        (job_id,),
    ).fetchone()
    if rrow is None:
        _die(f"no renders recorded for job {job_id!r} (run 'hypelab render' first)")
    erow = conn.execute(
        "SELECT render_json FROM edls WHERE job_id=? ORDER BY version DESC LIMIT 1",
        (job_id,),
    ).fetchone()
    if erow is None:
        _die(f"no EDL versions recorded for job {job_id!r}")
    edl = json.loads(erow["render_json"])

    results = gates_mod.run_all(conn, job_id, edl, rrow["path"], work)
    by_name = {name: (ok, detail) for name, ok, detail in results}

    for name in BOOK7_GATES:
        ok, detail = by_name.get(name, (False, "gate did not run"))
        print(f"{name} {'PASS' if ok else 'FAIL'} — {detail}")

    extra = [(n, ok, d) for n, ok, d in results if n not in BOOK7_GATES]
    for n, ok, d in extra:
        print(f"  (extra gate {n}: {'PASS' if ok else 'FAIL'} — {d})")

    all_ok = all(ok for _, ok, _ in results)
    if all_ok:
        print(f"-> {rrow['path']}  ready")
    else:
        failed = [n for n, ok, _ in results if not ok]
        print(f"-> gate_failed: {', '.join(failed)}")
    return all_ok


@cli.command("gates")
@click.argument("job_id")
def gates_cmd(job_id):
    """Run the 7 Book-1 gates on the latest render; route to ready|gate_failed."""
    conn = _conn()
    job = _get_job(conn, job_id)
    state = job["state"]
    if state == "rendered":
        _transition(conn, job_id, "queued_gates", "gates requested")
        state = "queued_gates"
    if state not in ("queued_gates", "gating"):
        _die(f"cannot run gates in state {state!r} (need a render first)")
    if state == "queued_gates":
        _transition(conn, job_id, "gating", "gates running")

    ok = _run_gates(conn, job_id)
    if ok:
        _transition(conn, job_id, "ready", "all gates passed")
    else:
        _transition(conn, job_id, "gate_failed", "one or more gates failed")


# ---------------------------------------------------------------------------
# Worker
# ---------------------------------------------------------------------------

def _print_poison(conn):
    rows = conn.execute(
        "SELECT id, title, attempts, substr(error, 1, 100) AS err "
        "FROM jobs WHERE state='failed' ORDER BY updated_at"
    ).fetchall()
    if not rows:
        return
    print("poison review (state=failed):")
    for r in rows:
        print(f"  {r['id']}  attempts={r['attempts']}  "
              f"title={r['title']!r}  error={r['err']}")


def _handle_align(conn, job_id):
    """Worker align handler: the VO is already attached; align and route."""
    job = _get_job(conn, job_id)
    kit = _get_kit(conn, job)
    work = _work_dir(job_id)
    edl = _load_edl(work)
    doc, flagged = _do_align(conn, job_id, kit, work, edl)
    print(f"  aligned {doc['n_words']} words "
          f"(mean_p={doc['mean_confidence']:.3f})")
    if flagged:
        reasons = "; ".join(
            f"{f['beat_id']} mean_p={f['mean_word_p']}" for f in flagged
        )
        jobs_mod.transition(conn, job_id, "gate_failed",
                            f"low word confidence: {reasons}")
        print(f"  gate_failed: {reasons}")
        return
    jobs_mod.transition(conn, job_id, "aligned", f"{doc['n_words']} words")
    jobs_mod.transition(conn, job_id, "queued_render", "ready to render")


def _handle_render(conn, job_id, owner):
    _render_job(conn, job_id, heartbeat_owner=owner)


def _handle_gates(conn, job_id):
    ok = _run_gates(conn, job_id)
    if ok:
        jobs_mod.transition(conn, job_id, "ready", "all gates passed")
    else:
        jobs_mod.transition(conn, job_id, "gate_failed",
                            "one or more gates failed")


def _handle_ingest(conn, job_id):
    """Book 2: rights-gated ingest (fails closed without a rights basis)."""
    from hypelab import ingest as ingest_mod

    ingest_mod.ingest(conn, job_id, _work_dir(job_id))
    jobs_mod.transition(conn, job_id, "ingested", "ingest complete")
    jobs_mod.transition(conn, job_id, "queued_score", "awaiting score")


def _handle_score(conn, job_id):
    """Book 2: moment scoring (blind path when Tier 3 is absent)."""
    from hypelab import score as score_mod

    score_mod.score_moments(conn, job_id, _work_dir(job_id),
                            weights_dir=_WEIGHTS_DIR)
    jobs_mod.transition(conn, job_id, "scored", "scored")


@cli.command()
@click.option("--once", is_flag=True, default=False,
              help="Handle at most one job, then exit.")
@click.option("--owner", default=None,
              help="Worker owner tag (default hostname:pid).")
def work(once, owner):
    """Claim-loop worker: queued_align / queued_render / queued_gates
    (Book 1) plus queued_ingest / queued_score (Book 2, Clip Mine)."""
    owner = owner or f"{socket.gethostname()}:{os.getpid()}"
    conn = _conn()
    lease = _lease_seconds()
    print(f"worker {owner} starting (lease {lease}s)")
    try:
        while True:
            _print_poison(conn)
            row = queue_mod.claim(
                conn, owner,
                states=["queued_align", "queued_render", "queued_gates",
                        "queued_ingest", "queued_score"],
            )
            if row is None:
                print("no claimable jobs")
                if once:
                    break
                time.sleep(5)
                continue

            job_id, state = row["id"], row["state"]
            print(f"claimed {job_id} -> {state} (attempt {row['attempts']})")
            try:
                if state == "aligning":
                    _handle_align(conn, job_id)
                elif state == "rendering":
                    _handle_render(conn, job_id, owner)
                elif state == "gating":
                    _handle_gates(conn, job_id)
                elif state == "ingesting":
                    _handle_ingest(conn, job_id)
                elif state == "scoring":
                    _handle_score(conn, job_id)
                else:
                    raise RuntimeError(f"no handler for state {state!r}")
                print(f"done {job_id}")
            except Exception as e:  # handler blew up: record, don't lose the job
                print(f"handler error on {job_id}: {e}")
                try:
                    queue_mod.fail(conn, job_id, owner, e)
                except ValueError as ve:
                    print(f"  (fail() skipped: {ve})")

            if once:
                break
    except KeyboardInterrupt:
        print("worker stopping")


@cli.command()
@click.argument("job_id", required=False)
def costs(job_id):
    """Print the cost ledger (rows + totals), optionally filtered by job."""
    conn = _conn()
    if job_id:
        rows = conn.execute(
            "SELECT at, provider, unit, qty, usd, note FROM cost_ledger "
            "WHERE job_id=? ORDER BY at",
            (job_id,),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT job_id, at, provider, unit, qty, usd, note FROM cost_ledger "
            "ORDER BY at"
        ).fetchall()
    if not rows:
        print("no cost rows recorded")
        return

    show_job = job_id is None
    header = (f"{'JOB':<16}" if show_job else "") + \
        f"{'AT':<22}{'PROVIDER':<12}{'UNIT':<14}{'QTY':>8}  {'USD':>8}  NOTE"
    print(header)
    for r in rows:
        pre = f"{r['job_id']:<16}" if show_job else ""
        print(f"{pre}{r['at']:<22}{r['provider']:<12}{r['unit']:<14}"
              f"{r['qty']:>8.2f}  {r['usd']:>8.2f}  {r['note'] or ''}")

    total = sum(r["usd"] for r in rows)
    est = sum(r["usd"] for r in rows if (r["note"] or "").startswith("ESTIMATE|"))
    act = sum(r["usd"] for r in rows if (r["note"] or "").startswith("ACTUAL|"))
    print(f"total: ${total:.2f}  (estimate ${est:.2f} / actual ${act:.2f})")


# ---------------------------------------------------------------------------
# Book 2 (Clip Mine) commands.
# Implemented in hypelab/b2cli.py so Book 1's CLI surface stays untouched;
# registered here so `hypelab campaign add ...` etc. work from the front door.
# ---------------------------------------------------------------------------
from hypelab import b2cli as _b2cli

_b2cli.register(cli)

# Book 3 (Hype Layer) commands live in hypelab/book3cli.py so Book 1's
# CLI surface stays untouched.
from hypelab import book3cli as _b3cli

_b3cli.register(cli)


def main():
    cli()


if __name__ == "__main__":
    main()
