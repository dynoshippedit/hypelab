"""Tests for CSV formula-injection hardening (SEC-104).

The consent ledger export writes user-controlled cells (handle, actor, scope,
artifact_path, revocation_note, etc.) that can begin with =, +, -, @, a tab or
a carriage return. Opened in a spreadsheet, such cells execute as formulas
unless neutralized. ``_csv_safe`` prefixes those cells with a single quote so
they are treated as literal text.
"""
import csv
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from hypelab import consent as consent_mod  # noqa: E402
from hypelab import jobs as jobs_mod  # noqa: E402


# ------------------------------------------------------------------ helper unit tests
@pytest.mark.parametrize("value", ["=1+1", "+x", "-x", "@x", "\tx", "\rx"])
def test_csv_safe_prefixes_formula_chars(value):
    out = consent_mod._csv_safe(value)
    assert out == "'" + value
    assert out[1] in ("=", "+", "-", "@", "\t", "\r")


@pytest.mark.parametrize("value", ["normal", ""])
def test_csv_safe_leaves_safe_strings_unchanged(value):
    # "normal" and "" have no formula-triggering first character.
    # "" has no first char at all, so it is not prefixed.
    assert consent_mod._csv_safe(value) == value


@pytest.mark.parametrize("value", [None, 5, 3.14, 0, True])
def test_csv_safe_passthrough_non_strings(value):
    assert consent_mod._csv_safe(value) is value


# ------------------------------------------------------------------ export integration
@pytest.fixture()
def conn(tmp_path):
    from hypelab.db import connect

    cx = connect(tmp_path / "b3.db")
    yield cx
    cx.close()


def _job(conn, state="ready", mode="carousel", title="csv-safe test"):
    jid = jobs_mod.new(conn, mode=mode, title=title, state=state)
    conn.commit()
    return jid


def _media(tmp_path, name="a.bin", data=b"fake-media-bytes"):
    p = tmp_path / name
    p.write_bytes(data)
    return str(p)


def test_export_ledger_neutralizes_formula_cells(conn, tmp_path):
    """A grant whose scope begins with a spreadsheet formula is written
    out as a literal text cell (prefixed with a single quote)."""
    jid = _job(conn)
    m = _media(tmp_path)
    grant = consent_mod.grant(
        conn, job_id=jid, handle="@evil", platform="instagram",
        actor="@creator via DM", account_id="ig:evil",
        scope="=HYPERLINK(\"http://x\")",
        artifact_path=m, expires_at="2030-01-01T00:00:00+00:00",
        jurisdiction="US-OH", terms_version="pitch.md v1",
    )
    out = tmp_path / "ledger.csv"
    consent_mod.export_ledger(conn, out)

    with open(out, newline="", encoding="utf-8") as f:
        rows = list(csv.reader(f))

    # header + one data row
    assert len(rows) == 2
    header = rows[0]
    data = rows[1]

    # header is NOT neutralized (column names never start with a formula char)
    scope_idx = header.index("scope")
    assert data[scope_idx].startswith("'=")
    # the literal cell value (without the leading quote) is the stored scope
    assert data[scope_idx][1:] == grant["scope"]

    # every data cell is a neutralized string or a pass-through for non-strings;
    # the scope column specifically must not start with '=' unquoted
    assert not data[scope_idx].startswith("=")  # the quote prefix protects it
