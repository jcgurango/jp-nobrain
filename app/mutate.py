"""Mutate tier prompts: the learner sees the kanji sentence and is asked to say it differently.
No answers are generated; the learner self-grades after the reveal."""
import hashlib

PROMPTS = [
    ('register', 'Flip the register', 'Say it in the opposite politeness level: casual if it is polite, polite if it is casual.'),
    ('one_word', 'Change one word', 'Keep the structure, swap one content word for another that fits.'),
    ('new_sentence', 'Use it in a different sentence', 'Take the key word or grammar point and build a new sentence around it.'),
    ('negate', 'Say the opposite', 'Negate it, or flip its meaning some other way.'),
    ('tense', 'Shift the time', 'Move it into the past if it is present, or into the present if it is past.'),
    ('question', 'Ask it as a question', 'Turn the statement into a question someone could ask.'),
    ('answer', 'Reply to it', 'Imagine someone said this to you. Answer in Japanese.'),
    ('expand', 'Add detail', 'Say the same thing with one extra piece of information: when, where, why or who.'),
    ('shorten', 'Say it shorter', 'Drop everything that context would make obvious and keep it natural.'),
]

SHORT_OK = {'register', 'new_sentence', 'answer', 'expand'}   # prompts that make sense for one-word cards / greetings

def mutation_for(card, seed):
    h = int(hashlib.md5(f"{card['id']}|{seed}".encode()).hexdigest(), 16)
    pool = PROMPTS
    if len(card.get('extra', {}).get('lemmas') or card['kanji'].split()) <= 1 and len(card['kanji']) <= 8:
        pool = [p for p in PROMPTS if p[0] in SHORT_OK]
    key, label, hint = pool[h % len(pool)]
    return {'key': key, 'instruction': label, 'hint': hint}
