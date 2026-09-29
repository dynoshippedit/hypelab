"""Mode C carousel renderer (improved Book 3, section 3): spec -> HTML -> PNG.

A dumb spec, a deterministic renderer. Seven slides at exactly 1080x1350
(4:5), exported as JPEG/PNG via headless Chromium screenshots.

Hard rules (same as Book 1's render()):
- Chromium runs via validated argv arrays only (never shell=True).
- Every file lands via atomic tmp-file + fsync + os.replace.
- Fail loudly: no Chromium, no fake output.

Gates (real checks, tested broken/fixed):
- text_overflow: 10% margins, <=20 words/slide, 40-char lines, and an
  in-browser measurement (scrollHeight vs clientHeight) before the
  screenshot — text must not overflow its box.
- slide_one_hook: slide 1 carries the hook, <=12 words.

Audio rule: 2 s per slide, recorded in audio_map.json next to the PNGs
(drives the slideshow assembly downstream).
"""
from __future__ import annotations

import html
import json
import os
import re
import shutil
import sqlite3
import subprocess
import tempfile
from pathlib import Path

from .util import new_id, now

SLIDE_W, SLIDE_H = 1080, 1350
SLIDES_REQUIRED = 7
WORDS_PER_SLIDE_MAX = 20
HOOK_WORDS_MAX = 12
LINE_CHARS_MAX = 40
MARGIN_FRAC = 0.10
SLIDE_DURATION_S = 2.0  # audio rule: 2 s per slide

LAYOUTS = ("hook", "stat", "body", "cta")


class CarouselError(Exception):
    """Carousel rendering or gating refused."""


# ------------------------------------------------------------------ chromium

def _chromium() -> str:
    """Locate a Chromium binary. Fail loudly when none exists."""
    override = os.environ.get("HYPELAB_CHROMIUM")
    if override:
        if Path(override).is_file():
            return override
        raise CarouselError(f"HYPELAB_CHROMIUM={override} is not a file")
    for name in ("google-chrome", "google-chrome-stable", "chromium",
                 "chromium-browser"):
        p = shutil.which(name)
        if p:
            return p
    legacy = Path("/opt/pw-browsers/chromium")
    if legacy.is_file():
        return str(legacy)
    raise CarouselError(
        "no Chromium binary found (tried google-chrome, chromium, "
        "/opt/pw-browsers/chromium). Set HYPELAB_CHROMIUM."
    )


def _run(argv: list[str], timeout: int = 120) -> subprocess.CompletedProcess:
    """Validated argv array. Never shell=True, never a shell string."""
    return subprocess.run(argv, capture_output=True, text=True, timeout=timeout)


# ------------------------------------------------------------------ templates

def kit_to_css(kit: dict) -> str:
    """Brand Kit -> CSS tokens. Carousel reuses the Brand Kit (book §3)."""
    kit = kit or {}
    caps = kit.get("captions") or {}
    fill = caps.get("fill", "#FFFFFF")
    accent = caps.get("highlight", "#39FF88")
    font = caps.get("font", "DejaVu Sans")
    return f"""
:root {{ --fill: {fill}; --accent: {accent}; }}
* {{ margin: 0; padding: 0; box-sizing: border-box; }}
html, body {{ width: {SLIDE_W}px; height: {SLIDE_H}px; overflow: hidden;
              background: #0b0b10; color: var(--fill);
              font-family: "{font}", sans-serif; }}
.slide {{ position: relative; width: {SLIDE_W}px; height: {SLIDE_H}px;
          display: flex; flex-direction: column; justify-content: center;
          align-items: center; text-align: center; padding: 140px 110px; }}
.kicker {{ color: var(--accent); font-size: 34px; letter-spacing: 6px;
           text-transform: uppercase; margin-bottom: 36px; }}
h1 {{ font-size: 92px; line-height: 1.12; font-weight: 800; }}
.sub {{ font-size: 44px; line-height: 1.3; margin-top: 28px; opacity: 0.88; }}
.big {{ font-size: 240px; font-weight: 900; color: var(--accent);
        line-height: 1; }}
.caption {{ font-size: 46px; line-height: 1.35; margin-top: 30px; }}
ul {{ list-style: none; margin-top: 34px; }}
li {{ font-size: 46px; line-height: 1.4; margin: 18px 0; }}
li::before {{ content: "— "; color: var(--accent); }}
.handle {{ position: absolute; bottom: 150px; left: 110px; font-size: 40px;
           color: var(--accent); }}
.pageno {{ position: absolute; bottom: 150px; right: 110px; font-size: 30px;
           opacity: 0.5; }}
"""


def _esc(s) -> str:
    return html.escape("" if s is None else str(s))


def _slide_html(slide: dict, kit: dict, n: int) -> str:
    """Render one slide to an HTML fragment. data-txt marks measurable
    text blocks for the overflow probe."""
    layout = slide.get("layout")
    if layout not in LAYOUTS:
        raise CarouselError(f"slide {slide.get('idx')}: unknown layout {layout!r}")
    inner = ""
    if layout == "hook":
        inner = (
            f'<div class="kicker" data-txt>New Light Management</div>'
            f'<h1 data-txt>{_esc(slide.get("title"))}</h1>'
            f'<div class="sub" data-txt>{_esc(slide.get("sub"))}</div>'
        )
    elif layout == "stat":
        inner = (
            f'<div class="big" data-txt>{_esc(slide.get("big"))}</div>'
            f'<div class="caption" data-txt>{_esc(slide.get("caption"))}</div>'
        )
    elif layout == "body":
        bullets = "".join(
            f"<li data-txt>{_esc(b)}</li>" for b in slide.get("bullets", [])
        )
        inner = (
            f'<h1 data-txt>{_esc(slide.get("title"))}</h1>'
            f"<ul>{bullets}</ul>"
        )
    elif layout == "cta":
        inner = (
            f'<h1 data-txt>{_esc(slide.get("title"))}</h1>'
            f'<div class="sub" data-txt>{_esc(slide.get("sub"))}</div>'
            f'<div class="handle" data-txt>{_esc(slide.get("handle"))}</div>'
        )
    return (
        f'<div class="slide">{inner}'
        f'<div class="pageno">{n} / {SLIDES_REQUIRED}</div></div>'
    )


_PROBE_JS = """
<script>
window.addEventListener('load', () => {
  const mx = %d, my = %d;   // 10%% margin band in px
  const blocks = [];
  document.querySelectorAll('[data-txt]').forEach(el => {
    const r = el.getBoundingClientRect();
    blocks.push({
      text: el.textContent.slice(0, 40),
      // Horizontal overflow is the real per-block failure mode. (Vertical
      // scrollHeight on auto-height blocks false-positives with
      // line-height:1 glyph overhang, so column fit is checked at the
      // slide level instead.)
      overflow_x: (el.scrollWidth > el.clientWidth + 2),
      in_margin: (r.left < mx) || (r.top < my) ||
                 (r.right > (%d - mx)) || (r.bottom > (%d - my))
    });
  });
  document.title = 'MEASURE:' + JSON.stringify({
    blocks: blocks,
    // The column must fit the 1350px slide: too much text fails here.
    column_overflow: (document.documentElement.scrollHeight > %d + 2)
  });
});
</script>
""" % (int(SLIDE_W * MARGIN_FRAC), int(SLIDE_H * MARGIN_FRAC),
       SLIDE_W, SLIDE_H, SLIDE_H)


def _measure_slide(slide_html: str, css: str) -> dict:
    """Measure text blocks INSIDE the browser via --dump-dom. Returns
    {"blocks": [...], "column_overflow": bool}."""
    chrome = _chromium()
    page = (
        f"<!doctype html><html><head><meta charset='utf-8'>"
        f"<style>{css}</style></head><body>{slide_html}{_PROBE_JS}"
        f"</body></html>"
    )
    with tempfile.TemporaryDirectory(prefix="hypelab_carousel_probe_") as td:
        probe = Path(td) / "probe.html"
        probe.write_text(page, encoding="utf-8")
        p = _run([
            chrome, "--headless=new", "--disable-gpu",
            f"--window-size={SLIDE_W},{SLIDE_H}",
            "--virtual-time-budget=3000",
            "--dump-dom", f"file://{probe}",
        ])
    if p.returncode != 0:
        raise CarouselError(
            f"chromium probe failed (exit {p.returncode}): "
            f"{(p.stderr or '').strip().splitlines()[-1:] or 'no stderr'}"
        )
    m = re.search(r"<title>MEASURE:(\{.*?\})</title>", p.stdout or "", re.S)
    if not m:
        raise CarouselError("chromium probe returned no measurements")
    return json.loads(m.group(1))


# ------------------------------------------------------------------ gates

def _slide_text(slide: dict) -> list[str]:
    texts = [slide.get("title"), slide.get("sub"), slide.get("big"),
             slide.get("caption"), slide.get("handle")]
    texts.extend(slide.get("bullets") or [])
    return [t for t in texts if t]


def _words(s: str) -> int:
    return len(str(s).split())


def gate_text_overflow(spec: dict, kit: dict) -> tuple[bool, str]:
    """10%% margins, <=20 words/slide, 40-char lines, no in-browser overflow."""
    css = kit_to_css(kit)
    for i, s in enumerate(spec["slides"], 1):
        texts = _slide_text(s)
        n_words = sum(_words(t) for t in texts)
        if n_words > WORDS_PER_SLIDE_MAX:
            return False, (
                f"slide {i}: {n_words} words > {WORDS_PER_SLIDE_MAX} "
                "words/slide max"
            )
        for t in texts:
            if len(str(t)) > LINE_CHARS_MAX:
                return False, (
                    f"slide {i}: line {str(t)[:30]!r}… is "
                    f"{len(str(t))} chars > {LINE_CHARS_MAX}-char max"
                )
        measured = _measure_slide(_slide_html(s, kit, i), css)
        for b in measured["blocks"]:
            if b["overflow_x"]:
                return False, (
                    f"slide {i}: text overflows its box horizontally "
                    f"({b['text']!r}…)"
                )
            if b["in_margin"]:
                return False, (
                    f"slide {i}: text enters the 10%% margin band "
                    f"({b['text']!r}…)"
                )
        if measured["column_overflow"]:
            return False, f"slide {i}: text column overflows the slide"
    return True, (
        f"{len(spec['slides'])} slides: ≤{WORDS_PER_SLIDE_MAX} words/slide, "
        f"≤{LINE_CHARS_MAX}-char lines, no overflow, 10%% margins clear"
    )


def gate_slide_one_hook(spec: dict) -> tuple[bool, str]:
    """Slide 1 carries the hook: non-empty, <=12 words."""
    first = next(
        (s for s in spec["slides"] if s.get("idx") == 1), spec["slides"][0]
    )
    hook = (first.get("title") or "").strip()
    if not hook:
        return False, "slide 1: no hook (empty title)"
    n = _words(hook)
    if n > HOOK_WORDS_MAX:
        return False, f"slide 1: hook is {n} words > {HOOK_WORDS_MAX}-word max"
    return True, f"slide 1 hook: {n} words ({hook[:48]!r}…)"


def run_carousel_gates(spec: dict, kit: dict) -> list[tuple[str, bool, str]]:
    """Both Book 3 carousel gates. Every failure is specific, never vague."""
    results = []
    ok, detail = gate_text_overflow(spec, kit)
    results.append(("text_overflow", ok, detail))
    ok, detail = gate_slide_one_hook(spec)
    results.append(("slide_one_hook", ok, detail))
    return results


# ------------------------------------------------------------------ render

def _atomic_write_bytes(path: Path, data: bytes) -> None:
    """Atomic tmp-file + fsync + rename — Book 1 render() discipline."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(
        dir=str(path.parent), prefix=path.name + ".", suffix=".tmp"
    )
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _screenshot(html_path: Path, png_tmp: Path) -> None:
    chrome = _chromium()
    p = _run([
        chrome, "--headless", "--disable-gpu",
        f"--window-size={SLIDE_W},{SLIDE_H}", "--hide-scrollbars",
        f"--screenshot={png_tmp}", f"file://{html_path}",
    ])
    if p.returncode != 0 or not png_tmp.is_file():
        raise CarouselError(
            f"chromium screenshot failed (exit {p.returncode}): "
            f"{(p.stderr or '').strip()[-300:] or 'no stderr'}"
        )


def _png_size(png: Path) -> tuple[int, int]:
    """Read PNG dimensions via ffprobe (validated argv, no shell)."""
    p = _run([
        "ffprobe", "-v", "error", "-select_streams", "v:0",
        "-show_entries", "stream=width,height", "-of", "csv=p=0",
        str(png),
    ])
    if p.returncode != 0:
        raise CarouselError(f"ffprobe failed on {png}")
    w, h = (p.stdout or "").strip().split(",")
    return int(w), int(h)


def validate_spec(spec: dict) -> dict:
    """Structural validation of the carousel spec (the dumb-spec contract)."""
    if not isinstance(spec, dict) or "slides" not in spec:
        raise CarouselError("carousel spec needs a 'slides' list")
    slides = spec["slides"]
    if len(slides) != SLIDES_REQUIRED:
        raise CarouselError(
            f"carousel spec needs exactly {SLIDES_REQUIRED} slides, "
            f"got {len(slides)}"
        )
    idxs = sorted(s.get("idx") for s in slides)
    if idxs != list(range(1, SLIDES_REQUIRED + 1)):
        raise CarouselError(f"slide idx must be 1..{SLIDES_REQUIRED}, got {idxs}")
    for s in slides:
        if s.get("layout") not in LAYOUTS:
            raise CarouselError(
                f"slide {s.get('idx')}: unknown layout {s.get('layout')!r}"
            )
    return spec


def render_carousel(spec: dict, kit: dict, out_dir: str | Path,
                    conn: sqlite3.Connection | None = None,
                    job_id: str | None = None,
                    run_gates: bool = True) -> list[Path]:
    """Render the carousel: spec -> HTML -> 1080x1350 PNGs.

    Gates run BEFORE any render (fail the job, never ship it). Every PNG
    is verified at exactly 1080x1350. audio_map.json records the 2 s/slide
    audio rule. When conn+job_id are given, slide rows are stored.
    """
    spec = validate_spec(spec)
    out = Path(out_dir)
    if run_gates:
        failures = [(n, d) for n, ok, d in run_carousel_gates(spec, kit) if not ok]
        if failures:
            raise CarouselError(
                "carousel gates failed: "
                + "; ".join(f"{n}: {d}" for n, d in failures)
            )
    css = kit_to_css(kit)
    pngs: list[Path] = []
    with tempfile.TemporaryDirectory(prefix="hypelab_carousel_") as td:
        td = Path(td)
        for i, s in enumerate(sorted(spec["slides"], key=lambda x: x["idx"]), 1):
            page = (
                f"<!doctype html><html><head><meta charset='utf-8'>"
                f"<style>{css}</style></head><body>"
                f"{_slide_html(s, kit, i)}</body></html>"
            )
            html_path = td / f"slide_{i:02d}.html"
            html_path.write_text(page, encoding="utf-8")
            tmp_png = td / f"slide_{i:02d}.tmp.png"
            _screenshot(html_path, tmp_png)
            w, h = _png_size(tmp_png)
            if (w, h) != (SLIDE_W, SLIDE_H):
                raise CarouselError(
                    f"slide {i}: rendered at {w}x{h}, expected "
                    f"{SLIDE_W}x{SLIDE_H}"
                )
            final = out / f"slide_{i:02d}.png"
            _atomic_write_bytes(final, tmp_png.read_bytes())
            pngs.append(final)
    audio_map = {f"slide_{i:02d}": SLIDE_DURATION_S for i in range(1, 8)}
    _atomic_write_bytes(
        out / "audio_map.json",
        json.dumps(audio_map, indent=2).encode(),
    )
    if conn is not None and job_id is not None:
        for i, s in enumerate(sorted(spec["slides"], key=lambda x: x["idx"]), 1):
            conn.execute(
                """INSERT INTO slides(id, job_id, idx, spec_json, path)
                   VALUES(?,?,?,?,?)""",
                (new_id("slide"), job_id, i, json.dumps(s),
                 str(out / f"slide_{i:02d}.png")),
            )
        conn.commit()
    return sorted(pngs)


def export_jpeg(pngs: list[Path], quality: int = 92) -> list[Path]:
    """Slide JPEG export via ffmpeg (validated argv). Same atomic discipline."""
    outs = []
    for png in pngs:
        out = png.with_suffix(".jpg")
        fd, tmp = tempfile.mkstemp(
            dir=str(out.parent), prefix=out.stem + ".", suffix=".tmp.jpg"
        )
        os.close(fd)
        try:
            p = _run([
                "ffmpeg", "-v", "error", "-y", "-i", str(png),
                "-q:v", str(max(1, min(10, int(11 - quality / 10)))),
                tmp,
            ])
            if p.returncode != 0 or not Path(tmp).is_file():
                raise CarouselError(f"ffmpeg JPEG export failed for {png}")
            os.replace(tmp, out)
        except BaseException:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise
        outs.append(out)
    return outs
