# S2 — as-is architecture of the render output path

## Call chain (verified by reading source at HEAD 5c185ba)

```
hypelab/cli.py::_render_job(conn, job_id, aspect, heartbeat_owner)
  ├─ out = work/out/{slug}.mp4            (cli.py ~700; shared final path)
  ├─ heartbeat thread (daemon, 60s): queue_mod.heartbeat(c2, job_id, owner)
  │    on False: print "heartbeat lost … lease expired"; break   (cli.py ~711-724)
  │    NOTE: the render is NOT aborted (true per the finding; retained by
  │    chief decision — scheduling semantics unchanged).
  └─ render_mod.render(edl, work, out, conn, job_id, provenance)  (render.py:440)
       ├─ slots-filled gate (RenderError before ffmpeg)          (render.py:468)
       ├─ tmp = out.with_name(f"{out.stem}.partial-{os.getpid()}{out.suffix}")
       │                                                     (render.py:486)
       ├─ cmd, rhash = build_command(edl, work, tmp, ...)    (render.py:487)
       │    └─ build_command puts ["ffmpeg","-y",… , str(out)] with out=tmp
       │       → the `-y` clobber applies ONLY to the PID-unique temp file
       │       (render.py:349-397). Single production caller (grep-verified);
       │       the only other caller is tests/test_pipeline.py:244.
       ├─ render-hash skip (unchanged behavior)              (render.py:493)
       ├─ subprocess.run(cmd) → ffmpeg writes tmp only       (render.py:509)
       ├─ on nonzero exit: tmp.unlink(missing_ok=True); raise (render.py:515)
       ├─ ffprobe(tmp) must validate, else unlink + raise    (render.py:519)
       ├─ os.replace(tmp, out)  ← the ONLY write to the final path; atomic
       │                                                     (render.py:522)
       └─ manifest record_render (atomic tmp+fsync+replace JSON write;
          concurrent appends can lose one entry but cannot tear the file)
```

`derive()` (preview path, render.py ~590-625) uses the same tmp+os.replace
pattern for `work/preview_<aspect>.mp4`.

## Two-worker (lease-loss) scenario, traced

Worker A loses lease (heartbeat thread dead: any exception in
queue_mod.heartbeat kills the daemon thread silently — no except in _beat).
Reaper reclaims; worker B starts the same job. Both are separate OS
processes → distinct PIDs → distinct temp files
`{slug}.partial-<pidA>.mp4` / `{slug}.partial-<pidB>.mp4` in the same
`work/out/` dir. Neither ffmpeg process ever opens the shared `out`.
Completion order decides the final file via atomic rename; readers (gates)
see either the old complete file or the new complete file — rename(2) is
atomic. A SIGKILLed worker's orphaned ffmpeg keeps writing its own temp
file only (comment at render.py:483-485; exercised by the T-044 crash test).

## Authoritative invariants

- The final output path is written exclusively by `os.replace` (POSIX atomic).
- `-y` exists in the argv but its target is always the private temp file
  (needed for PID-reuse collisions on stale temps).
- Stale `.partial-<pid>.mp4` orphans can accumulate after SIGKILL; they are
  never read (no code globs them back) and never renamed (PID-unique).
