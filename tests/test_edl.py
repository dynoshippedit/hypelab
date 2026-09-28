"""Invalid EDLs must be rejected with field-level errors; valid ones pass."""
import copy
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from hypelab import edl as E

def valid_edl() -> dict:
    return {
        "edl_version": 1, "mode": "original", "kit": "demo@1",
        "source": {"url": None, "t_in": None, "t_out": None},
        "target": {"aspect": "9:16", "w": 1080, "h": 1920, "fps": 30,
                   "max_duration_s": 60, "loudness_lufs": -14},
        "audio": {"vo": {"slot": "vo", "align_slot": "vo.words"},
                  "music": {"slot": "music", "duck_db": -12, "fade_in_s": 0.5,
                            "fade_out_s": 1.5, "beat_grid_slot": "beats"}},
        "beats": [
            {"id": "b1", "role": "hook", "t_in": 0.0, "t_out": 2.8,
             "line": "hook line", "clip_slot": "beat:b1", "clip_fit": "cover",
             "prompt_used": "", "ref_image_slot": "ref_image"},
            {"id": "b2", "role": "body", "t_in": 2.8, "t_out": 9.4,
             "line": "body line", "clip_slot": "beat:b2", "clip_fit": "cover",
             "prompt_used": "", "ref_image_slot": "ref_image"},
        ],
        "reframe": {"mode": "static",
                    "keyframes": [{"t": 0.0, "cx": 0.5, "cy": 0.5, "scale": 1.0}]},
        "captions": {"style": "word_pop", "font": "DejaVu Sans", "size": 74,
                     "safe_top_pct": 14, "safe_bottom_pct": 22,
                     "max_chars_per_card": 22},
        "overlays": [],
        "compliance": {"campaign": None, "checks_passed": []},
        "creative": {"hook_len_s": 2.8, "beat_count": 2,
                     "caption_style": "word_pop", "music": True},
        "gates_passed": [], "render_hash": None,
    }

SLOTS = {"vo", "vo.words", "music", "beats", "ref_image", "beat:b1", "beat:b2"}

class TestEDL(unittest.TestCase):
    def test_valid_passes(self):
        self.assertEqual(E.validate_all(valid_edl(), SLOTS), [])

    def _mut(self, fn):
        d = valid_edl()
        fn(d)
        errs = E.validate_all(d, SLOTS)
        self.assertTrue(errs, "expected rejection but EDL passed")
        return errs

    def test_bad_version(self):
        self._mut(lambda d: d.update(edl_version=99))

    def test_bad_mode(self):
        self._mut(lambda d: d.update(mode="vlog"))

    def test_bad_kit(self):
        self._mut(lambda d: d.update(kit="no-version-here"))

    def test_hook_over_budget(self):
        self._mut(lambda d: d["beats"][0].update(t_out=5.0))

    def test_overlapping_beats(self):
        self._mut(lambda d: d["beats"][1].update(t_in=2.0))

    def test_gap_between_beats(self):
        self._mut(lambda d: d["beats"][1].update(t_in=3.5, t_out=9.4))

    def test_missing_clip_slot_asset(self):
        errs = E.validate_all(valid_edl(), SLOTS - {"beat:b2"})
        self.assertTrue(any("beat:b2" in x for x in errs))

    def test_bad_duck(self):
        self._mut(lambda d: d["audio"]["music"].update(duck_db=+6))

    def test_bad_caption_size(self):
        self._mut(lambda d: d["captions"].update(size=400))

    def test_bad_reframe(self):
        self._mut(lambda d: d["reframe"].update(mode="spin"))

    def test_missing_creative(self):
        self._mut(lambda d: d.pop("creative"))

    def test_duplicate_beat_id(self):
        self._mut(lambda d: d["beats"][1].update(id="b1"))

if __name__ == "__main__":
    unittest.main(verbosity=2)
