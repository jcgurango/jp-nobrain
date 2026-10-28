#!/usr/bin/env python3
"""Extract JLAB and Kaishi 1.5k apkg contents (already unzipped into raw/) into clean JSON + media.

Usage: python3 -I scripts/extract.py
Outputs:
  data/jlab_cards.json      - JLAB sentence cards in course order (InfoNotes folded in as section intros)
  data/jlab_info_notes.json - the raw InfoNotes, for reference
  data/kaishi_cards.json    - Kaishi cards in deck order
  media/jlab/*, media/kaishi/* - media files with their real names (hardlinked from raw/)
"""
import html, json, os, re, shutil, sqlite3, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RAW = os.path.join(ROOT, 'raw')
DATA = os.path.join(ROOT, 'data')
MEDIA = os.path.join(ROOT, 'media')

def load(deck):
    db = sqlite3.connect(os.path.join(RAW, deck, 'collection.anki21'))
    models = json.loads(db.execute('select models from col').fetchone()[0])
    fields = {k: [f['name'] for f in v['flds']] for k, v in models.items()}
    rows = db.execute('''select n.id, n.mid, n.flds, n.tags, c.due from notes n
                         join cards c on c.nid = n.id where c.ord = 0 order by c.due''').fetchall()
    out = []
    for nid, mid, flds, tags, due in rows:
        d = dict(zip(fields[str(mid)], flds.split('\x1f')))
        d['_nid'] = nid; d['_model'] = models[str(mid)]['name']; d['_tags'] = tags.split(); d['_due'] = due
        out.append(d)
    return out

def text(s):
    """HTML -> plain text, paragraphs separated by newlines."""
    s = re.sub(r'(?i)<br\s*/?>', '\n', s)
    s = re.sub(r'(?i)</(p|li|ul|ol|div)>', '\n', s)
    s = re.sub(r'(?i)<li>', '- ', s)
    s = re.sub(r'<[^>]+>', '', s)
    s = html.unescape(s).replace('\xa0', ' ')
    s = re.sub(r'[ \t]+', ' ', s)
    s = re.sub(r' *\n *', '\n', s)
    s = re.sub(r'\n{3,}', '\n\n', s)
    return s.strip()

def links(s):
    return [html.unescape(u) for u in re.findall(r'href\s*=\s*"([^"]+)"', s)]

def sound(s):
    m = re.search(r'\[sound:([^\]]+)\]', s or '')
    return m.group(1) if m else None

def img(s):
    m = re.search(r'<img[^>]+src="([^"]+)"', s or '')
    return m.group(1) if m else None

def furigana(s):
    """Normalize Anki bracket furigana: single spaces, trimmed. Strips tags."""
    s = re.sub(r'<[^>]+>', '', s)
    s = html.unescape(s).replace('\xa0', ' ')
    return re.sub(r'\s+', ' ', s).strip()

def link_media(deck):
    base = os.path.join(RAW, deck)
    mapping = json.load(open(os.path.join(base, 'media')))
    dest = os.path.join(MEDIA, deck)
    os.makedirs(dest, exist_ok=True)
    n = 0
    for num, name in mapping.items():
        src = os.path.join(base, num); dst = os.path.join(dest, name)
        if os.path.exists(dst):
            continue
        try:
            os.link(src, dst)
        except OSError:
            shutil.copy2(src, dst)
        n += 1
    return len(mapping), n

# ---------------------------------------------------------------- JLAB
def extract_jlab():
    notes = load('jlab')
    cards, infos = [], []
    section = None; pending_intro = []
    for i, d in enumerate(notes):
        if d['_model'] == 'InfoNote':
            t = d['Text']
            m = re.search(r'<strong>(.*?)</strong>', t, re.S)
            title = text(m.group(1)) if m else text(t).split('\n')[0][:80]
            info = {'nid': d['_nid'], 'position': i, 'title': title, 'text': text(t), 'html': t, 'links': links(t)}
            infos.append(info)
            section = title
            pending_intro.append(info)
            continue
        back = d['RemarksBack']; front = d['RemarksFront']
        back_txt = text(back)
        paras = [p.strip() for p in back_txt.split('\n') if p.strip()]
        # English gloss: first paragraph unless it is a "romaji: meaning" dictionary line
        gloss, gloss_source = '', None
        GLOSS_LINE = r"^[a-zA-Z][a-zA-Z\-' ]*\s*:\s"
        if paras:
            if re.match(GLOSS_LINE, paras[0]) and len(d['Jlab-KanjiSpaced'].split()) <= 2:
                gloss = re.sub(GLOSS_LINE, '', paras[0]); gloss_source = 'word_gloss'   # single-word card: "romaji: meaning"
            elif not re.match(GLOSS_LINE, paras[0]):
                gloss = paras[0]; gloss_source = 'translation'
            else:
                # multi-word sentence whose first line is a word gloss: fall back to the first
                # prose line, which usually paraphrases the sentence. Flagged so the app can tell.
                for p in paras[1:]:
                    if not re.match(GLOSS_LINE, p):
                        gloss = p; gloss_source = 'fallback'; break
        cards.append({
            'id': f"jlab:{d['_nid']}",
            'source_deck': 'jlab',
            'order': len(cards),
            'course_position': i,
            'nid': d['_nid'],
            'section': section,
            'section_intro': [{'title': p['title'], 'text': p['text']} for p in pending_intro] or None,
            'source': text(d['Source']),
            'audio': sound(d['Audio']),
            'image': img(d['Image']),
            'kanji': furigana(d['Jlab-Kanji']).replace(' ', ''),
            'kanji_spaced': furigana(d['Jlab-KanjiSpaced']),
            'hiragana': furigana(d['Jlab-Hiragana']),
            'furigana': furigana(d['Other-Front']),
            'romaji': furigana(d['Jlab-ListeningFront']),
            'lemmas': furigana(d['Jlab-Lemma']).split(),
            'gloss': gloss,
            'gloss_source': gloss_source,
            'explanation': back_txt,
            'explanation_front': text(front) or None,
            'explanation_html': back,
            'references': links(d['References']),
            'references_text': text(d['References']) or None,
        })
        pending_intro = []
    return cards, infos

# ---------------------------------------------------------------- Kaishi
def extract_kaishi():
    notes = load('kaishi')
    cards = []
    for i, d in enumerate(notes):
        if not d['Word Reading'].strip():  # welcome / info card
            continue
        cards.append({
            'id': f"kaishi:{d['_nid']}",
            'source_deck': 'kaishi',
            'order': len(cards),
            'nid': d['_nid'],
            'word': text(d['Word']),
            'word_reading': text(d['Word Reading']),
            'word_furigana': furigana(d['Word Furigana']),
            'word_meaning': text(d['Word Meaning']),
            'word_audio': sound(d['Word Audio']),
            'kanji': text(d['Sentence']),
            'furigana': furigana(d['Sentence Furigana']),
            'gloss': text(d['Sentence Meaning']),
            'audio': sound(d['Sentence Audio']),
            'image': img(d['Picture']),
            'explanation': text(d['Notes']) or None,
            'pitch_accent_html': d['Pitch Accent'] or None,
            'pitch_accent_notes': text(d['Pitch Accent Notes']) or None,
            'frequency': int(d['Frequency']) if d['Frequency'].strip().isdigit() else None,
        })
    return cards

if __name__ == '__main__':
    os.makedirs(DATA, exist_ok=True)
    jl, infos = extract_jlab()
    ka = extract_kaishi()
    json.dump(jl, open(os.path.join(DATA, 'jlab_cards.json'), 'w'), ensure_ascii=False, indent=1)
    json.dump(infos, open(os.path.join(DATA, 'jlab_info_notes.json'), 'w'), ensure_ascii=False, indent=1)
    json.dump(ka, open(os.path.join(DATA, 'kaishi_cards.json'), 'w'), ensure_ascii=False, indent=1)
    print(f'jlab: {len(jl)} sentence cards, {len(infos)} info notes')
    print(f'kaishi: {len(ka)} cards')
    for deck in ('jlab', 'kaishi'):
        total, linked = link_media(deck)
        print(f'media/{deck}: {total} files ({linked} newly linked)')
    # sanity: every referenced media file exists
    missing = 0
    for c in jl:
        for k in ('audio', 'image'):
            if c[k] and not os.path.exists(os.path.join(MEDIA, 'jlab', c[k])): missing += 1
    for c in ka:
        for k in ('audio', 'image', 'word_audio'):
            if c[k] and not os.path.exists(os.path.join(MEDIA, 'kaishi', c[k])): missing += 1
    print('missing media refs:', missing)
