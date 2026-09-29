"""Versioned state-machine migration 3.0 (improved Book 3, section 2).

Book 3's state extensions are ADDED to Book 1's ALLOWED map via
apply_state_migrations(), which asserts additivity: a migration that
removes an existing out-transition fails hard instead of silently
narrowing the graph.

Deviation from the book's literal tuple, documented: the book lists
"ready": ("pitch_sent", "dry_run", "scheduled") WITHOUT "archived".
Book 1's "ready" already has ("archived",), so the book's literal
addition would fail its own assertion ({"archived"} is not a subset of
the addition). The addition below includes "archived" — the correct
additive reading of "ready GAINS pitch_sent/dry_run/scheduled". The
merged result is identical either way (union), but the assertion now
actually guards the invariant instead of tripping on the base map.

Second deviation, documented: the book's literal tuple omits
"scheduled" -> "consent_granted", but the book's own revocation rule
(section 5/6: revoking consent on a scheduled job knocks it back to
consent_granted for re-gating) would then be an ILLEGAL transition.
The addition below includes it — the spec's described behavior, not a
new invention. consent.revoke() depends on this edge.
"""

STATE_MIGRATIONS = [
    ("3.0", {
        "ready":            ("pitch_sent", "dry_run", "scheduled", "archived"),
        "dry_run":          ("ready", "failed"),
        "pitch_sent":       ("awaiting_consent", "failed"),
        "awaiting_consent": ("consent_granted", "consent_denied", "consent_expired"),
        "consent_granted":  ("scheduled", "archived"),
        "consent_denied":   (),                      # terminal, deliberately
        "consent_expired":  ("pitch_sent", "archived"),
        "scheduled":        ("published", "failed", "consent_granted"),
        # ^ consent_granted: documented deviation — the revocation knock-back
        # (consent.revoke on a scheduled job) requires this edge.
        "published":        ("awaiting_accept", "measured"),
        "awaiting_accept":  ("accepted", "declined", "accept_timeout"),
        "accepted":         ("measured",),
        "declined":         ("measured",),
        "accept_timeout":   ("measured",),
        "measured":         ("archived",),
    }),
]


def apply_state_migrations(base, migrations):
    """Merge versioned state additions into a base ALLOWED map.

    Only adds keys and adds out-transitions. Removing a transition fails
    with AssertionError — this is the runtime invariant behind "Book 3
    must not override Book 1".
    """
    from copy import deepcopy

    merged = deepcopy(base)
    for version, additions in migrations:
        for frm, tos in additions.items():
            existing = set(merged.get(frm, ()))
            assert existing <= set(tos), (
                f"state migration {version}: removed transitions from "
                f"{frm} ({sorted(existing - set(tos))}) — forbidden"
            )
            merged[frm] = tuple(sorted(existing | set(tos)))
    return merged
