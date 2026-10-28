# jp-nobrain sentence bank

Source decks: `JLAB.apkg` (Japanese Like a Breeze, Tae Kim order, anime sentences) and
`Kaishi1.5k.apkg` (1,500 most common words, one sentence each).

## Pipeline

```
unzip JLAB.apkg -d raw/jlab ; unzip Kaishi1.5k.apkg -d raw/kaishi
python3 -I scripts/extract.py      # -> data/jlab_cards.json, data/kaishi_cards.json, media/
python3 -I scripts/tag_grammar.py  # adds is_grammar to JLAB cards (heuristic + data/grammar_overrides.json)
python3 -I scripts/build_deck.py   # -> data/combined_deck.json
```

`raw/` and `media/` are derived from the apkgs (media files are hardlinks into `raw/`).

## Ordering rules (as implemented)

1. JLAB cards keep course order. Each card tagged `is_grammar` opens a block; JLAB vocab/usage
   cards after it belong to that block, however many there are (the 1:10 ratio is a target, not
   a hard rule: 59 blocks have more than 10 JLAB vocab cards).
2. A block with fewer than 10 vocab cards is topped up with Kaishi cards, from the first block on.
3. Kaishi fill order: re-exposure first (Kaishi card whose word matches a JLAB lemma taught so
   far, oldest teaching first), then Kaishi deck order.
4. Kaishi cards left when JLAB ends are appended as a tail in Kaishi order (589 cards).
5. No redundancy stripping. Exact duplicate sentences are flagged via `duplicate_of` (36 entries).

## data/combined_deck.json

One entry per card, in study order. Common fields:

| field | meaning |
|---|---|
| `position`, `block` | study order; block index (block 0 has no grammar card, last block is the Kaishi tail) |
| `id`, `deck` | `jlab:<nid>` / `kaishi:<nid>`; `jlab` or `kaishi` |
| `type` | `grammar` (new grammar point, JLAB only) or `vocab` |
| `kanji` | sentence as written |
| `furigana` | Anki bracket format, e.g. `今日[きょう]は 用[よう] 事[じ]があります。` |
| `furigana_tokens` | `[[text, reading|null], ...]`, reading applies to the kanji run in `text` |
| `gloss` | English translation of the sentence |
| `audio`, `image` | paths relative to the project root |
| `explanation` | grammar card: the grammar-point paragraph; JLAB vocab: full remarks; Kaishi: word meaning (+notes) |
| `duplicate_of` | id of an earlier entry with the identical sentence, else null |

JLAB extras: `hiragana`, `romaji`, `lemmas`, `explanation_full`, `explanation_front`, `section`,
`section_intro` (preceding JLAB info card(s), text), `references`, `source`, `gloss_source`
(`translation` | `word_gloss` | `fallback` | null; 57 cards have no clean translation), `jlab_order`.

Kaishi extras: `word`, `word_reading`, `word_furigana`, `word_meaning`, `word_audio`,
`pitch_accent_html`, `frequency`, `fill_reason` (`re-exposure` | `kaishi-order` | `tail`),
`re_exposure_of` (JLAB card id that taught the word), `kaishi_order`.

## Grammar tagging

JLAB has no grammar tags. `scripts/tag_grammar.py` tags a card as a new grammar point when it is
the first card carrying (a) an explanation paragraph that is repeated verbatim on later cards,
(b) a Tae Kim link not seen before, or (c) a grammar-flavoured paragraph (keyword heuristic),
with near-duplicate suppression. Every hit was hand-reviewed; corrections live in
`data/grammar_overrides.json` (95 un-tags, 14 added). Result: 205 grammar cards, 1,871 vocab.
