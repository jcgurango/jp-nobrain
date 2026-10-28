#!/usr/bin/env python3
"""Build the combined, ordered sentence bank from the extracted JLAB and Kaishi cards.

Rules (see README):
  * JLAB cards keep their course order. Each JLAB grammar-point card opens a block; the JLAB
    vocab/usage cards that follow it belong to that block (however many there are).
  * If a block has fewer than VOCAB_PER_BLOCK vocab cards, it is topped up with Kaishi cards.
  * Kaishi fill order: first "re-exposure" cards (Kaishi word already taught by a JLAB card so
    far, oldest teaching first), then plain Kaishi deck order.
  * Kaishi cards left over when JLAB ends are appended as a tail in Kaishi order.

Usage: python3 -I scripts/build_deck.py
Output: data/combined_deck.json
"""
import json, os, re
from collections import deque

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, 'data')
VOCAB_PER_BLOCK = 10

KANJI = re.compile(r'[一-鿿㐀-䶿豈-﫿々〆ヶ]')

def furigana_tokens(s):
    """Anki bracket furigana -> [[text, reading|None], ...].
    A reading applies to the run of kanji immediately before the bracket (Kaishi writes
    'まで生[い]きたい' without the Anki space, so we do not rely on spaces)."""
    out = []
    buf = ''
    i = 0
    while i < len(s):
        ch = s[i]
        if ch == '[':
            j = s.find(']', i)
            if j == -1:
                buf += ch; i += 1; continue
            reading = s[i + 1:j]
            # split base: trailing kanji run of buf
            k = len(buf)
            while k > 0 and KANJI.match(buf[k - 1]): k -= 1
            if k == len(buf):   # no kanji before bracket: attach to the whole buffer word
                k = buf.rfind(' ') + 1
            plain, base = buf[:k], buf[k:]
            if plain.strip(): out.append([plain.rstrip(' ') if base else plain, None])
            if base: out.append([base, reading])
            buf = ''
            i = j + 1
            if i < len(s) and s[i] == ' ': i += 1   # Anki separator space
            continue
        buf += ch; i += 1
    if buf: out.append([buf, None])
    # merge adjacent plain tokens
    merged = []
    for t in out:
        if merged and t[1] is None and merged[-1][1] is None: merged[-1][0] += t[0]
        else: merged.append(t)
    return merged

def unify_jlab(c, kind, block):
    return {
        'id': c['id'], 'deck': 'jlab', 'type': kind, 'block': block,
        'kanji': c['kanji'], 'furigana': c['furigana'], 'furigana_tokens': furigana_tokens(c['furigana']),
        'hiragana': c['hiragana'], 'romaji': c['romaji'], 'gloss': c['gloss'],
        'audio': f"media/jlab/{c['audio']}", 'image': f"media/jlab/{c['image']}" if c['image'] else None,
        'explanation': c['grammar_key'] if kind == 'grammar' and c['grammar_key'] else c['explanation'],
        'explanation_full': c['explanation'], 'explanation_front': c['explanation_front'],
        'section': c['section'], 'section_intro': c['section_intro'],
        'references': c['references'], 'lemmas': c['lemmas'], 'source': c['source'],
        'gloss_source': c['gloss_source'],
        'jlab_order': c['order'],
    }

def unify_kaishi(k, block, fill_reason, taught_by=None):
    return {
        'id': k['id'], 'deck': 'kaishi', 'type': 'vocab', 'block': block,
        'kanji': k['kanji'], 'furigana': k['furigana'], 'furigana_tokens': furigana_tokens(k['furigana']),
        'gloss': k['gloss'],
        'audio': f"media/kaishi/{k['audio']}" if k['audio'] else None,
        'image': f"media/kaishi/{k['image']}" if k['image'] else None,
        'word': k['word'], 'word_reading': k['word_reading'], 'word_furigana': k['word_furigana'],
        'word_meaning': k['word_meaning'],
        'word_audio': f"media/kaishi/{k['word_audio']}" if k['word_audio'] else None,
        'explanation': k['word_meaning'] + (('\n' + k['explanation']) if k['explanation'] else ''),
        'pitch_accent_html': k['pitch_accent_html'], 'frequency': k['frequency'],
        'fill_reason': fill_reason, 're_exposure_of': taught_by,
        'kaishi_order': k['order'],
    }

def main():
    J = json.load(open(os.path.join(DATA, 'jlab_cards.json')))
    K = json.load(open(os.path.join(DATA, 'kaishi_cards.json')))

    # Kaishi lookup by word and by reading (kana-only JLAB lemmas)
    by_word, by_reading = {}, {}
    for k in K:
        by_word.setdefault(k['word'], []).append(k)
        by_reading.setdefault(k['word_reading'], []).append(k)

    used = set()
    reexposure = deque()     # Kaishi cards whose word JLAB has taught, FIFO
    queued = set()
    kaishi_iter = iter(K)

    def note_taught(jcard):
        for lem in jcard['lemmas']:
            for k in by_word.get(lem, []) + (by_reading.get(lem, []) if not KANJI.search(lem) else []):
                if k['id'] not in queued and k['id'] not in used:
                    queued.add(k['id']); reexposure.append((k, jcard['id']))

    def next_fill():
        while reexposure:
            k, src = reexposure.popleft()
            if k['id'] not in used: return k, 're-exposure', src
        for k in kaishi_iter:
            if k['id'] not in used: return k, 'kaishi-order', None
        return None, None, None

    # split JLAB into blocks
    blocks, cur = [], []
    for c in J:
        if c['is_grammar'] and cur:
            blocks.append(cur); cur = []
        cur.append(c)
    blocks.append(cur)

    deck = []
    stats = {'blocks': 0, 'filled_blocks': 0, 'fill_cards': 0, 're_exposure': 0, 'kaishi_order': 0}
    for bi, block in enumerate(blocks):
        stats['blocks'] += 1
        vocab_n = 0
        for c in block:
            kind = 'grammar' if c['is_grammar'] else 'vocab'
            deck.append(unify_jlab(c, kind, bi))
            note_taught(c)
            if kind == 'vocab': vocab_n += 1
        filled = False
        while vocab_n < VOCAB_PER_BLOCK:
            k, reason, src = next_fill()
            if k is None: break
            used.add(k['id'])
            deck.append(unify_kaishi(k, bi, reason, src))
            vocab_n += 1; filled = True
            stats['fill_cards'] += 1
            stats['re_exposure' if reason == 're-exposure' else 'kaishi_order'] += 1
        if filled: stats['filled_blocks'] += 1
    # tail
    tail_block = len(blocks)
    tail = 0
    for k in K:
        if k['id'] in used: continue
        used.add(k['id'])
        deck.append(unify_kaishi(k, tail_block, 'tail'))
        tail += 1
    # flag (do not strip) exact duplicate sentences; both decks reuse a few sentences
    first_seen = {}
    for e in deck:
        key = re.sub(r'[\s。、！？!?｡]', '', e['kanji'])
        e['duplicate_of'] = first_seen.get(key)
        first_seen.setdefault(key, e['id'])
    for i, e in enumerate(deck): e['position'] = i
    json.dump(deck, open(os.path.join(DATA, 'combined_deck.json'), 'w'), ensure_ascii=False, indent=1)
    stats['tail_cards'] = tail; stats['total'] = len(deck)
    stats['duplicate_sentences_flagged'] = sum(1 for e in deck if e['duplicate_of'])
    stats['jlab_grammar'] = sum(1 for e in deck if e['deck'] == 'jlab' and e['type'] == 'grammar')
    stats['jlab_vocab'] = sum(1 for e in deck if e['deck'] == 'jlab' and e['type'] == 'vocab')
    stats['kaishi'] = sum(1 for e in deck if e['deck'] == 'kaishi')
    print(json.dumps(stats, indent=1))
    assert len({e['id'] for e in deck}) == len(deck)
    assert stats['kaishi'] == len(K) and stats['jlab_grammar'] + stats['jlab_vocab'] == len(J)

if __name__ == '__main__':
    main()
