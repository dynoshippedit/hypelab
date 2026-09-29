"""EDL (Edit Decision List) build + validate (Book 1).

Shape is enforced by EDL_SCHEMA (jsonschema). validate() adds the
temporal/structural rules a schema cannot express and raises EDLError with
a list of human-readable strings.

Render fingerprinting lives in hypelab.manifests.render_hash (content-hash
identity + provenance); edl.py no longer hashes inputs itself.
"""
from __future__ import annotations

import jsonschema

_BEAT_ROLES = ["hook", "body", "turn", "payoff", "cta"]

EDL_SCHEMA = {
    "type": "object",
    "required": [
        "mode", "kit", "target", "beats",
        "audio", "captions", "overlays", "gates_passed",
    ],
    "properties": {
        "mode": {"type": "string", "enum": ["original", "clip"]},
        "kit": {"type": "string", "pattern": "^[a-z0-9_-]+@\\d+$"},
        "target": {
            "type": "object",
            "required": [
                "aspect", "w", "h", "fps", "max_duration_s", "loudness_lufs",
            ],
            "properties": {
                "aspect": {"type": "string", "enum": ["9:16", "1:1", "16:9"]},
                "w": {"type": "integer"},
                "h": {"type": "integer"},
                "fps": {"type": "number"},
                "max_duration_s": {"type": "number"},
                "loudness_lufs": {"type": "number"},
            },
        },
        "beats": {
            "type": "array",
            "minItems": 1,
            "items": {
                "type": "object",
                "required": [
                    "id", "role", "t_in", "t_out",
                    "line", "clip", "clip_in", "clip_fit",
                ],
                "properties": {
                    "id": {"type": "string"},
                    "role": {"type": "string", "enum": _BEAT_ROLES},
                    "t_in": {"type": "number"},
                    "t_out": {"type": "number"},
                    "line": {"type": "string"},
                    "clip": {"type": ["string", "null"]},
                    "clip_in": {"type": "number"},
                    "clip_fit": {
                        "type": "string",
                        "enum": ["cover", "contain", "blurpad"],
                    },
                    "prompt_used": {"type": ["string", "null"]},
                    "ref_image": {"type": ["string", "null"]},
                    # Book-2 hook: per-beat reframe plan (detail-validated by
                    # hypelab.reframe when present).
                    "reframe": {"type": "object"},
                },
            },
        },
        "audio": {
            "type": "object",
            "required": ["vo"],
            "properties": {
                "vo": {"type": ["object", "null"]},
                "music": {"type": ["object", "null"]},
            },
        },
        "captions": {"type": "object"},
        "overlays": {"type": "array"},
        "compliance": {"type": ["object", "null"]},
        "gates_passed": {"type": "array", "items": {"type": "string"}},
        "render_hash": {"type": ["string", "null"]},
    },
}


class EDLError(Exception):
    """Raised by validate(); carries the list of violation strings."""

    def __init__(self, errors: list[str]):
        self.errors = list(errors)
        super().__init__(
            "EDL invalid:\n" + "\n".join(f"  - {e}" for e in self.errors)
        )


def _schema_errors(edl: dict) -> list[str]:
    v = jsonschema.Draft7Validator(EDL_SCHEMA)
    out = []
    for e in sorted(v.iter_errors(edl), key=lambda x: list(x.absolute_path)):
        where = "/".join(str(p) for p in e.absolute_path) or "<root>"
        out.append(f"{where}: {e.message}")
    return out


def _beats_ok(beats) -> bool:
    """True when beats are a non-empty list of dicts with numeric boundaries."""
    return (
        isinstance(beats, list)
        and bool(beats)
        and all(
            isinstance(b, dict)
            and isinstance(b.get("t_in"), (int, float))
            and isinstance(b.get("t_out"), (int, float))
            for b in beats
        )
    )


def validate(edl: dict) -> bool:
    """Validate shape (schema) plus temporal/structural rules.

    Extra rules beyond the schema:
      1. beats contiguous: b[i].t_out == b[i+1].t_in within 1e-3
         (no gaps, no overlaps);
      2. beats[0].t_in == 0 and every t_out > t_in;
      3. total = beats[-1].t_out <= target.max_duration_s;
      4. exactly one hook: beats[0].role == "hook" and no other beat is hook.
    Returns True; raises EDLError(list_of_strings) on any violation.
    """
    errors = _schema_errors(edl)

    beats = edl.get("beats") if isinstance(edl, dict) else None
    target = edl.get("target") if isinstance(edl, dict) else None

    if _beats_ok(beats):
        # Rule 2: first beat starts at 0; every beat has positive duration.
        if abs(beats[0]["t_in"]) > 1e-6:
            errors.append(
                f"beats[0].t_in: must be 0, got {beats[0]['t_in']}"
            )
        for i, b in enumerate(beats):
            if not b["t_out"] > b["t_in"]:
                errors.append(
                    f"beats[{i}].t_out: must be > t_in "
                    f"({b['t_in']} -> {b['t_out']})"
                )
        # Rule 1: contiguity within 1e-3 (no gaps, no overlaps).
        for i in range(len(beats) - 1):
            a, b = beats[i], beats[i + 1]
            drift = b["t_in"] - a["t_out"]
            if abs(drift) > 1e-3:
                kind = "gap" if drift > 0 else "overlap"
                errors.append(
                    f"beats[{i}]->beats[{i + 1}]: {kind} of {drift:.4f}s "
                    f"(t_out={a['t_out']}, next t_in={b['t_in']})"
                )
        # Rule 4: exactly one hook, and it is the first beat.
        hooks = [i for i, b in enumerate(beats) if b.get("role") == "hook"]
        if not hooks or hooks[0] != 0:
            errors.append('beats: exactly one hook required and beats[0].role must be "hook"')
        elif len(hooks) > 1:
            errors.append(
                f"beats: multiple hooks at indices {hooks} "
                '(only beats[0] may be "hook")'
            )
        # Rule 3: total duration within the target budget.
        if isinstance(target, dict) and isinstance(
            target.get("max_duration_s"), (int, float)
        ):
            total = beats[-1]["t_out"]
            if total > target["max_duration_s"] + 1e-6:
                errors.append(
                    f"beats: total {total:.3f}s exceeds "
                    f"target.max_duration_s={target['max_duration_s']}"
                )

    if errors:
        raise EDLError(errors)
    return True


def build_edl(
    *,
    mode: str,
    kit_ref: str,
    target: dict,
    beats: list[dict],
    audio: dict | None = None,
    captions: dict | None = None,
    overlays: list | None = None,
    compliance: dict | None = None,
    min_word_prob: float = 0.5,
) -> dict:
    """Assemble the full EDL dict. Does not validate (see validate()).

    ``min_word_prob`` is stamped from the kit (Book 1 §8): the word-
    confidence gate fails beats below this word probability.
    """
    return {
        "mode": mode,
        "kit": kit_ref,
        "target": target,
        "beats": beats,
        "audio": audio if audio is not None else {"vo": None, "music": None},
        "captions": captions if captions is not None else {},
        "overlays": overlays if overlays is not None else [],
        "compliance": compliance,
        "min_word_prob": float(min_word_prob),
        "gates_passed": [],
        "render_hash": None,
    }
