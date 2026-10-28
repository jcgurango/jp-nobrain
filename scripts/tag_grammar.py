#!/usr/bin/env python3
"""Tag each JLAB sentence card as teaching a NEW grammar point or not.

JLAB has no explicit grammar tags. The author's pattern is: when a new grammar point is
introduced, the card's explanation carries a paragraph describing it, and that same paragraph
is copy-pasted onto the next few "usage" cards. Often the first card also links the relevant
Tae Kim chapter/section. So a card is tagged `is_grammar` when it is the FIRST card to carry
  (a) an explanation paragraph that is later repeated verbatim on other cards, or
  (b) a Tae Kim (guidetojapanese.org) URL not linked before, or
  (c) a long, grammar-flavoured explanation paragraph (keyword heuristic) even if never repeated.
Pure word glosses ("amai: sweet"), "Reminder:" paragraphs and translations never count.

Usage: python3 -I scripts/tag_grammar.py   (rewrites data/jlab_cards.json in place)
"""
import json, os, re, sys
from collections import Counter, defaultdict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PATH = os.path.join(ROOT, 'data', 'jlab_cards.json')

GLOSS_RE = re.compile(r"^[a-zA-Z][a-zA-Z\-'/ ()]*\s*:\s")
SKIP_RE = re.compile(r"^(reminder|remark|note that we already|you already understand|as mentioned|as you (already )?know|again,? note|we already had)", re.I)
GRAMMAR_KW = re.compile(r"(\b(particle|conjugat\w*|tense|negative form|polite form|potential form|passive|causative|volitional|imperative|conditional|suffix|prefix|grammar|verb stem|the stem|auxiliary|construction|nominaliz\w*|casual version|contraction|relative clause|sub-?clause|-te form|te-form|-ta form|-tai form|na-adjective|i-adjective|counter|honorific|humble|keigo|teineigo|sentence[- ]ending|is attached|attach(ed|ing)? (to|it|this)|replace .{1,30} (with|by)|is used (to|when|for|if)|can be used (to|when|for|as))\b|\b(da|desu|ha|wa|ga|wo|ni|de|to|mo|no|ne|yo|zo|ka|kara|made|kedo|node|noni|tte|nara|tara|ba|koto|mono|you|sou|rashii|mitai|hazu|beki|dake|shika|bakari|hodo|kurai)\b.{0,40}\b(particle|form|means|is used|expresses|indicates|marks))", re.I)

WINDOW = 25        # cards: how far back a near-identical explanation counts as the same grammar point
DUP_JACCARD = 0.35
STOP = set('the a an of to in is it this that and or for on as be with you can are not by from at which also e g i we he she they'.split())

def norm(line):
    return re.sub(r'[^a-z0-9぀-ヿ一-鿿]+', '', line.lower())

def norm_url(u):
    u = re.sub(r'^https?://(www\.)?', '', u.strip().lower())
    return u.rstrip('/').split(' ')[0]

def candidate_lines(card):
    """Explanation lines that could describe a grammar point (not glosses, reminders, translation)."""
    lines = [l.strip() for l in card['explanation'].split('\n') if l.strip()]
    out = []
    for i, l in enumerate(lines):
        if len(l) < 60: continue
        if GLOSS_RE.match(l): continue
        if SKIP_RE.match(l): continue
        if i == 0 and l == card['gloss']: continue   # translation line
        out.append(l)
    return out

def main():
    cards = json.load(open(PATH))
    # pass 1: how many cards carry each normalized explanation line
    line_cards = defaultdict(list)
    for c in cards:
        for l in candidate_lines(c):
            line_cards[norm(l)].append(c['order'])
    seen_lines, seen_urls = set(), set()
    stats = Counter()
    recent = []   # (order, token set, taekim page) of accepted grammar cards
    def toks(l): return set(re.findall(r'[a-z\u3040-\u30ff\u4e00-\u9fff]+', l.lower())) - STOP
    def near_dup(c, l):
        t = toks(l)
        for o, rt, _ in recent:
            if c['order'] - o > WINDOW: continue
            if len(t & rt) / max(1, len(t | rt)) >= DUP_JACCARD: return o
        return None
    for c in cards:
        reasons, keys = [], []; dup = None
        for l in candidate_lines(c):
            n = norm(l)
            if n in seen_lines: continue
            seen_lines.add(n)
            if len(set(line_cards[n])) >= 2 or GRAMMAR_KW.search(l):
                d = near_dup(c, l)
                if d is not None: dup = d; continue
                reasons.append('repeated_explanation' if len(set(line_cards[n])) >= 2 else 'grammar_keywords'); keys.append(l)
        for u in c['references']:
            if 'guidetojapanese' not in u: continue
            nu = norm_url(u)
            if nu in seen_urls: continue
            seen_urls.add(nu)
            page = nu.split('#')[0]
            # a bare link is weak evidence: skip if the same Tae Kim page or any grammar card was just seen
            if not reasons and (any(c['order'] - o <= 3 for o, _, _ in recent) or any(c['order'] - o <= WINDOW and pg == page for o, _, pg in recent)):
                dup = dup if dup is not None else recent[-1][0]; continue
            reasons.append('new_taekim_link'); keys.append(u)
        if reasons:
            page = next((norm_url(u).split('#')[0] for u in c['references'] if 'guidetojapanese' in u), None)
            recent.append((c['order'], toks(keys[0]), page))
        c['grammar_dup_of'] = dup
        c['is_grammar'] = bool(reasons)
        c['grammar_reasons'] = reasons
        c['grammar_key'] = keys[0] if keys else None
        for r in set(reasons): stats[r] += 1
    # hand-reviewed overrides
    ov_path = os.path.join(ROOT, 'data', 'grammar_overrides.json')
    if os.path.exists(ov_path):
        ov = json.load(open(ov_path))
        for o in ov.get('untag', []):
            cards[o]['is_grammar'] = False; cards[o]['grammar_reasons'] = ['manual_untag']
        for o, key in ov.get('tag', {}).items():
            c = cards[int(o)]; c['is_grammar'] = True; c['grammar_reasons'] = ['manual_tag']; c['grammar_key'] = key
    json.dump(cards, open(PATH, 'w'), ensure_ascii=False, indent=1)
    g = [c for c in cards if c['is_grammar']]
    print(f'{len(g)} / {len(cards)} JLAB cards tagged as new grammar point')
    print('signal counts:', dict(stats))
    print('reason combos:', Counter(tuple(sorted(set(c["grammar_reasons"]))) for c in g).most_common())
    gaps = Counter()
    last = -1
    for c in g:
        gaps[min(c['order'] - last - 1, 30)] += 1; last = c['order']
    print('vocab cards between grammar cards (capped 30):', sorted(gaps.items()))
    if '--list' in sys.argv:
        lo, hi = (int(x) for x in sys.argv[sys.argv.index('--list') + 1].split(':'))
        for c in cards[lo:hi]:
            flag = 'G' if c['is_grammar'] else ' '
            print(f"{flag} {c['order']:4d} {c['kanji']:<22} | {c['gloss'][:50]:<50} | {','.join(c['grammar_reasons'])} | {(c['grammar_key'] or '')[:90]}")

if __name__ == '__main__':
    main()
