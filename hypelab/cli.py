"""hypelab CLI — thin client over services.py. No business logic here.

Usage:  python3 -m hypelab.cli <command> [args]
"""
from __future__ import annotations
import argparse
import json
import sys

from .services import Services

def _svc() -> Services:
    return Services()

def cmd_kit(args):
    s = _svc()
    if args.op == "new":
        overrides = {}
        if args.appearance:
            overrides["appearance_text"] = args.appearance
        kid, ver = s.kits.new(args.name, **overrides)
        print(f"kit {kid} @v{ver}")
    elif args.op == "show":
        print(json.dumps(s.kits.get(args.id), indent=1))
    elif args.op == "bump":
        ver = s.kits.bump(args.id)
        print(f"kit {args.id} bumped to v{ver}")
    elif args.op == "list":
        for k in s.kits.list():
            print(f"{k['id']}  {k['name']}  v{k['version']}  ({k['owner']})")

def cmd_new(args):
    s = _svc()
    job = s.new_job(args.kit, args.script, args.title or "untitled", mode="original")
    print(f"job {job['id']}  state={job['state']}")

def cmd_shots(args):
    for p in _svc().shots(args.job):
        print(p)
        print("---")

def cmd_attach(args):
    rec = _svc().attach(args.job, args.slot, args.file, args.provenance)
    print(f"attached {rec['slot']} -> {rec['path']}  sha256={rec['sha256'][:16]}…  "
          f"({rec['kind']}, {rec['bytes']} bytes)")

def cmd_align(args):
    t = _svc().align(args.job, whisper_model=args.model)
    print(f"task {t['id']} ({t['state']}) — run 'hypelab work --once' to execute")

def cmd_plan(args):
    t = _svc().plan(args.job, aspect=args.aspect)
    print(f"task {t['id']} ({t['state']})")

def cmd_render(args):
    t = _svc().render(args.job, aspects=args.aspect.split(","))
    print(f"task {t['id']} ({t['state']})")

def cmd_gates(args):
    t = _svc().gates(args.job)
    print(f"task {t['id']} ({t['state']})")

def cmd_work(args):
    from .worker import main as worker_main
    sys.argv = ["worker"] + (["--once"] if args.once else []) + \
               (["--worker", args.worker] if args.worker else [])
    worker_main()

def cmd_show(args):
    job = _svc().get_job(args.job)
    print(json.dumps({k: job[k] for k in
                      ("id", "mode", "state", "title", "error")}, indent=1))
    for t in job["tasks"]:
        print(f"  task {t['id'][:14]} {t['kind']:10} {t['state']:7} "
              f"attempts={t['attempts']}")
    for a in job["assets"]:
        print(f"  asset {a['slot']:12} {a['kind']:6} {a['provenance']}")

def cmd_pitch(args):
    print(json.dumps(_svc().pitch(args.job, args.target, args.platform), indent=1))

def cmd_consent(args):
    s = _svc()
    if args.op == "grant":
        rec = s.consent_grant(args.job, args.target, args.platform,
                              args.scope, args.evidence, args.expiry)
        print(f"consent {rec['id']} recorded for @{args.target} "
              f"(asset {rec['asset_version'][:12]}…, expires {rec['expiry']})")
    elif args.op == "revoke":
        from .consent import Consents
        Consents().revoke(args.id)
        print(f"consent {args.id} revoked")

def cmd_publish(args):
    try:
        r = _svc().publish(args.job, args.target, args.platform,
                           collaborators=args.collaborators or [],
                           dry_run=not args.real, i_confirm=args.i_confirm)
    except Exception as ex:
        print(f"REFUSED: {ex}")
        sys.exit(3)
    print(f"dry_run={r['dry_run']} ok={r['ok']}\n{r['detail']}")

def cmd_costs(args):
    print(json.dumps(_svc().costs(args.job), indent=1))

def cmd_cancel(args):
    _svc().cancel(args.job)
    print(f"job {args.job} cancelled")

def cmd_retry(args):
    _svc().retry_task(args.task)
    print(f"task {args.task} requeued")

def cmd_backup(args):
    print(_svc().backup())

def cmd_doctor(args):
    print(json.dumps(_svc().doctor(), indent=1))

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="hypelab", description="HypeLab v2 CLI (thin client)")
    sub = p.add_subparsers(dest="cmd", required=True)

    k = sub.add_parser("kit"); k.add_argument("op", choices=["new", "show", "bump", "list"])
    k.add_argument("id", nargs="?"); k.add_argument("--name", default="demo")
    k.add_argument("--appearance", default=""); k.set_defaults(fn=cmd_kit)

    n = sub.add_parser("new"); n.add_argument("kit"); n.add_argument("--script", required=True)
    n.add_argument("--title", default=""); n.set_defaults(fn=cmd_new)

    s = sub.add_parser("shots"); s.add_argument("job"); s.set_defaults(fn=cmd_shots)

    a = sub.add_parser("attach"); a.add_argument("job"); a.add_argument("slot"); a.add_argument("file")
    a.add_argument("--provenance", default="supplied"); a.set_defaults(fn=cmd_attach)

    al = sub.add_parser("align"); al.add_argument("job")
    al.add_argument("--model", default="tiny"); al.set_defaults(fn=cmd_align)

    pl = sub.add_parser("plan"); pl.add_argument("job")
    pl.add_argument("--aspect", default="9:16"); pl.set_defaults(fn=cmd_plan)

    r = sub.add_parser("render"); r.add_argument("job")
    r.add_argument("--aspect", default="9:16"); r.set_defaults(fn=cmd_render)

    g = sub.add_parser("gates"); g.add_argument("job"); g.set_defaults(fn=cmd_gates)

    w = sub.add_parser("work"); w.add_argument("--once", action="store_true")
    w.add_argument("--worker", default=""); w.set_defaults(fn=cmd_work)

    sh = sub.add_parser("show"); sh.add_argument("job"); sh.set_defaults(fn=cmd_show)

    pt = sub.add_parser("pitch"); pt.add_argument("job"); pt.add_argument("--target", required=True)
    pt.add_argument("--platform", default="instagram"); pt.set_defaults(fn=cmd_pitch)

    c = sub.add_parser("consent"); c.add_argument("op", choices=["grant", "revoke"])
    c.add_argument("--job", default=""); c.add_argument("--target", default="")
    c.add_argument("--platform", default="instagram"); c.add_argument("--scope", default="collab_post:instagram")
    c.add_argument("--evidence", default=""); c.add_argument("--expiry", default="")
    c.add_argument("--id", default=""); c.set_defaults(fn=cmd_consent)

    pb = sub.add_parser("publish"); pb.add_argument("job")
    pb.add_argument("--target", required=True); pb.add_argument("--platform", default="instagram")
    pb.add_argument("--collaborators", nargs="*", default=[])
    pb.add_argument("--real", action="store_true",
                    help="attempt a REAL publish (requires --i-confirm + consent + credentials)")
    pb.add_argument("--i-confirm", action="store_true"); pb.set_defaults(fn=cmd_publish)

    co = sub.add_parser("costs"); co.add_argument("--job", default=None); co.set_defaults(fn=cmd_costs)
    ca = sub.add_parser("cancel"); ca.add_argument("job"); ca.set_defaults(fn=cmd_cancel)
    rt = sub.add_parser("retry"); rt.add_argument("task"); rt.set_defaults(fn=cmd_retry)
    b = sub.add_parser("backup"); b.set_defaults(fn=cmd_backup)
    d = sub.add_parser("doctor"); d.set_defaults(fn=cmd_doctor)
    return p

def main() -> None:
    args = build_parser().parse_args()
    args.fn(args)

if __name__ == "__main__":
    main()
