"""Minimal FSRS-5 implementation (default parameters) used per tier.

Formulas follow the open-spaced-repetition FSRS-5 reference. A "state" is a dict with
stability (days), difficulty (1..10), due (iso), last_review (iso), state name, reps, lapses.
"""
import math, random
from datetime import datetime, timedelta, timezone

W = [0.40255, 1.18385, 3.173, 15.69105, 7.1949, 0.5345, 1.4604, 0.0046, 1.54575, 0.1192,
     1.01925, 1.9395, 0.11, 0.29605, 2.2698, 0.2315, 2.9898, 0.51655, 0.6621]
DECAY = -0.5
FACTOR = 19 / 81
AGAIN, HARD, GOOD, EASY = 1, 2, 3, 4
LEARNING_STEP_MIN = 10
MAX_INTERVAL = 365 * 2

def now_utc():
    return datetime.now(timezone.utc)

def iso(dt):
    return dt.astimezone(timezone.utc).isoformat(timespec='seconds')

def parse(s):
    return datetime.fromisoformat(s)

def retrievability(stability, elapsed_days):
    if stability <= 0: return 0.0
    return (1 + FACTOR * elapsed_days / stability) ** DECAY

def interval_for(stability, retention=0.9):
    """Days until retrievability drops to `retention`."""
    ivl = stability / FACTOR * (retention ** (1 / DECAY) - 1)
    return max(1.0, min(MAX_INTERVAL, ivl))

def init_stability(g):
    return max(0.1, W[g - 1])

def init_difficulty(g):
    return clamp_d(W[4] - math.exp(W[5] * (g - 1)) + 1)

def clamp_d(d):
    return min(10.0, max(1.0, d))

def next_difficulty(d, g):
    delta = -W[6] * (g - 3)
    d2 = d + delta * (10 - d) / 9           # linear damping
    return clamp_d(W[7] * init_difficulty(4) + (1 - W[7]) * d2)   # mean reversion

def stability_recall(d, s, r, g):
    hard = W[15] if g == HARD else 1.0
    easy = W[16] if g == EASY else 1.0
    return s * (math.exp(W[8]) * (11 - d) * s ** (-W[9]) * (math.exp(W[10] * (1 - r)) - 1) * hard * easy + 1)

def stability_forget(d, s, r):
    sf = W[11] * d ** (-W[12]) * ((s + 1) ** W[13] - 1) * math.exp(W[14] * (1 - r))
    return min(sf, s)

def stability_short_term(s, g):
    return s * math.exp(W[17] * (g - 3 + W[18]))

def fuzz(days, rng=random):
    if days < 2.5: return days
    return days * rng.uniform(0.95, 1.05)

def new_state():
    return {'state': 'new', 'stability': 0.0, 'difficulty': 0.0, 'due': None, 'last_review': None,
            'reps': 0, 'lapses': 0, 'passes': 0}

def review(state, g, now=None, retention=0.9, interval_mult=1.0, min_interval=1.0):
    """Apply a rating to a tier state. Returns (new_state, info)."""
    now = now or now_utc()
    st = dict(state)
    elapsed = 0.0
    if st['last_review']:
        elapsed = max(0.0, (now - parse(st['last_review'])).total_seconds() / 86400)
    before = st['state']
    if before == 'new':
        s = init_stability(g); d = init_difficulty(g)
    elif before in ('learning', 'relearning') and elapsed < 1.0:
        s = stability_short_term(st['stability'], g); d = next_difficulty(st['difficulty'], g)
    else:
        r = retrievability(st['stability'], elapsed)
        if g == AGAIN:
            s = stability_forget(st['difficulty'], st['stability'], r)
        else:
            s = stability_recall(st['difficulty'], st['stability'], r, g)
        d = next_difficulty(st['difficulty'], g)
    st['stability'] = s; st['difficulty'] = d
    st['reps'] += 1
    st['last_review'] = iso(now)
    if g == AGAIN:
        if before in ('review',): st['lapses'] += 1
        st['state'] = 'relearning' if before in ('review', 'relearning') else 'learning'
        st['due'] = iso(now + timedelta(minutes=LEARNING_STEP_MIN))
        scheduled = LEARNING_STEP_MIN / 1440
    else:
        st['passes'] += 1
        st['state'] = 'review'
        ivl = max(min_interval, fuzz(interval_for(s, retention) * interval_mult))
        st['due'] = iso(now + timedelta(days=ivl))
        scheduled = ivl
    return st, {'elapsed_days': elapsed, 'scheduled_days': scheduled, 'state_before': before}

def reschedule_from_stability(state, now=None, retention=0.9, interval_mult=1.0, min_interval=1.0):
    now = now or now_utc()
    st = dict(state)
    ivl = max(min_interval, interval_for(st['stability'], retention) * interval_mult)
    st['due'] = iso(now + timedelta(days=ivl)); st['last_review'] = iso(now); st['state'] = 'review'
    return st, ivl

if __name__ == '__main__':
    # sanity checks
    assert abs(retrievability(10, 10) - 0.9) < 1e-9
    assert abs(interval_for(10) - 10) < 1e-6
    s = new_state()
    for g in (GOOD, GOOD, GOOD):
        s, info = review(s, g, now=now_utc() + timedelta(days=s['stability'] if s['stability'] else 0))
        print(g, round(s['stability'], 2), round(s['difficulty'], 2), round(info['scheduled_days'], 2))
    s2, _ = review(new_state(), EASY); print('easy first', round(s2['stability'], 2), s2['due'])
    s3, _ = review(new_state(), AGAIN); print('again first', s3['state'], s3['due'])
