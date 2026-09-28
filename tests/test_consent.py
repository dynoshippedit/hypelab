"""Consent hard gate: publish is refused without a valid consent artifact.

Cases: no consent at all; wrong asset version; expired; revoked; valid dry-run
succeeds and explicitly reports that nothing was sent.
"""
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from hypelab.consent import Consents, ConsentRequired, require_consent
from hypelab import publish as pub

def _future(days=30):
    return (datetime.now(timezone.utc) + timedelta(days=days)).isoformat()

class TestConsent(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Path(self.tmp.name) / "c.db"
        self.consents = Consents(path=self.db)

    def tearDown(self):
        self.tmp.cleanup()

    def _grant(self, asset_version="abc123", expiry=None):
        return self.consents.record(
            job_id="job1", handle="creator", platform="instagram",
            scope="collab_post:instagram", asset_version=asset_version,
            evidence="dm:12345", expiry=expiry or _future())

    def test_no_consent_refused(self):
        with self.assertRaises(ConsentRequired):
            require_consent("job1", "creator", "instagram", "abc123", path=self.db)

    def test_wrong_asset_version_refused(self):
        self._grant(asset_version="abc123")
        with self.assertRaises(ConsentRequired):
            require_consent("job1", "creator", "instagram", "DIFFERENT",
                            path=self.db)

    def test_expired_refused(self):
        past = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
        self._grant(expiry=past)
        with self.assertRaises(ConsentRequired):
            require_consent("job1", "creator", "instagram", "abc123", path=self.db)

    def test_revoked_refused(self):
        rec = self._grant()
        self.consents.revoke(rec["id"])
        with self.assertRaises(ConsentRequired):
            require_consent("job1", "creator", "instagram", "abc123", path=self.db)

    def test_valid_consent_passes(self):
        self._grant()
        rec = require_consent("job1", "creator", "instagram", "abc123", path=self.db)
        self.assertEqual(rec["scope"], "collab_post:instagram")

    def test_dryrun_adapter_says_nothing_sent(self):
        plan = pub.PublishPlan(job_id="job1", target_handle="creator",
                               platform="instagram", collaborators=["a"],
                               asset_path="/tmp/x.mp4", dry_run=True)
        r = pub.DryRunAdapter().publish(plan, dry_run=True)
        self.assertTrue(r.ok and r.dry_run)
        self.assertIn("DRY RUN", r.detail)
        self.assertIn("nothing was sent", r.detail)

    def test_too_many_collaborators_rejected(self):
        plan = pub.PublishPlan(job_id="job1", target_handle="creator",
                               platform="instagram",
                               collaborators=["a", "b", "c", "d"],
                               asset_path="/tmp/x.mp4", dry_run=True)
        r = pub.DryRunAdapter().publish(plan, dry_run=True)
        self.assertFalse(r.ok)
        self.assertIn("max 3", r.detail)

if __name__ == "__main__":
    unittest.main(verbosity=2)
