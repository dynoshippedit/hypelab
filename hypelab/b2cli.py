"""HypeLab Book 2 (Clip Mine) CLI commands.

Registered onto the main ``hypelab`` click group by cli.py (Book 2's
commands live here so Book 1's cli.py diff stays a two-line registration).

Conventions mirror cli.py: HYPELAB_DB / HYPELAB_ROOT env overrides, errors
via _die to stderr with a nonzero exit.
"""
from __future__ import annotations

import json
import os
import socket
import sys
import time
from pathlib import Path

import click

import hypelab
from hypelab import attribution as attribution_mod
from hypelab import campaigns as campaigns_mod
from hypelab import compliance as compliance_mod
from hypelab import cut as cut_mod
from hypelab import ingest as ingest_mod
from hypelab import jobs as jobs_mod
from hypelab import metrics as metrics_mod
from hypelab import queue as queue_mod
from hypelab import score as score_mod
from hypelab import tray as tray_mod
from hypelab import watcher as watcher_mod
from hypelab import db as db_mod
from hypelab.util import work_dir as _work_dir

DEFAULT_ROOT = "/home/dino/hypelab"
WEIGHTS_DIR = Path(hypelab.__file__).parent / "weights"

COMMANDS: list[click.BaseCommand] = []


def _die(msg, code=1):
    print(f"error: {msg}", file=sys.stderr)
    raise SystemExit(code)


def _root():
    return os.environ.get("HYPELAB_ROOT", DEFAULT_ROOT)


def _conn():
    return db_mod.connect(os.environ.get("HYPELAB_DB") or None)


def _work(job_id):
    return _work_dir(job_id, root=_root())


def _read_json(path, what):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        _die(f"cannot read {what} {path}: {e}")


def _cmd(fn=None, **kw):
    """Register a click command in COMMANDS."""
    def deco(f):
        c = click.command(**kw)(f)
        COMMANDS.append(c)
        return c
    return deco(fn) if fn else deco


# ------------------------------------------------------------------ campaign

@click.group("campaign")
def campaign_grp():
    """Campaign lifecycle: add, list, show, deliberate rule/budget ops."""


@campaign_grp.command("add")
@click.argument("json_path")
def campaign_add(json_path):
    """Add a campaign from a JSON file. Prints the campaign id."""
    data = _read_json(json_path, "campaign json")
    conn = _conn()
    try:
        cid = campaigns_mod.add(conn, data)
    except campaigns_mod.CampaignError as e:
        _die(str(e))
    print(cid)


@campaign_grp.command("list")
def campaign_list():
    for c in campaigns_mod.list_all(_conn()):
        print(f"{c['id']}  {c['creator']}  {c['marketplace']}  "
              f"rules_v{c['rules_version']}  {c['status']}")


@campaign_grp.command("show")
@click.argument("campaign_id")
def campaign_show(campaign_id):
    conn = _conn()
    try:
        c = campaigns_mod.load(conn, campaign_id)
    except KeyError:
        _die(f"campaign {campaign_id!r} not found")
    print(json.dumps(c, indent=2))


@campaign_grp.command("bump-rules")
@click.argument("campaign_id")
@click.argument("rules_json")
@click.option("--by", "operator", required=True,
              help="Operator name (recorded in provenance).")
def campaign_bump_rules(campaign_id, rules_json, operator):
    """Deliberate rules bump (a human changed the rules)."""
    rules = _read_json(rules_json, "rules json")
    conn = _conn()
    try:
        v = campaigns_mod.bump_rules(conn, campaign_id, rules, operator)
    except campaigns_mod.CampaignError as e:
        _die(str(e))
    print(f"rules -> v{v}")


@campaign_grp.command("refresh-budget")
@click.argument("campaign_id")
@click.argument("budget_json")
@click.option("--by", "operator", required=True,
              help="Operator name (recorded in provenance).")
def campaign_refresh_budget(campaign_id, budget_json, operator):
    """Deliberate budget refresh (a human re-read the campaign page)."""
    budget = _read_json(budget_json, "budget json")
    conn = _conn()
    try:
        campaigns_mod.refresh_budget(conn, campaign_id, budget, operator)
    except campaigns_mod.CampaignError as e:
        _die(str(e))
    print("budget refreshed")


COMMANDS.append(campaign_grp)


# ------------------------------------------------------------------ source

@click.group("source")
def source_grp():
    """Source lifecycle: add (rights manifest required), clearance, list."""


@source_grp.command("add")
@click.option("--campaign", required=True, help="Campaign id.")
@click.option("--kind", required=True,
              type=click.Choice(["yt_channel", "rss", "twitch", "manual"]))
@click.option("--url", required=True,
              help="Channel/playlist URL, feed URL, or (kind=manual) the "
                   "local JSON listing file.")
@click.option("--rights", "rights_path", required=True,
              help="Rights manifest JSON (basis + provenance).")
@click.option("--poll-every", "poll_every_s", type=int, default=900,
              help="Seconds between polls (floor: 300).")
def source_add(campaign, kind, url, rights_path, poll_every_s):
    """Add a source. Fails closed without a valid rights manifest."""
    manifest = _read_json(rights_path, "rights manifest")
    conn = _conn()
    try:
        sid = watcher_mod.add_source(
            conn, campaign_id=campaign, kind=kind, url=url,
            authorization=manifest, poll_every_s=poll_every_s,
        )
    except watcher_mod.WatcherError as e:
        _die(str(e))
    print(sid)


@source_grp.command("clearance")
@click.option("--source", "source_id", required=True)
@click.option("--granted-by", required=True)
@click.option("--evidence", required=True,
              help="Evidence of clearance (note, ticket, screenshot path).")
@click.option("--scope", default="")
def source_clearance(source_id, granted_by, evidence, scope):
    """Record explicit clearance (rights basis needs_clearance)."""
    conn = _conn()
    try:
        watcher_mod.record_clearance(conn, source_id,
                                     granted_by=granted_by,
                                     evidence=evidence, scope=scope)
    except watcher_mod.WatcherError as e:
        _die(str(e))
    print("clearance recorded")


@source_grp.command("list")
@click.option("--campaign", default=None)
def source_list(campaign):
    conn = _conn()
    q = "SELECT * FROM sources" + (" WHERE campaign_id=?" if campaign else "")
    for s in conn.execute(q, (campaign,) if campaign else ()):
        print(f"{s['id']}  {s['kind']}  {s['title'] or s['url'] or ''}  "
              f"auth={s['authorization']}")


COMMANDS.append(source_grp)


# ------------------------------------------------------------------ watch

@_cmd(name="watch")
@click.option("--once", is_flag=True, default=False,
              help="Poll once and exit.")
@click.option("--campaign", default=None, help="Only this campaign.")
def watch(once, campaign):
    """Poll due sources for new items (creates queued_ingest jobs)."""
    conn = _conn()
    while True:
        try:
            new = watcher_mod.poll(conn, campaign_id=campaign)
        except watcher_mod.WatcherError as e:
            _die(str(e))
        print(f"watch: {len(new)} new item(s)")
        if once:
            return
        time.sleep(60)


# ------------------------------------------------------------------ moments

@_cmd(name="moments")
@click.argument("job_id")
@click.option("--limit", type=int, default=10, show_default=True)
def moments(job_id, limit):
    """List a scored job's moments, ranked (numbers feed `cut`)."""
    conn = _conn()
    rows = conn.execute(
        "SELECT id, t_in, t_out, score, confidence, weight_version"
        " FROM moments WHERE job_id=? ORDER BY score DESC LIMIT ?",
        (job_id, limit),
    ).fetchall()
    if not rows:
        _die(f"no moments for job {job_id} (run the worker first)")
    for i, m in enumerate(rows, 1):
        print(f"{i:>3}  {m['t_in']:7.1f}-{m['t_out']:7.1f}s  "
              f"score={m['score']:.3f} conf={m['confidence']:.2f} "
              f"w={m['weight_version']}  {m['id']}")


# ------------------------------------------------------------------ cut

@_cmd(name="cut")
@click.argument("job_id")
@click.argument("numbers", nargs=-1, required=True)
@click.option("--reframe-mode", default="auto",
              type=click.Choice(["auto", "static", "track", "split",
                                 "blurpad"]))
@click.option("--work-minutes", type=float, default=None,
              help="Operator-logged minutes for this cut batch.")
def cut(job_id, numbers, reframe_mode, work_minutes):
    """Cut compliant 9:16 clips from numbered moments (see `moments`)."""
    conn = _conn()
    rows = conn.execute(
        "SELECT id FROM moments WHERE job_id=? ORDER BY score DESC",
        (job_id,)).fetchall()
    ids = []
    for n in numbers:
        try:
            idx = int(n) - 1
        except ValueError:
            _die(f"not a moment number: {n!r}")
        if not 0 <= idx < len(rows):
            _die(f"moment #{n} out of range (1-{len(rows)})")
        ids.append(rows[idx]["id"])
    try:
        res = cut_mod.cut(conn, job_id, ids, root=_root(),
                          reframe_mode=reframe_mode,
                          work_minutes=work_minutes)
    except (cut_mod.CutError, ValueError) as e:
        _die(str(e))
    for c in res["clips"]:
        print(f"{c['id']}  {c['state']}  reframe={c['reframe_mode']}  "
              f"{c['path']}")
    print(f"job -> {res['job_state']}")


# ------------------------------------------------------------------ tray

@_cmd(name="tray")
@click.argument("job_id", required=False)
def tray(job_id):
    """Build the upload tray (ranked compliant clips + captions + links)."""
    conn = _conn()
    if job_id:
        job_ids = [job_id]
    else:
        job_ids = [r["id"] for r in conn.execute(
            "SELECT id FROM jobs WHERE state='tray'")]
    if not job_ids:
        _die("no jobs in tray state")
    for jid in job_ids:
        try:
            ranked = tray_mod.build_tray(conn, jid, _root())
        except tray_mod.TrayError as e:
            _die(str(e))
        for c in ranked:
            slug = f"clip_{c['tray_rank']:04d}"
            print(f"{slug}  predicted={c['predicted']:.3f}  {c['id']}")


# ------------------------------------------------------------------ posted

@_cmd(name="posted")
@click.argument("clip_id")
@click.argument("post_url")
@click.option("--platform", required=True)
@click.option("--by", "operator", default="")
def posted(clip_id, post_url, platform, operator):
    """Record a manual upload (re-gates compliance if rules changed)."""
    conn = _conn()
    try:
        res = cut_mod.record_posted(conn, clip_id, post_url, platform,
                                    operator=operator)
    except (cut_mod.CutError, ValueError) as e:
        _die(str(e))
    if res.get("regated") and not res.get("passed"):
        _die(f"re-gate at submission failed: clip -> {res['state']}")
    print(f"posted {res['post_id']} at {res['posted_at']}")


# ------------------------------------------------------------------ review

@click.group("review", invoke_without_command=True)
@click.option("--job", "job_id", default=None)
@click.pass_context
def review_grp(ctx, job_id):
    """List clips routed to human review (compliance UNKNOWN)."""
    if ctx.invoked_subcommand is None:
        conn = _conn()
        q = ("SELECT c.id, c.job_id, c.path, cl.unknown_reasons"
             " FROM clips c JOIN compliance_log cl ON cl.clip_id=c.id"
             " WHERE c.state='compliance_unknown'"
             " AND cl.decided_by='machine'")
        args: tuple = ()
        if job_id:
            q += " AND c.job_id=?"
            args = (job_id,)
        q += " ORDER BY cl.at DESC"
        seen = set()
        n = 0
        for r in conn.execute(q, args):
            if r["id"] in seen:
                continue
            seen.add(r["id"])
            n += 1
            print(f"{r['id']}  job={r['job_id']}\n"
                  f"  unknown: {r['unknown_reasons']}\n  {r['path']}")
        if not n:
            print("no clips awaiting review")


@review_grp.command("resolve")
@click.argument("clip_id")
@click.option("--decision", required=True,
              type=click.Choice(["pass", "fail"]))
@click.option("--by", "operator", required=True)
@click.option("--note", default="")
def review_resolve(clip_id, decision, operator, note):
    """Human resolution of a compliance_unknown clip."""
    conn = _conn()
    try:
        res = compliance_mod.resolve(conn, clip_id, operator, decision,
                                     note=note)
    except compliance_mod.ComplianceError as e:
        _die(str(e))
    print(f"{res['clip_id']} -> {res['state']} "
          f"({res['remaining_unknown']} unknown left)")


COMMANDS.append(review_grp)


# ------------------------------------------------------------------ measure

@_cmd(name="measure")
def measure():
    """Poll metrics for open posts (provenance recorded per row)."""
    conn = _conn()
    rows = metrics_mod.poll_metrics(conn)
    for r in rows:
        print(f"{r['post_id']}  {r['provenance']}  views={r.get('views')}")
    if not rows:
        print("no open posts")


@_cmd(name="worked")
@click.argument("dimension", required=False)
def worked(dimension):
    """Attribution: what correlated with views (correlations only).

    Dimensions below n=30 are listed as below-threshold, never read as
    signal. Run `measure` first; attribution reads calibration-grade
    metrics (official_api + provider_api) only.
    """
    conn = _conn()
    n = attribution_mod.attribute(conn)
    print(f"attributed {n} (dimension, value) bucket(s)")
    dims = attribution_mod.read_dimensions(conn)
    rows = dims["signal"]
    if dimension:
        rows = [r for r in rows if r["dimension"] == dimension]
    for r in rows:
        print("  " + attribution_mod.describe_row(r))
    if dims["below_threshold"]:
        print(f"  ({len(dims['below_threshold'])} bucket(s) below n=30: "
              "listed, not interpreted)")


# ------------------------------------------------------------------ weights

@_cmd(name="propose-weights")
def propose_weights():
    """Propose a re-weighting (refuses below n=50 measured posts)."""
    conn = _conn()
    try:
        res = attribution_mod.propose_weights(conn, WEIGHTS_DIR)
    except attribution_mod.AttributionError as e:
        _die(str(e))
    print(f"proposal written: {res['path']} (status: proposed, NOT applied)")
    for k, why in res["basis"].items():
        print(f"  {k}: {why}")


@_cmd(name="promote-weights")
@click.argument("candidate")
@click.option("--by", "operator", required=True)
def promote_weights(candidate, operator):
    """Explicit operator approval: promote a proposal to weights_v2.json."""
    try:
        res = attribution_mod.promote_weights(WEIGHTS_DIR, candidate,
                                              operator)
    except attribution_mod.AttributionError as e:
        _die(str(e))
    print(f"promoted: {res['path']} by {res['approved_by']}")


# ------------------------------------------------------------------ register

def register(cli: click.Group) -> None:
    """Attach every Book 2 command to the main hypelab group."""
    for c in COMMANDS:
        cli.add_command(c)
