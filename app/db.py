import json, os, sqlite3

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.environ.get('JP_DB', os.path.join(ROOT, 'progress.sqlite'))

SCHEMA = """
CREATE TABLE IF NOT EXISTS cards (
  id TEXT PRIMARY KEY, position INTEGER UNIQUE NOT NULL, deck TEXT, type TEXT, block INTEGER,
  kanji TEXT, furigana TEXT, tokens TEXT, gloss TEXT, audio TEXT, image TEXT, explanation TEXT,
  target TEXT, extra TEXT
);
CREATE TABLE IF NOT EXISTS card_meta (
  card_id TEXT PRIMARY KEY, introduced_at TEXT, previously_known INTEGER DEFAULT 0,
  short_circuited INTEGER DEFAULT 0, produce_fails INTEGER DEFAULT 0,
  graduated INTEGER DEFAULT 0, graduated_at TEXT
);
CREATE TABLE IF NOT EXISTS tier_state (
  card_id TEXT NOT NULL, tier TEXT NOT NULL, state TEXT NOT NULL,
  stability REAL DEFAULT 0, difficulty REAL DEFAULT 0, due TEXT, last_review TEXT,
  reps INTEGER DEFAULT 0, lapses INTEGER DEFAULT 0, passes INTEGER DEFAULT 0,
  PRIMARY KEY (card_id, tier)
);
CREATE INDEX IF NOT EXISTS tier_due ON tier_state(tier, state, due);
CREATE TABLE IF NOT EXISTS review_log (
  id INTEGER PRIMARY KEY AUTOINCREMENT, card_id TEXT, tier TEXT, rating INTEGER, grade TEXT,
  implied INTEGER DEFAULT 0, reviewed_at TEXT, day TEXT, elapsed_days REAL, scheduled_days REAL,
  stability REAL, difficulty REAL, state_before TEXT, batch INTEGER, snapshot TEXT
);
CREATE INDEX IF NOT EXISTS log_day ON review_log(day);
CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT);
"""

DEFAULT_SETTINGS = {
    'daily_review_cap': 180,      # total graded reviews per day across tiers (~1 hour)
    'new_cards_per_day': 12,      # max deck intake per day, throttled by review load
    'desired_retention': 0.9,
    'implied_credit': 0.5,        # fraction of a Good review granted to lower tiers on a pass
    'graduate_min_interval': 30,  # mutate interval (days) needed to graduate
    'graduate_min_passes': 3,
    'graduated_listening_mult': 2.0,
    'graduated_listening_min_days': 120,
    'short_circuit_fail_limit': 2,
}

def connect():
    con = sqlite3.connect(DB_PATH, check_same_thread=False)
    con.row_factory = sqlite3.Row
    con.execute('PRAGMA journal_mode=WAL')
    con.executescript(SCHEMA)
    return con

def get_settings(con):
    s = dict(DEFAULT_SETTINGS)
    for r in con.execute('SELECT key, value FROM settings'):
        if r['key'] in s:
            s[r['key']] = type(DEFAULT_SETTINGS[r['key']])(json.loads(r['value']))
    return s

def set_settings(con, updates):
    for k, v in updates.items():
        if k in DEFAULT_SETTINGS:
            con.execute('INSERT OR REPLACE INTO settings(key, value) VALUES (?, ?)', (k, json.dumps(v)))
    con.commit()

def card_row_to_dict(r):
    d = dict(r)
    d['tokens'] = json.loads(d['tokens'] or '[]')
    d['extra'] = json.loads(d['extra'] or '{}')
    d['target'] = json.loads(d['target'] or 'null')
    return d
