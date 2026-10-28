#!/usr/bin/env python3
"""Load data/combined_deck.json into the progress database (idempotent, keeps progress).

Usage: python3 -I app/import_deck.py
"""
import json, os, re, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db

KANJI = re.compile(r'[一-鿿々]')

def find_target(entry, seen_lemmas):
    """Return the surface string to highlight as the card's target word, or None."""
    if entry['deck'] == 'kaishi':
        w = entry['word']
        return w if w in entry['kanji'] else (entry['word_reading'] if entry['word_reading'] in entry['kanji'] else None)
    new = [l for l in entry.get('lemmas', []) if l not in seen_lemmas and len(l) > 1 and l not in STOP]
    for lem in new:
        for cut in range(len(lem), 0, -1):       # longest prefix of the lemma found in the surface
            stem = lem[:cut]
            if (KANJI.search(stem) or cut == len(lem)) and stem in entry['kanji']:
                return stem
    return None

STOP = set('する いる ある なる です ます だ から まで ない こと もの'.split())

def main():
    root = db.ROOT
    deck = json.load(open(os.path.join(root, 'data', 'combined_deck.json')))
    con = db.connect()
    seen = set()
    n = 0
    for e in deck:
        target = find_target(e, seen)
        for l in e.get('lemmas', []): seen.add(l)
        core = {'id', 'position', 'deck', 'type', 'block', 'kanji', 'furigana', 'furigana_tokens', 'gloss', 'audio', 'image', 'explanation'}
        extra = {k: v for k, v in e.items() if k not in core}
        con.execute('''INSERT INTO cards(id, position, deck, type, block, kanji, furigana, tokens, gloss, audio, image, explanation, target, extra)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                       ON CONFLICT(id) DO UPDATE SET position=excluded.position, deck=excluded.deck, type=excluded.type,
                         block=excluded.block, kanji=excluded.kanji, furigana=excluded.furigana, tokens=excluded.tokens,
                         gloss=excluded.gloss, audio=excluded.audio, image=excluded.image, explanation=excluded.explanation,
                         target=excluded.target, extra=excluded.extra''',
                    (e['id'], e['position'], e['deck'], e['type'], e['block'], e['kanji'], e['furigana'],
                     json.dumps(e['furigana_tokens'], ensure_ascii=False), e['gloss'], e['audio'], e['image'],
                     e['explanation'] or '', json.dumps(target, ensure_ascii=False), json.dumps(extra, ensure_ascii=False)))
        n += 1
    con.commit()
    print(f'imported {n} cards into {db.DB_PATH}')
    print('cards with a highlight target:', con.execute("SELECT count(*) FROM cards WHERE target != 'null'").fetchone()[0])

if __name__ == '__main__':
    main()
