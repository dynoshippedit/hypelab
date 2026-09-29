"""Book 2 (Clip Mine) tests.

Local files and synthesized media only: no yt-dlp, no network, no real
URLs. Tiny ffmpeg-synthesized clips stand in for real footage wherever a
probe is needed. The 10-minute acceptance fixture lives in
tests/fixtures_book2/ and is exercised by the acceptance run, not here.

Repo-root path hack matches the existing tests (no conftest.py in this repo).
"""
import json
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from hypelab import attribution  # noqa: E402
from hypelab import boundary  # noqa: E402
from hypelab import campaigns as campaigns_mod  # noqa: E402
from hypelab import compliance as compliance_mod  # noqa: E402
from hypelab import cut as cut_mod  # noqa: E402
from hypelab import ingest as ingest_mod  # noqa: E402
from hypelab import jobs as jobs_mod  # noqa: E402
from hypelab import metrics as metrics_mod  # noqa: E402
from hypelab import reframe as reframe_mod  # noqa: E402
from hypelab import render as render_mod  # noqa: E402
from hypelab import score as score_mod  # noqa: E402
from hypelab import tray as tray_mod  # noqa: E402
from hypelab import watcher as watcher_mod  # noqa: E402
from hypelab.db import connect  # noqa: E402

WEIGHTS_DIR = Path(__file__).resolve().parents[1] / "hypelab" / "weights"


@pytest.fixture()
def conn(tmp_path):
    cx = connect(tmp_path / "b2.db")
    yield cx
    cx.close()


def _campaign_dict(**over):
    d = {
        "id": "test-camp-1",
        "marketplace": "test-mart",
        "creator": "Test Creator",
        "rate_per_1k_usd": 4.0,
        "rate_basis": "observed",
        "platforms": ["tiktok"],
        "rules": {
            "min_s": 6,
            "max_s": 45,
            "required_handle": "@testcreator",
            "handle_placement": "caption",
            "required_hashtags": ["#test"],
            "required_credit": "Clip: Test Creator",
            "banned_words": ["bannedword"],
            "watermark_required": False,
            "platforms": ["tiktok"],
            "source_allowlist": ["fixture"],
            "music_policy": "original_audio_only",
        },
        "rules_provenance": {
            "source": "campaign_page",
            "url": "https://example.com/rules",
            "captured_at": "2026-09-28T00:00:00+00:00",
            "captured_by": "test",
        },
        "submission": {"url": "https://example.com/submit"},
    }
    d.update(over)
    return d


@pytest.fixture()
def camp(conn):
    campaigns_mod.add(conn, _campaign_dict())
    return campaigns_mod.load(conn, "test-camp-1")


def _tiny_mp4(path: Path, w: int, h: int, dur: float = 1.0) -> Path:
    cmd = ["ffmpeg", "-y", "-v", "error", "-f", "lavfi",
           "-i", f"testsrc=size={w}x{h}:rate=30:duration={dur}",
           "-f", "lavfi", "-i", f"sine=frequency=440:duration={dur}",
           "-c:v", "libx264", "-preset", "veryfast", "-crf", "30",
           "-c:a", "aac", "-shortest", str(path)]
    p = subprocess.run(cmd, capture_output=True, text=True, timeout=120,
                       shell=False)
    assert p.returncode == 0, p.stderr[-300:]
    return path


@pytest.fixture(scope="module")
def tiny_916(tmp_path_factory):
    return _tiny_mp4(tmp_path_factory.mktemp("media") / "v_916.mp4",
                     1080, 1920)


@pytest.fixture(scope="module")
def tiny_169(tmp_path_factory):
    return _tiny_mp4(tmp_path_factory.mktemp("media") / "v_169.mp4",
                     1280, 720)


def _base_clip(**over):
    c = {
        "id": "clip1", "job_id": "job1",
        "path": "",  # filled by caller
        "caption": "@testcreator a great training clip #test\n"
                   "Clip: Test Creator",
        "burned_text": "a great training clip",
        "ocr_confidence": 1.0,
        "overlays_text": [],
        "duration_s": 20.0,
        "source_url": "https://fixture.example/v/1",
        "audio_provenance": "campaign_supplied",
        "mixed_music": False,
        "watermark_verified": False,
        "target_aspect": "9:16",
        "platforms": ["tiktok"],
    }
    c.update(over)
    return c


# ------------------------------------------------------------------ migration

def test_migration_0002_applies(conn):
    rows = conn.execute(
        "SELECT version, name FROM schema_migrations ORDER BY version"
    ).fetchall()
    assert [(r["version"], r["name"]) for r in rows] == [
        (1, "0001_book1_foundation"), (2, "0002_book2_clip_mine"),
            (3, "0003_book3_hype_layer")]

    def cols(table):
        return {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}

    assert {"rate_basis", "budget_provenance",
            "rules_provenance"} <= cols("campaigns")
    assert "authorization" in cols("sources")
    assert "content_sha256" in cols("source_items")
    assert "weight_version" in cols("moments")
    assert "work_minutes" in cols("clips")
    assert "payout_usd" in cols("posts")
    assert "provenance" in cols("metrics")
    tables = {r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"moment_dedup", "compliance_log"} <= tables
    idx = {r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='index'")}
    assert "ix_moments_job" in idx


# ------------------------------------------------------------------ campaign

def test_campaign_add_and_validation(conn):
    cid = campaigns_mod.add(conn, _campaign_dict(id="c2"))
    assert cid == "c2"
    c = campaigns_mod.load(conn, "c2")
    assert c["rules_version"] == 1
    assert c["rules_provenance"]["source"] == "campaign_page"
    with pytest.raises(campaigns_mod.CampaignError):
        campaigns_mod.add(conn, {"id": "bad"})  # missing platforms/rules
    with pytest.raises(campaigns_mod.CampaignError):
        campaigns_mod.add(conn, _campaign_dict(id="c3", rate_basis="vibes"))


def test_campaign_provenance_dicts_round_trip(conn):
    d = _campaign_dict(
        id="c4",
        budget_provenance={"source": "campaign_page",
                           "url": "https://example.com/budget",
                           "captured_at": "2026-09-28T00:00:00+00:00",
                           "captured_by": "test"},
    )
    campaigns_mod.add(conn, d)
    c = campaigns_mod.load(conn, "c4")
    assert c["budget_provenance"]["source"] == "campaign_page"
    assert c["rules_provenance"]["source"] == "campaign_page"


def test_payout_rate_never_scores(conn, camp):
    # The payout rate exists on the campaign; scoring reads only weights.
    assert camp["rate_per_1k_usd"] == 4.0
    w = score_mod.load_weights(WEIGHTS_DIR)
    assert "rate" not in json.dumps(w["sets"])


# ------------------------------------------------------------------ rights

def _rights_job(conn, camp_id, authorization):
    jid = jobs_mod.new(conn, mode="clip", campaign_id=camp_id,
                       title="rights test", state="queued_ingest")
    sid = watcher_mod.add_source(
        conn, campaign_id=camp_id, kind="manual", url="x",
        authorization=authorization or {"basis": "needs_clearance"},
        poll_every_s=900)
    if authorization is None:
        conn.execute("UPDATE sources SET authorization=NULL WHERE id=?",
                     (sid,))
    conn.execute(
        "INSERT INTO source_items(id, source_id, url, job_id, seen_at)"
        " VALUES('ri1', ?, 'https://fixture.example/v/1', ?,"
        " '2026-09-28T00:00:00+00:00')", (sid, jid))
    return jid


def test_rights_fail_closed_no_manifest(conn, camp):
    jid = _rights_job(conn, camp["id"], None)
    with pytest.raises(ingest_mod.RightsError, match="no rights manifest"):
        ingest_mod.require_rights(conn, jid)


def test_rights_fail_closed_needs_clearance(conn, camp):
    jid = _rights_job(conn, camp["id"], {"basis": "needs_clearance"})
    with pytest.raises(ingest_mod.RightsError, match="no recorded clearance"):
        ingest_mod.require_rights(conn, jid)
    # After explicit clearance the same source passes.
    sid = conn.execute(
        "SELECT source_id FROM source_items WHERE job_id=?", (jid,)
    ).fetchone()[0]
    watcher_mod.record_clearance(conn, sid, granted_by="op",
                                 evidence="ticket-123")
    m = ingest_mod.require_rights(conn, jid)
    assert m["clearance"]["granted_by"] == "op"


def test_rights_fail_closed_unknown_basis(conn, camp):
    # Unknown bases are rejected at source-add time, before any job exists.
    with pytest.raises(watcher_mod.WatcherError, match="unknown rights basis"):
        watcher_mod.add_source(conn, campaign_id=camp["id"], kind="manual",
                               url="x", authorization={"basis": "vibes"},
                               poll_every_s=900)


def test_rights_pass_campaign_supplied(conn, camp):
    jid = _rights_job(conn, camp["id"], {"basis": "campaign_supplied",
                                        "granted_by": "campaign"})
    m = ingest_mod.require_rights(conn, jid)
    assert m["basis"] == "campaign_supplied"


# ------------------------------------------------------------------ scoring

def _words(n=40, step=0.4):
    vocab = ["the", "quick", "brown", "fox", "jumps", "over", "lazy", "dog"]
    return [{"w": vocab[i % len(vocab)], "t0": round(i * step, 3),
             "t1": round(i * step + 0.32, 3)} for i in range(n)]


def test_blind_path_when_tier3_absent(conn):
    signals = {"duration": 60.0, "heatmap": None, "comments": None}
    w = score_mod.load_weights(WEIGHTS_DIR)
    out = score_mod.score_windows(signals, _words(), w, audio_sig=None,
                                  win_s=20, hop_s=10)
    assert out, "expected windows"
    for m in out:
        assert m["confidence"] == pytest.approx(0.45)
        assert m["signals"]["weights"] == w["sets"]["blind"]
        assert m["signals"]["raw"]["tier3"] == "blind"


def test_full_path_when_tier3_present(conn):
    signals = {"duration": 60.0,
               "heatmap": [{"t0": 25.0, "t1": 35.0, "v": 0.9}],
               "comments": {"grid": 1.0, "density": [0.0] * 61,
                            "n_hits": 1, "hits": [{"t": 31.0}]}}
    w = score_mod.load_weights(WEIGHTS_DIR)
    out = score_mod.score_windows(signals, _words(), w, audio_sig=None,
                                  win_s=20, hop_s=10)
    assert all(m["confidence"] == pytest.approx(0.9) for m in out)
    assert all(m["signals"]["weights"] == w["sets"]["full"] for m in out)
    assert all(m["signals"]["raw"]["tier3"] == "full" for m in out)
    hot = [m for m in out
           if m["t_in"] <= 30.0 <= m["t_out"]]
    assert hot and all(m["signals"]["parts"]["heatmap"] > 0 for m in hot)


def test_weight_version_recorded(conn):
    w = score_mod.load_weights(WEIGHTS_DIR)
    out = score_mod.score_windows({"duration": 30.0}, _words(), w,
                                  win_s=20, hop_s=10)
    assert all(m["weight_version"] == "v1" for m in out)


def test_nms_suppresses_overlap():
    wins = [
        {"t_in": 0.0, "t_out": 20.0, "score": 0.9},
        {"t_in": 5.0, "t_out": 25.0, "score": 0.8},   # overlaps -> dropped
        {"t_in": 20.0, "t_out": 40.0, "score": 0.7},  # touches -> kept
        {"t_in": 50.0, "t_out": 70.0, "score": 0.6},  # disjoint -> kept
    ]
    kept = score_mod.nms(sorted(wins, key=lambda m: -m["score"]),
                         min_gap_s=30)
    assert [m["score"] for m in kept] == [0.9, 0.7, 0.6]


def test_dedup_catches_remine(conn, camp, tmp_path):
    work = tmp_path / "work" / "j1"
    work.mkdir(parents=True)
    (work / "source.words.json").write_text(json.dumps(
        {"words": _words(200, 0.4), "timing": "fixture"}))
    (work / "signals.json").write_text(json.dumps(
        {"duration": 80.0, "heatmap": None, "comments": None}))
    _tiny_mp4(work / "source.mp4", 320, 240, dur=10.0)
    jid = jobs_mod.new(conn, mode="A", campaign_id=camp["id"],
                       title="dedup", state="scoring")
    conn.execute(
        "INSERT INTO sources(id, campaign_id, kind, url, authorization,"
        " poll_every_s) VALUES('ds1', ?, 'manual', 'x',"
        " '{\"basis\": \"campaign_supplied\"}', 900)", (camp["id"],))
    conn.execute(
        "INSERT INTO source_items(id, source_id, url, job_id,"
        " content_sha256, seen_at)"
        " VALUES('di1', 'ds1', 'x', ?, 'sha:abc',"
        " '2026-09-28T00:00:00+00:00')", (jid,))
    first = score_mod.score_moments(conn, jid, work, weights_dir=WEIGHTS_DIR,
                                    win_s=20, hop_s=10)
    assert first, "first mine should find moments"
    assert all(m["weight_version"] == "v1" for m in first)
    second = score_mod.score_moments(conn, jid, work, weights_dir=WEIGHTS_DIR,
                                     win_s=20, hop_s=10)
    assert second == [], "re-mine must be caught by moment_dedup"


# ------------------------------------------------------------------ boundary

def _sentence_words():
    sents = ["The truth is most people train too hard.",
             "So I started tracking every single workout.",
             "Rest days matter more than you think."]
    words, t = [], 0.0
    for s in sents:
        for tok in s.split(" "):
            words.append({"w": tok, "t0": round(t, 3),
                          "t1": round(t + 0.3, 3)})
            t += 0.4
        t += 0.8
    return words


def test_boundary_never_starts_mid_sentence():
    words = _sentence_words()
    # Moment opens mid-sentence-2 (t inside "So I started...").
    seg = boundary.select(words, 4.0, 9.0)
    first = seg["words"][0]
    idx = next(i for i, w in enumerate(words) if w["t0"] == first["t0"])
    if idx > 0:
        assert words[idx - 1]["w"].endswith(".")
    # The segment start snapped to the sentence start.
    assert seg["t_in"] == pytest.approx(words[idx]["t0"])


def test_boundary_cold_open_premise_capped():
    words = _sentence_words()
    seg = boundary.select(words, 0.5, 12.0)
    if seg["premise"]:
        assert len(seg["premise"].split()) <= 9


# ------------------------------------------------------------------ reframe

def test_reframe_blurpad_math():
    f = reframe_mod.reframe_filter({"mode": "blurpad"},
                                   {"w": 1080, "h": 1920}, 1280, 720)
    assert "gblur" in f
    assert "overlay=(W-w)/2:(H-h)/2" in f
    assert "scale=1080:1920" in f


def test_reframe_static_math():
    plan = {"mode": "static",
            "keyframes": [{"t": 0.0, "cx": 0.5, "cy": 0.42, "scale": 1.0}]}
    f = reframe_mod.reframe_filter(plan, {"w": 1080, "h": 1920}, 1280, 720)
    # crop width = int(720*1080/1920)=405 -> even 404;
    # x = int((1280-404)*0.5)=438 -> even 438.
    assert f == "crop=404:720:'438':0,scale=1080:1920"


def test_step_expr_holds_and_cuts():
    e = reframe_mod.step_expr(
        [{"t": 0, "x": 100}, {"t": 5, "x": 200}, {"t": 9, "x": 300}])
    assert e == "if(lt(t,5.000),100,if(lt(t,9.000),200,300))"
    # No interpolation: only if()/lt() steps, never lerp/between blends.
    assert "lerp" not in e and "mix" not in e


def test_track_keyframes_are_held():
    # The step function must be a hold-and-cut (no interpolation/panning).
    f = reframe_mod.reframe_filter(
        {"mode": "track",
         "keyframes": [{"t": 0.0, "cx": 0.3}, {"t": 6.0, "cx": 0.7}]},
        {"w": 1080, "h": 1920}, 1280, 720)
    assert f.startswith("crop=")
    assert "if(lt(t,6.000)" in f


# ------------------------------------------------------------------ compliance

def _check(conn, camp, clip):
    return compliance_mod.check(conn, clip, camp)


def _ensure_clip(conn, camp, clip, state="cutting"):
    """Insert the job + clip rows a compliance check's audit log needs
    (compliance_log.clip_id has an FK to clips)."""
    jid = jobs_mod.new(conn, mode="A", campaign_id=camp["id"],
                       title="comp", state="cutting")
    conn.execute(
        "INSERT INTO clips(id, job_id, campaign_id, path, caption, state,"
        " compliance_json, created_at) VALUES(?,?,?,?,?,?,?,?)",
        (clip["id"], jid, camp["id"], clip["path"],
         clip.get("caption", ""), state,
         json.dumps({"passed": False}),
         "2026-09-28T00:00:00+00:00"))
    return jid


def test_compliance_all_pass(conn, camp, tiny_916):
    clip = _base_clip(path=str(tiny_916))
    _ensure_clip(conn, camp, clip)
    rec = _check(conn, camp, clip)
    assert rec["passed"] is True
    assert rec["failed"] == [] and rec["unknowns"] == []
    assert rec["rules_version"] == camp["rules_version"]


def _breaks(conn, camp, tiny_916, tiny_169):
    base = _base_clip(path=str(tiny_916))
    return [
        ("duration", dict(base, duration_s=3.0)),
        ("handle_present", dict(base, caption="no handle here #test\n"
                                              "Clip: Test Creator")),
        ("hashtags_present", dict(base, caption="@testcreator clip\n"
                                                "Clip: Test Creator")),
        ("credit_present", dict(base, caption="@testcreator clip #test")),
        ("banned_words", dict(base, caption=base["caption"] + " bannedword")),
        ("watermark", None),  # handled separately (unknown, not fail)
        ("aspect", dict(base, path=str(tiny_169))),
        ("platform_limits", dict(base, platforms=[])),
        ("source_allowed", dict(base,
                                source_url="https://evil.example/v/1")),
        ("music_policy", dict(base, mixed_music=True)),
    ]


def test_compliance_each_check_breaks_once(conn, camp, tiny_916, tiny_169):
    for name, clip in _breaks(conn, camp, tiny_916, tiny_169):
        if clip is None:
            continue
        _ensure_clip(conn, camp, dict(clip, id=f"clip-{name}"))
        clip = dict(clip, id=f"clip-{name}")
        rec = _check(conn, camp, clip)
        assert name in rec["failed"], f"{name} should fail, got {rec}"
        assert rec["passed"] is False


def test_compliance_watermark_unknown_not_fail(conn, camp, tiny_916):
    rules = dict(camp["rules"], watermark_required=True)
    camp2 = dict(camp, rules=rules)
    clip = _base_clip(id="clipW", path=str(tiny_916))
    _ensure_clip(conn, camp, clip)
    rec = _check(conn, camp2, clip)
    assert "watermark" in rec["unknowns"]
    assert rec["passed"] is False
    assert rec["failed"] == []


def test_compliance_unknown_routes_to_human(conn, camp, tiny_916):
    # Rules with no provenance are rumors, not rules: every rule-governed
    # check goes UNKNOWN, never auto-pass.
    camp_np = dict(camp, rules_provenance=None)
    clip = _base_clip(id="clipU", path=str(tiny_916))
    jid = _ensure_clip(conn, camp, clip, state="compliance_unknown")
    rec = _check(conn, camp_np, clip)
    assert rec["passed"] is False
    assert rec["unknowns"], "expected forced UNKNOWNs"
    conn.execute("UPDATE clips SET compliance_json=? WHERE id='clipU'",
                 (json.dumps(rec),))
    dest = compliance_mod.route_job(conn, jid)
    assert dest == "compliance_unknown"
    assert jobs_mod.get(conn, jid)["state"] == "compliance_unknown"


def test_compliance_human_resolve(conn, camp, tiny_916):
    jid = jobs_mod.new(conn, mode="clip", campaign_id=camp["id"],
                       title="r", state="compliance_unknown")
    conn.execute(
        "INSERT INTO clips(id, job_id, campaign_id, path, state,"
        " compliance_json, created_at) VALUES(?,?,?,?,?,?,?)",
        ("clipR", jid, camp["id"], str(tiny_916), "compliance_unknown",
         json.dumps({"passed": False, "unknowns": ["watermark"],
                     "failed": []}),
         "2026-09-28T00:00:00+00:00"))
    res = compliance_mod.resolve(conn, "clipR", "dino", "pass",
                                 note="watermark visible in corner")
    assert res["state"] == "tray"
    log = conn.execute(
        "SELECT decided_by FROM compliance_log WHERE clip_id='clipR'"
        " ORDER BY id DESC LIMIT 1").fetchone()
    assert log["decided_by"] == "human:dino"
    assert jobs_mod.get(conn, jid)["state"] == "tray"


# ------------------------------------------------------------------ tray

def test_tray_ranks_and_materializes(conn, camp, tiny_916, tmp_path,
                                     monkeypatch):
    monkeypatch.setenv("HYPELAB_WORK_DIR", str(tmp_path))
    # Tray thumbnails seek to t=1s, so the source needs more than a second.
    src916 = _tiny_mp4(tmp_path / "v_916_3s.mp4", 1080, 1920, dur=3.0)
    jid = jobs_mod.new(conn, mode="A", campaign_id=camp["id"],
                       title="tray", state="tray")
    for i, pred in enumerate([0.2, 0.9, 0.5]):
        cid = f"tc{i}"
        src = tmp_path / f"{cid}.mp4"
        src.write_bytes(src916.read_bytes())
        conn.execute(
            "INSERT INTO clips(id, job_id, campaign_id, path, caption,"
            " predicted, state, compliance_json, created_at)"
            " VALUES(?,?,?,?,?,?,?,?,?)",
            (cid, jid, camp["id"], str(src), "cap", pred, "tray",
             json.dumps({"passed": True, "rules_version": 1}),
             "2026-09-28T00:00:00+00:00"))
    ranked = __import__("hypelab.tray", fromlist=["build_tray"]).build_tray(
        conn, jid, tmp_path)
    assert [c["predicted"] for c in ranked] == [0.9, 0.5, 0.2]
    slugs = sorted(p.name for p in (tmp_path / "work" / jid / "tray").iterdir())
    assert slugs == ["clip_0001", "clip_0002", "clip_0003"]
    d = tmp_path / "work" / jid / "tray" / "clip_0001"
    for name in ("clip.mp4", "caption.txt", "meta.json", "submit.url",
                 "thumb.jpg"):
        assert (d / name).is_file(), name
    meta = json.loads((d / "meta.json").read_text())
    assert meta["campaign"]["id"] == camp["id"]


def _stale_clip(conn, camp, tmp_path, cid, caption, monkeypatch):
    """One tray clip gated under rules_version=1 (7s 9:16, genuinely
    compliant under the fixture rules), returned with its job id."""
    monkeypatch.setenv("HYPELAB_WORK_DIR", str(tmp_path))
    src = _tiny_mp4(tmp_path / f"{cid}.mp4", 1080, 1920, dur=7.0)
    jid = jobs_mod.new(conn, mode="clip", campaign_id=camp["id"],
                       title="reg", state="tray")
    conn.execute(
        "INSERT INTO clips(id, job_id, campaign_id, path, caption,"
        " predicted, state, compliance_json, created_at)"
        " VALUES(?,?,?,?,?,?,?,?,?)",
        (cid, jid, camp["id"], str(src), caption, 0.9, "tray",
         json.dumps({"passed": True, "rules_version": 1}),
         "2026-09-28T00:00:00+00:00"))
    return jid


def _bump(conn, camp, **rule_over):
    rules = dict(camp["rules"], **rule_over)
    rules.pop("source_allowlist", None)  # re-gate probes with source_url=""
    return campaigns_mod.bump_rules(
        conn, camp["id"], rules,
        {"who": "test", "source_url": "https://example.com/rules",
         "captured_at": "2026-09-28T00:00:00+00:00"})


def test_tray_regates_stale_compliance_pass(conn, camp, tmp_path,
                                            monkeypatch):
    """Book 2 §3: rules changed since gating -> the tray re-runs the gate
    first. A clip that passes the new rules is handed over, with a
    refreshed compliance record (new rules_version)."""
    caption = ("@testcreator a great training clip #test #v2\n"
               "Clip: Test Creator")
    jid = _stale_clip(conn, camp, tmp_path, "rc1", caption, monkeypatch)
    v = _bump(conn, camp, required_hashtags=["#test", "#v2"])
    assert v == 2
    ranked = tray_mod.build_tray(conn, jid, tmp_path)
    assert len(ranked) == 1
    rec = json.loads(conn.execute(
        "SELECT compliance_json FROM clips WHERE id='rc1'").fetchone()[0])
    assert rec["passed"] is True and rec["rules_version"] == 2
    assert (tmp_path / "work" / jid / "tray" / "clip_0001"
            / "clip.mp4").is_file()


def test_tray_excludes_clip_failing_regate(conn, camp, tmp_path,
                                           monkeypatch):
    """A clip that fails the re-gate is refused by the tray: excluded from
    the handoff, routed to failed, job re-aggregated."""
    caption = ("@testcreator a great training clip #test\n"
               "Clip: Test Creator")
    jid = _stale_clip(conn, camp, tmp_path, "rc2", caption, monkeypatch)
    _bump(conn, camp, required_hashtags=["#test", "#newtag"])
    ranked = tray_mod.build_tray(conn, jid, tmp_path)
    assert ranked == []
    st = conn.execute(
        "SELECT state FROM clips WHERE id='rc2'").fetchone()[0]
    assert st == "failed"
    assert jobs_mod.get(conn, jid)["state"] == "failed"
    assert not (tmp_path / "work" / jid / "tray" / "clip_0001").exists()


# ------------------------------------------------------------------ metrics

def test_metrics_provenance_unavailable_writes_null(conn, camp):
    jid = jobs_mod.new(conn, mode="clip", campaign_id=camp["id"],
                       title="m", state="posted")
    conn.execute(
        "INSERT INTO clips(id, job_id, campaign_id, path, state, created_at)"
        " VALUES('mc1', ?, ?, 'x', 'posted', '2026-09-28T00:00:00+00:00')",
        (jid, camp["id"]))
    conn.execute(
        "INSERT INTO posts(id, clip_id, platform, post_url, posted_at)"
        " VALUES('mp1', 'mc1', 'tiktok', 'https://tiktok.example/v/1',"
        " '2026-09-28T00:00:00+00:00')")
    rows = metrics_mod.poll_metrics(conn)
    assert len(rows) == 1
    assert rows[0]["provenance"] == "unavailable"
    got = conn.execute(
        "SELECT views, provenance FROM metrics WHERE post_id='mp1'"
    ).fetchone()
    assert got["views"] is None and got["provenance"] == "unavailable"


def test_user_metrics_never_calibration_grade(conn, camp):
    jid = jobs_mod.new(conn, mode="clip", campaign_id=camp["id"],
                       title="um", state="posted")
    conn.execute(
        "INSERT INTO clips(id, job_id, campaign_id, path, state, created_at)"
        " VALUES('mc2', ?, ?, 'x', 'posted',"
        " '2026-09-28T00:00:00+00:00')",
        (jid, camp["id"]))
    conn.execute(
        "INSERT INTO posts(id, clip_id, platform, post_url, posted_at)"
        " VALUES('mp2', 'mc2', 'tiktok', 'https://tiktok.example/v/2',"
        " '2026-09-28T00:00:00+00:00')")
    r = metrics_mod.record_user_metrics(conn, "mp2", views=1234,
                                        note="screenshot")
    assert r["provenance"] == "user_entered"
    assert metrics_mod.best_views(conn, "mp2") is None


# ------------------------------------------------------------------ attribution

def test_attribution_guards(conn):
    with pytest.raises(attribution.AttributionError, match="n=50|minimum 50"):
        attribution.propose_weights(conn, WEIGHTS_DIR)
    conn.execute(
        "INSERT INTO what_worked(dimension, value, n, mean_perf, updated_at)"
        " VALUES('signal_heatmap', '0.8', 29, 100.0, 'x')")
    conn.execute(
        "INSERT INTO what_worked(dimension, value, n, mean_perf, updated_at)"
        " VALUES('signal_heatmap', '0.9', 30, 200.0, 'x')")
    dims = attribution.read_dimensions(conn)
    assert [r["value"] for r in dims["signal"]] == ["0.9"]
    assert [r["value"] for r in dims["below_threshold"]] == ["0.8"]
    text = attribution.describe_row(dims["signal"][0])
    assert "averaged" in text and "caused" not in text


def test_promote_requires_explicit_approval(conn, tmp_path):
    cand = tmp_path / "weights_v2_candidate.json"
    cand.write_text(json.dumps({"version": "v2", "status": "draft",
                                "sets": {}}))
    with pytest.raises(attribution.AttributionError, match="not 'proposed'"):
        attribution.promote_weights(tmp_path, cand, "dino")


# ------------------------------------------------------------------ posted

def test_posted_requires_url(conn, camp):
    jid = jobs_mod.new(conn, mode="clip", campaign_id=camp["id"],
                       title="p", state="tray")
    conn.execute(
        "INSERT INTO clips(id, job_id, campaign_id, path, state,"
        " compliance_json, created_at) VALUES(?,?,?,?,?,?,?)",
        ("clipP", jid, camp["id"], "x", "tray",
         json.dumps({"passed": True, "rules_version": 1}),
         "2026-09-28T00:00:00+00:00"))
    with pytest.raises(cut_mod.CutError, match="post_url is required"):
        cut_mod.record_posted(conn, "clipP", "", "tiktok")


# ------------------------------------------------------------------ watcher

def test_watcher_manual_poll_and_rededup(conn, camp, tmp_path):
    listing = tmp_path / "listing.json"
    listing.write_text(json.dumps({"items": [{
        "id": "w1", "url": "https://fixture.example/v/9",
        "title": "Watch item", "duration": 600,
        "published_at": "2026-09-28T00:00:00+00:00"}]}))
    watcher_mod.add_source(
        conn, campaign_id=camp["id"], kind="manual", url=str(listing),
        authorization={"basis": "campaign_supplied"}, poll_every_s=300)
    new = watcher_mod.poll(conn)
    assert len(new) == 1
    item, jid = new[0]
    assert jobs_mod.get(conn, jid)["state"] == "queued_ingest"
    row = conn.execute(
        "SELECT job_id FROM source_items WHERE id='w1'").fetchone()
    assert row["job_id"] == jid
    assert watcher_mod.poll(conn) == [], "second poll must not re-enqueue"


# ------------------------------------------------------------------ render ext

def test_overlays_enable_is_additive():
    edl = {"target": {"h": 1920},
           "overlays": [{"text": "hi", "pos": "top"}]}
    without = render_mod.overlays_chain(edl)
    assert not any("enable=" in p for p in without)
    edl["overlays"][0]["enable"] = "between(t,0,2)"
    with_ = render_mod.overlays_chain(edl)
    assert any("enable='between(t,0,2)'" in p for p in with_)
