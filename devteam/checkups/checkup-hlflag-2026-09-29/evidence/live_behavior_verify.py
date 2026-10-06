import os, sys, tempfile, shutil
"""Live behavioral verification for the HYPELAB_AUTO_REQUEUE kill switch.

Proves, against the real implementation and a real sqlite DB (no mocks):
  1. auto_requeue_enabled() reads the env LIVE at each routing decision
     (flag flipped AFTER import changes routing).
  2. flag=0 routes a transient failure to the review pile with reason
     "auto-requeue-disabled:<detail>" and logs one UNMETERED cost row.
  3. flag flipped back on mid-process -> transient requeues again.
  4. publish-job exclusion holds even when the flag is OFF (kill switch
     cannot bypass the D1 exclusion).
  5. empty string = ON.
  6. backoff sequence 60/120/240, cap 900 (attempt 4 shown for the curve).
"""
from pathlib import Path
from datetime import datetime, timedelta, timezone

REPO = Path('/home/dino/hypelab')
sys.path.insert(0, str(REPO))
os.environ.pop('HYPELAB_AUTO_REQUEUE', None)
from hypelab import db as db_mod, jobs as jobs_mod, kits as kits_mod, queue as queue_mod, retry as retry_mod

tmp = tempfile.mkdtemp(prefix='hlflag_verify_')
root = Path(tmp) / 'root'
(root / 'work').mkdir(parents=True)
dbp = str(Path(tmp) / 't.db')
os.environ['HYPELAB_DB'] = dbp
os.environ['HYPELAB_ROOT'] = str(root)

def _conn():
    return db_mod.connect(dbp)

c = _conn(); db_mod.migrate(c); kits_mod.seed(c, 'k', {}); c.close()

def new_claimed(queued_state='queued_render'):
    c = _conn()
    try:
        jid = jobs_mod.new(c, mode='book1', title='tq', state=queued_state,
                           kit_id='k', kit_version=1)
        row = queue_mod.claim(c, 'w1', states=[queued_state])
        assert row is not None and row['id'] == jid
        return jid
    finally:
        c.close()

def get(jid):
    c = _conn()
    try:
        return jobs_mod.get(c, jid)
    finally:
        c.close()

def cost_rows(jid):
    c = _conn()
    try:
        return c.execute(
            "SELECT provider, unit, qty, usd, note FROM cost_ledger"
            " WHERE job_id=? ORDER BY id", (jid,)).fetchall()
    finally:
        c.close()

def handle(jid, err):
    c = _conn()
    try:
        return retry_mod.handle_failure(c, jid, 'w1', err)
    finally:
        c.close()

# 1. Live read: flag set AFTER import must change routing.
os.environ['HYPELAB_AUTO_REQUEUE'] = '0'
print('check1 live read (flag=0 after import):', retry_mod.auto_requeue_enabled())
assert retry_mod.auto_requeue_enabled() is False

# 2. Disabled -> transient -> review pile, reason auto-requeue-disabled:<detail>.
jid = new_claimed()
outcome = handle(jid, TimeoutError('boom'))
row = get(jid)
print('check2 disabled transient -> outcome=%s state=%s reason=%s'
      % (outcome, row['state'], row['review_reason']))
assert outcome == 'review' and row['state'] == 'failed'
assert row['review_reason'].startswith('auto-requeue-disabled:')
cost = cost_rows(jid)
print('check2 cost rows: %d | %s' % (len(cost), cost[0][4][:72]))
assert len(cost) == 1 and 'UNMETERED' in cost[0][4]

# 3. Live flip back on mid-process -> requeues again.
os.environ['HYPELAB_AUTO_REQUEUE'] = 'on'
jid2 = new_claimed()
outcome2 = handle(jid2, TimeoutError('boom'))
row2 = get(jid2)
print('check3 re-enabled transient -> outcome=%s state=%s'
      % (outcome2, row2['state']))
assert outcome2 == 'requeued'

# 4. Publish exclusion holds with flag OFF (kill switch must not bypass D1).
os.environ['HYPELAB_AUTO_REQUEUE'] = '0'
c = _conn()
try:
    jid3 = jobs_mod.new(c, mode='book1', title='tq', state='queued_render',
                        kit_id='k', kit_version=1)
    c.execute("UPDATE jobs SET state='published', lease_owner='w1',"
              " lease_expires=?, attempts=1 WHERE id=?",
              ((datetime.now(timezone.utc) + timedelta(minutes=30))
               .isoformat(timespec='seconds'), jid3))
    outcome3 = retry_mod.handle_failure(c, jid3, 'w1',
                                        TimeoutError('post timed out'))
finally:
    c.close()
row3 = get(jid3)
print('check4 disabled flag + publish job -> outcome=%s reason=%s'
      % (outcome3, row3['review_reason']))
assert outcome3 == 'review'
assert (row3['review_reason'] or '').startswith('publish-excluded:')

# 5. Empty string = ON.
os.environ['HYPELAB_AUTO_REQUEUE'] = ''
assert retry_mod.auto_requeue_enabled() is True
print('check5 empty string -> on: OK')

# 6. Backoff sequence.
seq = [retry_mod.backoff_delay_s(a) for a in (1, 2, 3, 4, 10)]
print('check6 backoffs attempt 1,2,3,4,10:', seq)
assert seq == [60, 120, 240, 480, 900]

print('ALL LIVE BEHAVIOR CHECKS PASSED')
shutil.rmtree(tmp, ignore_errors=True)
