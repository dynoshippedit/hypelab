"""HypeLab Book 3 (Hype Layer) CLI commands.

Registered onto the main ``hypelab`` click group by cli.py (Book 3's
commands live here so Book 1's cli.py diff stays a small registration).

Conventions mirror cli.py / b2cli.py: HYPELAB_DB / HYPELAB_ROOT env
overrides, errors via _die to stderr with a nonzero exit. No external
side effect without a recorded authorization row — enforced in the
modules, not just the CLI.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import click

from hypelab import authorize as authorize_mod
from hypelab import carousel as carousel_mod
from hypelab import consent as consent_mod
from hypelab import feedback as feedback_mod
from hypelab import invites as invites_mod
from hypelab import jobs as jobs_mod
from hypelab import kits as kits_mod
from hypelab import pitch as pitch_mod
from hypelab import publish as publish_mod
from hypelab import db as db_mod
from hypelab.util import work_dir as _work_dir

DEFAULT_ROOT = "/home/dino/hypelab"

COMMANDS: list[click.BaseCommand] = []


def _die(msg, code=1):
    print(f"error: {msg}", file=sys.stderr)
    raise SystemExit(code)


def _root():
    return os.environ.get("HYPELAB_ROOT", DEFAULT_ROOT)


def _conn():
    return db_mod.connect(os.environ.get("HYPELAB_DB") or None)


def _cmd(name=None, **kw):
    def deco(f):
        cmd = click.command(name, **kw)(f)
        COMMANDS.append(cmd)
        return cmd
    return deco


def _get_job(conn, job_id):
    job = jobs_mod.get(conn, job_id)
    if job is None:
        _die(f"unknown job {job_id}")
    return job


def _kit_or_die(conn, kit_id):
    try:
        return kits_mod.load(conn, kit_id)
    except Exception as e:
        _die(f"cannot load kit {kit_id!r}: {e}")


# ---------------------------------------------------------------- authorize

@_cmd("authorize")
@click.argument("job_id")
@click.argument("action")
@click.option("--actor", default="dino", show_default=True)
@click.option("--platform", default=None)
@click.option("--intent", default=None, help="operator-stated intent, verbatim")
@click.option("--note", default=None)
def authorize_cmd(job_id, action, actor, platform, intent, note):
    """Record an authorization row: hypelab authorize JOB_ID pitch|publish|invite."""
    conn = _conn()
    try:
        row = authorize_mod.record(conn, job_id, action, actor=actor,
                                   platform=platform, intent=intent, note=note)
    except authorize_mod.AuthorizationError as e:
        _die(str(e))
    click.echo(f"authorized: {row['id']}  {action} on {job_id} by {actor} "
               f"at {row['authorized_at']}")


# ---------------------------------------------------------------- carousel

@_cmd("carousel")
@click.option("--job", "job_id", default=None)
@click.option("--spec", "spec_path", required=True,
              help="carousel spec JSON (7 slides)")
@click.option("--kit", "kit_id", default="cerebratico", show_default=True)
@click.option("--title", default="carousel")
def carousel_cmd(job_id, spec_path, kit_id, title):
    """Render a 7-slide 1080x1350 carousel (gates run first)."""
    conn = _conn()
    spec = json.loads(Path(spec_path).read_text(encoding="utf-8"))
    kit = _kit_or_die(conn, kit_id)
    if job_id is None:
        job_id = jobs_mod.new(conn, mode="carousel", kit_id=kit_id,
                              title=title, state="ready")
        conn.commit()
        click.echo(f"job {job_id} (mode=carousel, state=ready)")
    else:
        _get_job(conn, job_id)
    out_dir = Path(_work_dir(job_id, root=_root())) / "carousel"
    try:
        pngs = carousel_mod.render_carousel(spec, kit, out_dir,
                                            conn=conn, job_id=job_id)
        jpegs = carousel_mod.export_jpeg(pngs)
    except carousel_mod.CarouselError as e:
        _die(str(e))
    click.echo(f"rendered {len(pngs)} slides at 1080x1350 -> {out_dir}")
    click.echo(f"jpeg export: {len(jpegs)} files; audio_map.json: 2s/slide")


# ---------------------------------------------------------------- publish

@_cmd("publish")
@click.option("--job", "job_id", required=True)
@click.option("--platform", default="instagram", show_default=True)
@click.option("--collab", "collabs", multiple=True,
              help="collaborator handle (repeatable)")
@click.option("--media", "media", multiple=True, required=True,
              help="media file path (repeatable)")
@click.option("--caption", default="")
@click.option("--adapter", "adapter_name", default="dryrun", show_default=True)
@click.option("--live", is_flag=True, default=False,
              help="attempt the live path (Dino-gated: refuses without "
                   "authorization + credentials)")
def publish_cmd(job_id, platform, collabs, media, caption, adapter_name,
                live):
    """Publish a job's asset. dry_run (default) records against fixtures
    and makes zero live calls. --live refuses: the live path is Dino-gated."""
    conn = _conn()
    _get_job(conn, job_id)
    if live:
        _die("live publishing is Dino-gated: it needs an explicit "
             "authorization row AND provider credentials, neither of which "
             "exists in this build. Refusing — no live call was made.")
    try:
        res = publish_mod.publish_job(
            conn, job_id, platform=platform,
            collaborators=list(collabs), caption=caption,
            media=list(media), adapter_name=adapter_name, dry_run=True)
    except (publish_mod.PublishError,
            authorize_mod.AuthorizationError,
            consent_mod.ConsentError) as e:
        _die(str(e))
    click.echo(f"DRY RUN placement {res['placement_id']} "
               f"(adapter={res['adapter']}, provider_post_id={res['provider_post_id']})")
    click.echo(f"consent re-check: {res['consent_detail']}")
    click.echo("zero live calls made — recorded against fixtures only")


# ---------------------------------------------------------------- consent

@_cmd("consent")
@click.argument("op", type=click.Choice(["grant", "revoke", "check", "export"]))
@click.option("--job", "job_id", default=None)
@click.option("--handle", default=None)
@click.option("--platform", default="instagram", show_default=True)
@click.option("--actor", default=None, help="who granted (handle + channel)")
@click.option("--account", "account_id", default=None,
              help="account the grant covers")
@click.option("--scope", default=None, help="verbatim scope of the grant")
@click.option("--artifact", "artifact_path", default=None,
              help="consent artifact file (hashed at grant time)")
@click.option("--expires", "expires_at", default=None,
              help="expiry timestamp (MANDATORY for grant)")
@click.option("--jurisdiction", default=None)
@click.option("--terms", "terms_version", default=None)
@click.option("--id", "consent_id", default=None, help="consent id (revoke)")
@click.option("--note", default=None)
@click.option("--asset-sha256", "asset_sha256", default=None,
              help="optional: verify the consent artifact you hold matches "
                   "the hash pinned at grant time (check op)")
@click.option("--out", "out_path", default="consent_ledger.csv")
def consent_cmd(op, job_id, handle, platform, actor, account_id, scope,
               artifact_path, expires_at, jurisdiction, terms_version,
               consent_id, note, asset_sha256, out_path):
    """Consent ledger: grant | revoke | check | export."""
    conn = _conn()
    if op == "grant":
        for name, v in (("job", job_id), ("handle", handle),
                        ("actor", actor), ("account", account_id),
                        ("scope", scope), ("artifact", artifact_path),
                        ("expires", expires_at)):
            if not v:
                _die(f"consent grant needs --{name}")
        try:
            row = consent_mod.grant(
                conn, job_id=job_id, handle=handle, platform=platform,
                actor=actor, account_id=account_id, scope=scope,
                artifact_path=artifact_path, expires_at=expires_at,
                jurisdiction=jurisdiction, terms_version=terms_version)
        except consent_mod.ConsentError as e:
            _die(str(e))
        click.echo(f"consent {row['id']}: granted, artifact "
                   f"sha256={row['artifact_hash'][:16]}…, expires {expires_at}")
    elif op == "revoke":
        if not consent_id:
            _die("consent revoke needs --id")
        try:
            row = consent_mod.revoke(conn, consent_id, actor or "dino", note)
        except consent_mod.ConsentError as e:
            _die(str(e))
        click.echo(f"consent {consent_id} revoked at {row['revoked_at']}")
        if row.get("knocked_back"):
            click.echo("knocked back to consent_granted: "
                       + ", ".join(row["knocked_back"]))
    elif op == "check":
        for name, v in (("job", job_id), ("handle", handle)):
            if not v:
                _die(f"consent check needs --{name.replace('_', '-')}")
        c = consent_mod.valid_for(conn, job_id, handle, platform)
        if c and asset_sha256 and asset_sha256 != c["artifact_hash"]:
            # Optional evidence cross-check: the caller can verify that the
            # artifact they hold is the one pinned at grant time. A mismatch
            # fails closed — the evidence does not match the ledger.
            _die("consent evidence mismatch: --asset-sha256 does not match "
                 f"the pinned artifact hash {c['artifact_hash'][:16]}…")
        if c:
            click.echo(f"VALID: {c['id']} (granted {c['responded_at']}, "
                       f"expires {c['expiry']}, scope: {c['scope'][:60]}…)")
        else:
            _die("NO valid consent (granted, unrevoked, unexpired) on file")
    elif op == "export":
        out = consent_mod.export_ledger(conn, out_path)
        n = conn.execute("SELECT COUNT(*) c FROM consents").fetchone()["c"]
        click.echo(f"exported {n} consent row(s) -> {out}")


# ---------------------------------------------------------------- pitch

@_cmd("pitch")
@click.argument("op", type=click.Choice(["new", "list", "outcome", "tripwire"]))
@click.option("--job", "job_id", default=None)
@click.option("--target", "handle", default=None)
@click.option("--platform", default="instagram", show_default=True)
@click.option("--angle", default="")
@click.option("--id", "attempt_id", default=None)
@click.option("--outcome", default=None,
              type=click.Choice(list(pitch_mod.OUTCOMES)))
@click.option("--note", default=None)
def pitch_cmd(op, job_id, handle, platform, angle, attempt_id, outcome,
              note):
    """Pitch generator: new | list | outcome | tripwire."""
    conn = _conn()
    if op == "new":
        if not job_id or not handle:
            _die("pitch new needs --job and --target")
        try:
            att = pitch_mod.make_pitch(conn, job_id, handle,
                                       platform=platform, angle=angle)
        except (pitch_mod.PitchError,
                authorize_mod.AuthorizationError) as e:
            _die(str(e))
        click.echo(f"pitch {att['id']} -> {handle} "
                   f"(job {job_id}: ready -> pitch_sent -> awaiting_consent)")
    elif op == "list":
        for a in pitch_mod.list_attempts(conn, job_id):
            click.echo(f"{a['id']}  {a['handle']}  {a['outcome']}  "
                       f"sent {a['sent_at']}")
    elif op == "outcome":
        if not attempt_id or not outcome:
            _die("pitch outcome needs --id and --outcome")
        try:
            att = pitch_mod.record_pitch_outcome(conn, attempt_id, outcome,
                                                 note)
        except pitch_mod.PitchError as e:
            _die(str(e))
        click.echo(f"pitch {attempt_id}: {att['outcome']}")
    elif op == "tripwire":
        st = pitch_mod.kill_threshold_status(conn)
        click.echo(f"pitches={st['pitches']} accepts={st['accepts']} "
                   f"tripwire={st['tripwire']}")
        click.echo(f"label: {st['label']}")
        click.echo(f"tripped: {st['tripped']}")


# ---------------------------------------------------------------- invite

@_cmd("invite")
@click.argument("op", type=click.Choice(["add", "poll"]))
@click.option("--post", "post_id", default=None)
@click.option("--handle", default=None)
@click.option("--job", "job_id", default=None)
@click.option("--adapter", "adapter_name", default="dryrun", show_default=True)
def invite_cmd(op, post_id, handle, job_id, adapter_name):
    """Invite tracking: add | poll."""
    conn = _conn()
    if op == "add":
        if not post_id or not handle or not job_id:
            _die("invite add needs --post, --handle and --job")
        try:
            inv = invites_mod.add(conn, post_id, handle, job_id)
        except (invites_mod.InviteError,
                authorize_mod.AuthorizationError) as e:
            _die(str(e))
        click.echo(f"invite {inv['id']}: {handle} pending on post {post_id}")
    elif op == "poll":
        adapter = publish_mod.get_adapter(adapter_name)
        changed = invites_mod.poll(conn, adapter)
        if not changed:
            click.echo("no invite status changes")
        for c in changed:
            click.echo(f"{c['handle']}: -> {c['invite_status']}")


# ---------------------------------------------------------------- feedback

@_cmd("feedback")
def feedback_cmd():
    """Run feed_back: attribute measured outcomes into what_worked."""
    conn = _conn()
    res = feedback_mod.feed_back(conn)
    click.echo(f"feed_back: {res['rows_consumed']} measured posts, "
               f"{res['buckets']} buckets upserted")


# ---------------------------------------------------------------- priors

@_cmd("priors")
@click.option("--min-n", "min_n", default=feedback_mod.MIN_N, show_default=True)
@click.option("--snapshot", is_flag=True, default=False,
              help="write versioned priors/priors_v<N>.json")
@click.option("--dimension", default=None)
def priors_cmd(min_n, snapshot, dimension):
    """Show production priors (min_n guard enforced; below-guard rows are
    listed as NOT APPLIED, never used)."""
    conn = _conn()
    data = feedback_mod.priors(conn, min_n)
    dims = [dimension] if dimension else sorted(data)
    for dim in dims:
        for r in data.get(dim, []):
            flag = "APPLIED" if r["applied"] else "not applied (n<min_n)"
            click.echo(f"{dim:20s} {r['value']:12s} n={r['n']:3d} "
                       f"mean={r['mean_perf']}  {flag}")
    if snapshot:
        out = feedback_mod.snapshot_priors(conn, _root(), min_n)
        click.echo(f"snapshot -> {out}")


def register(cli):
    for cmd in COMMANDS:
        cli.add_command(cmd)
