"""Tier logic on top of FSRS: bucketing, short circuits, implied credit, graduation, budget, queues."""
import json, random
from datetime import datetime, timedelta, timezone
import fsrs
from db import get_settings, card_row_to_dict

TIERS = ['listening', 'reading', 'produce', 'mutate']
RANK = {t: i for i, t in enumerate(TIERS)}
GRADES = {
    'listening': {'missed': 1, 'replay': 2, 'instant': 3},
    'reading':   {'missed': 1, 'slow': 2, 'good': 3, 'instant': 4},
    'produce':   {'missed': 1, 'partial': 2, 'good': 3},
    'mutate':    {'missed': 1, 'shaky': 2, 'good': 3},
}
ACTIVE = ('new', 'learning', 'relearning', 'review')

def now(): return fsrs.now_utc()
def local_now(): return now().astimezone()
def today(): return local_now().date().isoformat()

def _state_row(con, card_id, tier):
    r = con.execute('SELECT * FROM tier_state WHERE card_id=? AND tier=?', (card_id, tier)).fetchone()
    return dict(r) if r else None

def _save_state(con, card_id, tier, st):
    con.execute('''INSERT INTO tier_state(card_id, tier, state, stability, difficulty, due, last_review, reps, lapses, passes)
                   VALUES (?,?,?,?,?,?,?,?,?,?) ON CONFLICT(card_id, tier) DO UPDATE SET state=excluded.state,
                   stability=excluded.stability, difficulty=excluded.difficulty, due=excluded.due, last_review=excluded.last_review,
                   reps=excluded.reps, lapses=excluded.lapses, passes=excluded.passes''',
                (card_id, tier, st['state'], st['stability'], st['difficulty'], st['due'], st['last_review'], st['reps'], st['lapses'], st['passes']))

def _meta(con, card_id, create=False):
    r = con.execute('SELECT * FROM card_meta WHERE card_id=?', (card_id,)).fetchone()
    if r: return dict(r)
    if not create: return None
    con.execute('INSERT INTO card_meta(card_id, introduced_at) VALUES (?, ?)', (card_id, fsrs.iso(now())))
    return _meta(con, card_id)

def _save_meta(con, m):
    con.execute('''UPDATE card_meta SET previously_known=?, short_circuited=?, produce_fails=?, graduated=?, graduated_at=? WHERE card_id=?''',
                (m['previously_known'], m['short_circuited'], m['produce_fails'], m['graduated'], m['graduated_at'], m['card_id']))

def _states(con, card_id):
    return {r['tier']: dict(r) for r in con.execute('SELECT * FROM tier_state WHERE card_id=?', (card_id,))}

def _fresh(due=None):
    st = fsrs.new_state(); st['due'] = fsrs.iso(due or now()); return st

def _ensure_unlocks(con, card_id, meta, states):
    """Create tier rows the card has earned. Returns list of newly unlocked tiers."""
    unlocked = []
    def passed(t): return states.get(t, {}).get('passes', 0) >= 1
    want = set()
    if passed('listening'): want.add('reading')
    if meta['short_circuited'] or (passed('listening') and passed('reading')): want.add('produce')
    if 'produce' in want and passed('produce'): want.add('mutate')
    if meta['graduated']: want = set()
    for t in want:
        if t not in states:
            st = _fresh(); _save_state(con, card_id, t, st); states[t] = dict(st, card_id=card_id, tier=t); unlocked.append(t)
    return unlocked

def _log(con, batch, card_id, tier, rating, grade, implied, info, st, snapshot):
    con.execute('''INSERT INTO review_log(card_id, tier, rating, grade, implied, reviewed_at, day, elapsed_days, scheduled_days, stability, difficulty, state_before, batch, snapshot)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
                (card_id, tier, rating, grade, implied, fsrs.iso(now()), today(), info.get('elapsed_days'), info.get('scheduled_days'),
                 st['stability'], st['difficulty'], info.get('state_before'), batch, json.dumps(snapshot)))

def review(con, card_id, tier, grade):
    S = get_settings(con)
    if tier not in TIERS or grade not in GRADES[tier]: raise ValueError('bad tier/grade')
    card = card_row_to_dict(con.execute('SELECT * FROM cards WHERE id=?', (card_id,)).fetchone())
    meta = _meta(con, card_id, create=True)
    states = _states(con, card_id)
    if tier not in states:
        if tier != 'listening' and not meta['short_circuited']:
            raise ValueError(f'{tier} is not unlocked for this card')
        states[tier] = dict(_fresh(), card_id=card_id, tier=tier)
    st = states[tier]
    if st['state'] == 'inactive': raise ValueError('tier is inactive (graduated)')
    batch = int(now().timestamp() * 1000)
    snapshot = {'meta': dict(meta), 'states': {t: dict(s) for t, s in states.items()}}
    rating = GRADES[tier][grade]
    first = st['reps'] == 0
    result = {'card_id': card_id, 'tier': tier, 'grade': grade, 'events': []}

    # --- short circuits (first-ever instant hit)
    short = False
    if first and grade == 'instant' and tier in ('listening', 'reading'):
        rating = fsrs.EASY; short = True
        meta['short_circuited'] = 1
        if tier == 'listening': meta['previously_known'] = 1
        result['events'].append('short_circuit')

    mult, min_days = 1.0, 1.0
    if tier == 'listening' and meta['graduated']:
        mult, min_days = S['graduated_listening_mult'], S['graduated_listening_min_days']
    new_st, info = fsrs.review(st, rating, retention=S['desired_retention'], interval_mult=mult, min_interval=min_days)
    states[tier].update(new_st)
    _save_state(con, card_id, tier, new_st)
    _log(con, batch, card_id, tier, rating, grade, 0, info, new_st, snapshot)
    result['scheduled_days'] = info['scheduled_days']

    # a Listening short circuit opens Produce at once, but Reading still has to be tested:
    # it is unlocked as a normal new review (due now) rather than seeded with a pass.

    # --- implied credit downward on a pass
    if rating >= 2:
        for lower in TIERS[:RANK[tier]]:
            ls = states.get(lower)
            if not ls or ls['state'] != 'review': continue
            cand, cinfo = fsrs.review(ls, fsrs.GOOD, retention=S['desired_retention'])
            blended = dict(ls)
            blended['stability'] = ls['stability'] + S['implied_credit'] * (cand['stability'] - ls['stability'])
            lmult, lmin = (S['graduated_listening_mult'], S['graduated_listening_min_days']) if (lower == 'listening' and meta['graduated']) else (1.0, 1.0)
            blended, ivl = fsrs.reschedule_from_stability(blended, retention=S['desired_retention'], interval_mult=lmult, min_interval=lmin)
            states[lower].update(blended); _save_state(con, card_id, lower, blended)
            _log(con, batch, card_id, lower, fsrs.GOOD, 'implied', 1, {'elapsed_days': cinfo['elapsed_days'], 'scheduled_days': ivl, 'state_before': ls['state']}, blended, None)
            result['events'].append(f'implied:{lower}')

    # --- a short-circuited card failing Produce repeatedly was not really known
    if tier == 'produce' and meta['short_circuited']:
        if rating == 1:
            meta['produce_fails'] += 1
            if meta['produce_fails'] >= S['short_circuit_fail_limit']:
                fresh = _fresh(); _save_state(con, card_id, 'reading', fresh); states['reading'] = dict(fresh, card_id=card_id, tier='reading')
                meta['short_circuited'] = 0; meta['previously_known'] = 0; meta['produce_fails'] = 0
                result['events'].append('reading_reopened')
        else:
            meta['produce_fails'] = 0

    # --- graduation
    if tier == 'mutate' and rating >= 3 and not meta['graduated']:
        if info['scheduled_days'] >= S['graduate_min_interval'] and new_st['passes'] >= S['graduate_min_passes']:
            meta['graduated'] = 1; meta['graduated_at'] = fsrs.iso(now())
            for t in ('reading', 'produce', 'mutate'):
                if t in states:
                    states[t]['state'] = 'inactive'; _save_state(con, card_id, t, states[t])
            ls = states.get('listening')
            if ls and ls['state'] != 'new':
                ls['stability'] = max(ls['stability'] * S['graduated_listening_mult'], S['graduated_listening_min_days'])
                ls, _ = fsrs.reschedule_from_stability(ls, retention=S['desired_retention'], min_interval=S['graduated_listening_min_days'])
                states['listening'] = ls; _save_state(con, card_id, 'listening', ls)
            result['events'].append('graduated')

    _save_meta(con, meta)
    unlocked = _ensure_unlocks(con, card_id, meta, states)
    for t in unlocked: result['events'].append(f'unlocked:{t}')
    con.commit()
    result['states'] = {t: {k: s[k] for k in ('state', 'stability', 'due', 'passes', 'reps', 'lapses')} for t, s in states.items()}
    result['meta'] = meta
    result['batch'] = batch
    return result

def undo_last(con):
    r = con.execute('SELECT batch, snapshot, card_id FROM review_log WHERE implied=0 ORDER BY id DESC LIMIT 1').fetchone()
    if not r or not r['snapshot']: return None
    snap = json.loads(r['snapshot'])
    card_id = r['card_id']
    con.execute('DELETE FROM tier_state WHERE card_id=?', (card_id,))
    for t, s in snap['states'].items(): _save_state(con, card_id, t, s)
    m = snap['meta']
    if m.get('introduced_at') and not m.get('previously_known') and all(s['reps'] == 0 for s in snap['states'].values()) and len(snap['states']) <= 1:
        con.execute('DELETE FROM card_meta WHERE card_id=?', (card_id,))   # was a brand-new card: un-introduce it
    else:
        _save_meta(con, m)
    con.execute('DELETE FROM review_log WHERE batch=?', (r['batch'],))
    con.commit()
    return card_id

# ---------------------------------------------------------------- queues and budget
def reviews_today(con):
    return con.execute('SELECT count(*) FROM review_log WHERE day=? AND implied=0', (today(),)).fetchone()[0]

def introduced_today(con):
    start = local_now().replace(hour=0, minute=0, second=0, microsecond=0)
    return con.execute('SELECT count(*) FROM card_meta WHERE introduced_at >= ?', (fsrs.iso(start),)).fetchone()[0]

def due_counts(con):
    n = fsrs.iso(now())
    end = fsrs.iso(local_now().replace(hour=23, minute=59, second=59))
    out = {}
    for t in TIERS:
        row = con.execute('''SELECT sum(due <= ?) AS due_now, sum(due > ? AND due <= ?) AS later_today,
                             sum(state != 'inactive') AS active, sum(state = 'new') AS fresh FROM tier_state WHERE tier=? AND state != 'inactive' ''', (n, n, end, t)).fetchone()
        out[t] = {'due': row['due_now'] or 0, 'later_today': row['later_today'] or 0, 'active': row['active'] or 0, 'new': row['fresh'] or 0}
    return out

def new_allowance(con, S, counts=None):
    counts = counts or due_counts(con)
    load = sum(c['due'] + c['later_today'] for c in counts.values()) + reviews_today(con)
    factor = min(1.0, max(0.0, (1 - load / S['daily_review_cap']) / 0.5))
    allowed = round(S['new_cards_per_day'] * factor) - introduced_today(con)
    allowed = min(allowed, S['daily_review_cap'] - reviews_today(con))
    return max(0, allowed), round(load / S['daily_review_cap'], 2)

def _item(con, row, tier, is_new=False):
    card = card_row_to_dict(con.execute('SELECT * FROM cards WHERE id=?', (row['card_id'] if 'card_id' in row.keys() else row['id'],)).fetchone())
    st = _state_row(con, card['id'], tier) or _fresh()
    meta = _meta(con, card['id']) or {}
    item = {'card': card, 'tier': tier, 'is_new': is_new, 'first_review': st['reps'] == 0, 'state': {k: st[k] for k in ('state', 'stability', 'due', 'reps', 'passes', 'lapses')}, 'meta': meta}
    if tier == 'mutate':
        import mutate
        item['mutation'] = mutate.mutation_for(card, today())
    return item

def next_item(con, tier='all', ignore_cap=False, exclude=None):
    S = get_settings(con)
    done = reviews_today(con)
    scope = TIERS if tier == 'all' else [tier]
    if not ignore_cap and done >= S['daily_review_cap']:
        return {'item': None, 'reason': 'cap', 'done': done, 'cap': S['daily_review_cap']}
    n = fsrs.iso(now())
    ex = exclude or ''
    # due now, higher tiers first, most overdue first
    for t in sorted(scope, key=lambda x: -RANK[x]):
        r = con.execute('''SELECT * FROM tier_state WHERE tier=? AND state IN ('new','learning','relearning','review') AND due <= ? AND card_id != ?
                           ORDER BY (state='new') ASC, due ASC LIMIT 1''', (t, n, ex)).fetchone()
        if r: return {'item': _item(con, r, t), 'reason': 'due', 'done': done, 'cap': S['daily_review_cap']}
    # deck intake (only through listening)
    if 'listening' in scope:
        allowed, load = new_allowance(con, S)
        if allowed > 0 or ignore_cap:
            r = con.execute('''SELECT c.* FROM cards c LEFT JOIN card_meta m ON m.card_id = c.id WHERE m.card_id IS NULL ORDER BY c.position LIMIT 1''').fetchone()
            if r: return {'item': _item(con, r, 'listening', is_new=True), 'reason': 'new', 'done': done, 'cap': S['daily_review_cap'], 'new_left': allowed}
    # learning cards coming up within the session
    soon = fsrs.iso(now() + timedelta(minutes=fsrs.LEARNING_STEP_MIN))
    for t in sorted(scope, key=lambda x: -RANK[x]):
        r = con.execute('''SELECT * FROM tier_state WHERE tier=? AND state IN ('learning','relearning') AND due <= ? AND card_id != ? ORDER BY due ASC LIMIT 1''', (t, soon, ex)).fetchone()
        if r: return {'item': _item(con, r, t), 'reason': 'learning_ahead', 'done': done, 'cap': S['daily_review_cap']}
    return {'item': None, 'reason': 'empty', 'done': done, 'cap': S['daily_review_cap']}

def overview(con):
    S = get_settings(con)
    counts = due_counts(con)
    allowed, load = new_allowance(con, S, counts)
    nxt = [dict(r) for r in con.execute('''SELECT c.id, c.kanji, c.gloss, c.type, c.deck FROM cards c LEFT JOIN card_meta m ON m.card_id=c.id WHERE m.card_id IS NULL ORDER BY c.position LIMIT 5''')]
    known = con.execute('SELECT count(DISTINCT card_id) FROM tier_state WHERE passes >= 1').fetchone()[0]
    introduced = con.execute('SELECT count(*) FROM card_meta').fetchone()[0]
    graduated = con.execute('SELECT count(*) FROM card_meta WHERE graduated=1').fetchone()[0]
    total = con.execute('SELECT count(*) FROM cards').fetchone()[0]
    return {'tiers': counts, 'new': {'allowed': allowed, 'introduced_today': introduced_today(con), 'per_day': S['new_cards_per_day'], 'load': load, 'next': nxt},
            'today': {'reviews': reviews_today(con), 'cap': S['daily_review_cap']},
            'deck': {'total': total, 'introduced': introduced, 'known': known, 'graduated': graduated,
                     'previously_known': con.execute('SELECT count(*) FROM card_meta WHERE previously_known=1').fetchone()[0]},
            'settings': S}

def shadow(con, limit=400):
    rows = con.execute('''SELECT c.* FROM cards c WHERE c.id IN (SELECT card_id FROM tier_state WHERE passes >= 1) AND c.audio IS NOT NULL''').fetchall()
    cards = [card_row_to_dict(r) for r in rows]
    random.shuffle(cards)
    return [{'id': c['id'], 'kanji': c['kanji'], 'tokens': c['tokens'], 'gloss': c['gloss'], 'audio': c['audio'], 'deck': c['deck']} for c in cards[:limit]]

def browse(con, offset=0, limit=50, filt='all'):
    where = ''
    if filt == 'introduced': where = 'WHERE m.card_id IS NOT NULL'
    elif filt == 'new': where = 'WHERE m.card_id IS NULL'
    elif filt == 'graduated': where = 'WHERE m.graduated = 1'
    rows = con.execute(f'''SELECT c.id, c.position, c.deck, c.type, c.kanji, c.gloss, m.previously_known, m.graduated, m.short_circuited
                           FROM cards c LEFT JOIN card_meta m ON m.card_id=c.id {where} ORDER BY c.position LIMIT ? OFFSET ?''', (limit, offset)).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d['tiers'] = {t['tier']: {'state': t['state'], 'due': t['due'], 'passes': t['passes']} for t in con.execute('SELECT tier, state, due, passes FROM tier_state WHERE card_id=?', (d['id'],))}
        out.append(d)
    total = con.execute(f'SELECT count(*) FROM cards c LEFT JOIN card_meta m ON m.card_id=c.id {where}').fetchone()[0]
    return {'rows': out, 'total': total}

def stats(con):
    days = [dict(r) for r in con.execute('''SELECT day, count(*) AS reviews, sum(rating=1) AS fails, count(DISTINCT card_id) AS cards
                                             FROM review_log WHERE implied=0 GROUP BY day ORDER BY day DESC LIMIT 60''')]
    per_tier = {t: dict(con.execute('''SELECT count(*) AS reviews, sum(rating=1) AS fails FROM review_log WHERE implied=0 AND tier=?''', (t,)).fetchone()) for t in TIERS}
    states = {t: {r['state']: r['n'] for r in con.execute('SELECT state, count(*) AS n FROM tier_state WHERE tier=? GROUP BY state', (t,))} for t in TIERS}
    upcoming = [dict(r) for r in con.execute('''SELECT substr(due,1,10) AS day, count(*) AS n FROM tier_state WHERE state='review' AND due > ? GROUP BY day ORDER BY day LIMIT 14''', (fsrs.iso(now()),))]
    return {'days': days, 'per_tier': per_tier, 'states': states, 'upcoming': upcoming}
