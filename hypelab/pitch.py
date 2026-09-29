"""Pitch generator (improved Book 3, section 6).

make_pitch() renders the pitch.md template against the target's observed
pattern, logs EVERY attempt to pitch_attempts (including no_response),
and requires a recorded pitch authorization — the system does not message
people on its own initiative, ever.

What goes in a pitch, in order of weight (book §6):
  1. Evidence you watched their work — cite the actual post, not the niche.
  2. What they get, stated first and concrete.
  3. The scope, verbatim — it doubles as consents.scope, so the pitch and
     the grant must match word for word, or the gate is theater.
  4. A one-tap yes. They accept the invite; they do nothing else.

Kill threshold (book §12): "20 pitches / ~3 accepts" is an EXPERIMENTAL
BUSINESS TRIPWIRE, not a statistical claim. It is cheap enough to hit and
painful enough to respect; it does not generalize and must not be quoted
as a power calculation.

Voice-match (book §7) is a HYPOTHESIS — that a pitch in the creator's
observable cadence gets accepted more often — and becomes a fact only
with 20+ measured pitches. Until then it is constrained styling:
consent for the corpus, public posts only, plagiarism caps (no verbatim
run longer than 5 words), no impersonation, signed as your brand.
"""
from __future__ import annotations

import json
import re
import sqlite3
from pathlib import Path

from . import authorize as authorize_mod
from . import jobs as jobs_mod
from .util import new_id, now

TEMPLATE_PATH = Path(__file__).resolve().parent / "pitch.md"

OUTCOMES = ("no_response", "accepted", "declined", "expired")

#: Experimental business tripwire (book §12) — labeled, never a statistic.
KILL_PITCHES = 20
KILL_ACCEPTS = 3

#: Plagiarism safeguard: no verbatim run longer than this many words.
MAX_VERBATIM_RUN = 5


class PitchError(Exception):
    """Pitch refused (no authorization, bad target, bad outcome)."""


def render_pitch(template_vars: dict,
                 template_path: str | Path | None = None) -> str:
    """Render the pitch.md template. {placeholders} not supplied raise."""
    text = Path(template_path or TEMPLATE_PATH).read_text(encoding="utf-8")

    def _sub(m: re.Match) -> str:
        key = m.group(1)
        if key not in template_vars:
            raise PitchError(f"pitch template needs {{{key}}}")
        return str(template_vars[key])

    return re.sub(r"\{([a-z_]+)\}", _sub, text)


def get_target(conn: sqlite3.Connection, handle: str,
               platform: str) -> dict | None:
    row = conn.execute(
        "SELECT * FROM targets WHERE handle=? AND platform=?",
        (handle, platform),
    ).fetchone()
    return dict(row) if row else None


def ensure_target(conn: sqlite3.Connection, handle: str, platform: str,
                  **fields) -> dict:
    """Create the target row if missing (consent-first: the row starts at
    consent_state='none'; nothing is assumed about publicity)."""
    conn.execute(
        """INSERT INTO targets(handle, platform, followers, engagement,
                               pattern_json, contact_route, consent_state)
           VALUES(?,?,?,?,?,?,'none')
           ON CONFLICT(handle, platform) DO NOTHING""",
        (handle, platform, fields.get("followers"), fields.get("engagement"),
         fields.get("pattern_json"), fields.get("contact_route")),
    )
    conn.commit()
    return get_target(conn, handle, platform)


def make_pitch(conn: sqlite3.Connection, job_id: str, handle: str,
               platform: str = "instagram", angle: str = "",
               brand: str = "New Light Management",
               sender: str = "Dino") -> dict:
    """Generate a pitch, log the attempt, move the job.

    Requires a recorded `pitch` authorization for the job. Transitions
    ready -> pitch_sent -> awaiting_consent. Returns the attempt row.
    """
    auth = authorize_mod.require_authorization(conn, job_id, "pitch")
    job = jobs_mod.get(conn, job_id)
    if job is None:
        raise PitchError(f"unknown job {job_id}")
    if job["state"] != "ready":
        raise PitchError(
            f"pitch starts from 'ready'; job is in '{job['state']}'"
        )
    target = ensure_target(conn, handle, platform)
    pattern = {}
    try:
        pattern = json.loads(target.get("pattern_json") or "{}")
    except (ValueError, TypeError):
        pattern = {}
    scope = "one Instagram collab post, your handle as co-author, 30-day window"
    pitch_text = render_pitch({
        "handle": handle,
        "platform": platform,
        "observed": pattern.get("best_post_shape")
                    or "your recent posts (pattern not yet recorded)",
        "angle": angle or "a data-backed look at what your audience responds to",
        "ask": "collab post — you accept the invite, it lands on both profiles",
        "scope": scope,
        "brand": brand,
        "sender": sender,
    })
    aid = new_id("pitch")
    ts = now()
    conn.execute(
        """INSERT INTO pitch_attempts(id, job_id, handle, platform, angle,
                                      pitch_text, authorization_id, outcome,
                                      sent_at)
           VALUES(?,?,?,?,?,?,?,?,?)""",
        (aid, job_id, handle, platform, angle, pitch_text, auth["id"],
         "no_response", ts),
    )
    conn.execute(
        "UPDATE targets SET consent_state='pitched' WHERE handle=? AND platform=?",
        (handle, platform),
    )
    jobs_mod.transition(conn, job_id, "pitch_sent",
                        f"pitch {aid} to {handle} (authorized {auth['id']})")
    jobs_mod.transition(conn, job_id, "awaiting_consent",
                        f"pitch {aid} sent — awaiting {handle}")
    conn.commit()
    return dict(
        conn.execute("SELECT * FROM pitch_attempts WHERE id=?", (aid,)).fetchone()
    )


def record_pitch_outcome(conn: sqlite3.Connection, attempt_id: str,
                         outcome: str, note: str | None = None) -> dict:
    """Log what happened to a pitch. no_response after 14 days is data."""
    if outcome not in OUTCOMES:
        raise PitchError(f"unknown pitch outcome {outcome!r}")
    row = conn.execute(
        "SELECT * FROM pitch_attempts WHERE id=?", (attempt_id,)
    ).fetchone()
    if row is None:
        raise PitchError(f"unknown pitch attempt {attempt_id}")
    row = dict(row)
    conn.execute(
        """UPDATE pitch_attempts SET outcome=?, decided_at=?, note=?
           WHERE id=?""",
        (outcome, now(), note, attempt_id),
    )
    if outcome == "accepted":
        conn.execute(
            "UPDATE targets SET consent_state='pitched' "
            "WHERE handle=? AND platform=?",
            (row["handle"], row["platform"]),
        )
    elif outcome == "declined":
        # They saw it and said no to the pitch. Never auto-re-pitched:
        # the next pitch needs a new angle and a new authorization.
        conn.execute(
            "UPDATE targets SET consent_state='denied' "
            "WHERE handle=? AND platform=?",
            (row["handle"], row["platform"]),
        )
    conn.commit()
    return dict(
        conn.execute("SELECT * FROM pitch_attempts WHERE id=?", (attempt_id,)).fetchone()
    )


def list_attempts(conn: sqlite3.Connection,
                  job_id: str | None = None) -> list[dict]:
    q = "SELECT * FROM pitch_attempts"
    args: tuple = ()
    if job_id:
        q += " WHERE job_id=?"
        args = (job_id,)
    q += " ORDER BY sent_at DESC"
    return [dict(r) for r in conn.execute(q, args).fetchall()]


def kill_threshold_status(conn: sqlite3.Connection) -> dict:
    """Report the experimental tripwire honestly: counts only, no verdict
    dressed as statistics."""
    n = conn.execute(
        "SELECT COUNT(*) c FROM pitch_attempts").fetchone()["c"]
    accepts = conn.execute(
        "SELECT COUNT(*) c FROM pitch_attempts WHERE outcome='accepted'"
    ).fetchone()["c"]
    return {
        "pitches": n,
        "accepts": accepts,
        "tripwire": f"{KILL_PITCHES} pitches / ~{KILL_ACCEPTS} accepts",
        "label": ("EXPERIMENTAL business tripwire — not a statistical claim, "
                  "not a power calculation"),
        "tripped": n >= KILL_PITCHES and accepts < KILL_ACCEPTS,
    }


# ------------------------------------------------------------------ voice

def voice_profile(samples: list[str]) -> dict:
    """Cadence/diction statistics over a consented public corpus.
    HYPOTHESIS machinery (book §7): style observations, not identity —
    no distinctive phrases, jokes, or signature lines are captured."""
    words = [w for s in samples for w in s.split()]
    sentences = [s for sample in samples
                 for s in re.split(r"[.!?]+", sample) if s.strip()]
    sent_lens = [len(s.split()) for s in sentences] or [0]
    return {
        "n_samples": len(samples),
        "mean_sentence_len": sum(sent_lens) / len(sent_lens),
        "contraction_rate": sum(
            1 for w in words if "'" in w or "’" in w) / max(1, len(words)),
        "vocabulary_floor": sorted({w.lower() for w in words if len(w) > 3}),
        "label": ("HYPOTHESIS — accept-rate effect unmeasured until 20+ "
                  "measured pitches (book §7)"),
    }


def plagiarism_check(text: str, samples: list[str],
                     max_run: int = MAX_VERBATIM_RUN) -> tuple[bool, str]:
    """No verbatim run longer than `max_run` words from any corpus sample."""
    def _runs(t: str) -> set[str]:
        ws = t.lower().split()
        return {" ".join(ws[i:i + max_run + 1])
                for i in range(len(ws) - max_run)}

    text_runs = _runs(text)
    for s in samples:
        overlap = text_runs & _runs(s)
        if overlap:
            example = sorted(overlap)[0]
            return False, (
                f"verbatim run > {max_run} words overlaps corpus: "
                f"{example[:60]!r}…"
            )
    return True, f"no verbatim run > {max_run} words"


def voice_match(draft: str, corpus_samples: list[str],
                corpus_consented: bool) -> tuple[dict, str]:
    """Constrain a draft against a consented public corpus.

    Returns (profile, guarded_draft). The draft is returned unchanged when
    it passes the plagiarism safeguard; the value-add is the constraint,
    not a rewrite. Raises PitchError when the corpus was not consented —
    never DMs, never private content, never scraped-then-asked.
    """
    if not corpus_consented:
        raise PitchError(
            "voice-match refused: no corpus consent on file. Public posts "
            "only, and only after the creator agreed to be pitched."
        )
    profile = voice_profile(corpus_samples)
    ok, detail = plagiarism_check(draft, corpus_samples)
    if not ok:
        raise PitchError(f"voice-match refused: {detail}")
    return profile, draft
