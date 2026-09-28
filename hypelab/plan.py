"""Planning: script -> beats -> shot prompts -> render.json assembly.

Beat boundaries come from word alignment (the VO is the spine), never from
fixed intervals. The planner emits render.json; edl.validate_all() decides
whether it may proceed.
"""
from __future__ import annotations
import hashlib
import json
import re

from . import edl as edl_mod

SENT_SPLIT = re.compile(r"(?<=[.!?])\s+|\n+")

def split_sentences(script: str) -> list[str]:
    parts = [p.strip() for p in SENT_SPLIT.split(script.strip()) if p.strip()]
    return parts

def group_into_beats(sentences: list[str], words: list[dict],
                     max_clip_len_s: float, hook_budget_s: float = 3.0
                     ) -> list[dict]:
    """Assign each sentence's words to a beat. Beat 1 (hook) is capped at the
    hook budget; the rest are capped at the kit's max clip length."""
    # map sentence -> word span by consuming words in order
    beats: list[dict] = []
    wi = 0  # word index
    for si, sent in enumerate(sentences):
        n_words = len(sent.split())
        span = words[wi:wi + n_words]
        if not span:
            break
        wi += n_words
        t_in = span[0]["t0"]
        t_out = span[-1]["t1"]
        role = "hook" if si == 0 else ("cta" if si == len(sentences) - 1 else "body")
        cap = hook_budget_s if role == "hook" else max_clip_len_s
        if t_out - t_in > cap and len(beats) and role != "hook":
            # over-long body sentence: split at word nearest the cap
            cut = t_in + cap
            k = next((j for j, w in enumerate(span) if w["t0"] >= cut), len(span))
            k = max(1, k)
            beats.append(_beat(f"b{len(beats)+1}", "body", span[:k]))
            beats.append(_beat(f"b{len(beats)+1}", role, span[k:]))
        else:
            # hook over budget: keep whole (validator/gate will flag it)
            beats.append(_beat(f"b{len(beats)+1}", role, span))
    # renumber sequentially
    for i, b in enumerate(beats):
        b["id"] = f"b{i+1}"
    # tile contiguously: each beat starts where the previous ended (b1 at 0).
    # Inter-sentence pauses belong to the following beat's clip hold.
    for i, b in enumerate(beats):
        b["t_in"] = 0.0 if i == 0 else beats[i - 1]["t_out"]
        b["t_in"] = round(b["t_in"], 3)
        b["t_out"] = round(b["t_out"], 3)
    return beats

def _beat(bid: str, role: str, span: list[dict]) -> dict:
    line = " ".join(w["w"] for w in span)
    return {"id": bid, "role": role, "t_in": span[0]["t0"], "t_out": span[-1]["t1"],
            "line": line}

def shot_prompts(beats: list[dict], kit: dict) -> list[str]:
    """Paste-ready numbered prompts, each carrying the locked reference."""
    prompts = []
    for b in beats:
        prompts.append(
            f"[{b['id']}] ({b['role']}, {b['t_out']-b['t_in']:.1f}s) "
            f"Beat line: \"{b['line']}\"\n"
            f"LOCKED CHARACTER — use verbatim: {kit['appearance_text']}\n"
            f"Reference image: {kit['ref_image_path'] or '(none locked)'}\n"
            f"Guardrails — DO: {'; '.join(kit['guardrails']['do']) or '—'} | "
            f"DON'T: {'; '.join(kit['guardrails']['dont']) or '—'}")
    return prompts

def assemble_edl(job_id: str, mode: str, kit: dict, kit_version: int,
                 script: str, words: list[dict], beats: list[dict],
                 aspect: str = "9:16") -> dict:
    w, h = {"9:16": (1080, 1920), "1:1": (1080, 1080), "16:9": (1920, 1080)}[aspect]
    cap = kit["caption_style"]
    data = {
        "edl_version": 1,
        "mode": mode,
        "kit": f"{kit['kit_id']}@{kit_version}",
        "source": {"url": None, "t_in": None, "t_out": None},
        "target": {"aspect": aspect, "w": w, "h": h, "fps": 30,
                   "max_duration_s": 60, "loudness_lufs": -14},
        "audio": {
            "vo": {"slot": "vo", "align_slot": "vo.words"},
            "music": {"slot": "music", "duck_db": -12, "fade_in_s": 0.5,
                      "fade_out_s": 1.5, "beat_grid_slot": "beats"},
        },
        "beats": [
            {"id": b["id"], "role": b["role"], "t_in": round(b["t_in"], 3),
             "t_out": round(b["t_out"], 3), "line": b["line"],
             "clip_slot": f"beat:{b['id']}", "clip_fit": "cover",
             "prompt_used": "", "ref_image_slot": "ref_image"}
            for b in beats
        ],
        "reframe": {"mode": "static",
                    "keyframes": [{"t": 0.0, "cx": 0.5, "cy": 0.5, "scale": 1.0}]},
        "captions": {"style": cap["style"], "font": kit["typography"]["font"],
                     "size": cap["size"], "safe_top_pct": cap["safe_top_pct"],
                     "safe_bottom_pct": cap["safe_bottom_pct"],
                     "max_chars_per_card": cap["max_chars_per_card"]},
        "overlays": [],
        "compliance": {"campaign": None, "checks_passed": []},
        "creative": {"hook_len_s": round(beats[0]["t_out"] - beats[0]["t_in"], 2),
                     "beat_count": len(beats),
                     "caption_style": cap["style"], "music": True},
        "gates_passed": [], "render_hash": None,
    }
    return data

def render_hash(data: dict) -> str:
    canon = json.dumps(data, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(canon).hexdigest()
