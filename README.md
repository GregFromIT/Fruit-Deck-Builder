# Commander Deckbuilder + Fly Reservoir

Theme-directed EDH deckbuilder. EDHREC and Scryfall do the statistics;
an optional frozen fruit-fly connectome supplies a personal-taste layer
trained on your own decks.

---

## HANDOFF — read this first

**The builder works today without training.** The fly stage is inert until
you feed it data. It gets better the more decks you build and edit here.

### Step 1 — install
```
pip install -r requirements.txt
```
If `mightstone` fights you, check your interpreter (`poetry env info`) first.
It failed to build in my sandbox with a package-metadata error, so it may
want a specific Python version. Most likely setup blocker.

### Step 2 — verify the Tagger slugs

> **Fixed in 0.2:** Scryfall requires `User-Agent` and `Accept` headers and
> returns HTTP 400 without them. v0.1 sent neither, so every Scryfall call
> failed. `scryfall.HEADERS` now sets both. If you fork this, don't let your
> HTTP library pick the User-Agent — Scryfall flags library defaults as junk
> traffic.
> https://scryfall.com/docs/faqs/i-m-having-trouble-accessing-the-scryfall-api-or-i-m-blocked-17

```
python cli.py --verify-tags
```
Any line showing `0` is a **wrong slug**, not "no such cards". The `otag:`
values in `scryfall.py` are educated guesses — Tagger's vocabulary is
community-curated with no canonical published list. Fix zeros by searching
the tag on scryfall.com.

If you skip this the builder still works: it falls back to oracle-text
matching and tells you it did. Just worse role classification.

### Step 3 — build a deck
```
python cli.py
```
Prints EDHREC's themes for the commander, builds, writes a `.txt`, and
gives you a `build_id`. It will always produce 100 cards or explain why not.

### Step 4 — teach it (THIS IS THE IMPORTANT PART)
Edit the deck however you like, then:
```
python cli.py --feedback <build_id>
```
Paste your final list. It diffs against what was proposed and records
kept / cut / added.

Or use the Flask UI (`python app.py`), which shows the deck with tick
boxes — untick what you'd cut, type what you'd add, submit.

**Why this beats exporting old decks:** a card you cut from a generated
list is one you saw *in context* and rejected. Exported decklists only show
survivors — they never tell you what was considered. Every build you give
feedback on adds ~100 labelled cards.

### Step 5 — check progress
```
python cli.py --stats
```
Retraining is worth it from roughly 300 labelled cards, i.e. about 3–4
builds with feedback.

### Step 6 — connectome + train
Download MaleCNS v1.0 safetensors to `malecns.safetensors`:
https://huggingface.co/QuixiAI/MaleCNS

**Third-party repackaging, not official Janelia.** Verify tensor shapes
against neuPrint first: https://male-cns.janelia.org/download/
Its `neuron_id` has ~88M entries vs the 166,700 proofread neurons, so it
includes unproofread fragments. `load_connectome` subsamples by lowest
index, which is arbitrary — filtering on `neuron_status` would be better.
Left as your call.

```
python train_readout.py
```
Uses your feedback log AND anything in `decks/mine/`.

**Report back the holdout correlation.** That number decides whether the
fly stage earns its place:
- `< 0.15` — noise. Expected early. Build more decks, give more feedback.
- `0.15–0.35` — weak but real.
- `> 0.35` — check for leakage before believing it.

**Do not raise `NEURONS` to fix a bad number.** More reservoir dimensions
against the same small sample makes overfitting worse. Fixes in order:
more feedback, richer features, harder negatives.

### Step 7 — build with taste
Once `readout_W.npy` exists, `cli.py` and `app.py` pick it up automatically
and `taste_weight` activates.

---

## The improvement loop

```
   build  ──►  you edit  ──►  feedback logged  ──►  retrain
     ▲                                                │
     └────────────  better scoring  ◄─────────────────┘
```

`feedback.jsonl` is append-only. Nothing is lost, and you can re-derive
labels differently later without rebuilding history.

Labels: kept → 1.0, **added → 1.0** (strongest signal — you wanted it
enough to type it in), cut → 0.0. Cards never proposed and never added are
left *unlabelled*, because absence is not rejection.

## What I verified vs. what I guessed

**Verified by running it here:**
- Reservoir propagation is numerically stable; state std ≈ 0.108, all finite.
- Readout recovers a planted synthetic signal at +0.69 holdout. The maths works.
- `assemble()` produces exactly 62 nonlands; curve caps bind; land split
  sums to 37; export totals 100 cards.

**Verified by reading the mightstone 0.4.0 wheel source (not run):**
- `EdhRecStatic.commander(name, sub)` → `/pages/commanders/<slug>[/<sub>].json`
- `EdhRecCommander.themes` / `.budget` → `(value, href-suffix, count)`
- `EdhRecCommander.cards[].items[]` → `EdhRecCardItem`
- `EdhRecCardItem.name / .synergy / .num_decks / .potential_decks`
- `EdhRecApi.recs()` → `EdhRecRecs(inRecs=[], outRecs=[])`

**Guessed, needs your verification:**
- Every `otag:` slug in `ROLE_OTAGS` (step 2 above).
- Whether mightstone's methods are coroutines or sync in your install —
  `edhrec_client._sync()` handles both, but it's untested against the real lib.
- Moxfield/Archidekt API response shapes in `fetch_training_decks.py`.
- Role quota numbers. Made up, not derived.

---

## Architecture

```
  EDHREC (theme-scoped)  ──┐
  Scryfall otag/kw queries ─┴──►  POOL  ──►  ENRICH (cmc/type/price/role)
                                               │
                                               ▼
                                    SCORE  synergy + novelty
                                               │  (+ fly taste, optional)
                                               ▼
                                    FILL   role quotas → curve caps → best rest
                                               │
                                               ▼
                                    REFINE EDHREC recs() sees the real list
                                               │
                                               ▼
                                    LANDS  basics by actual colour pips
```

### Scoring
```
score = synergy_weight * synergy + novelty_weight * (1 - inclusion_pct)
```
High synergy + low inclusion = good but non-obvious. `min_synergy` is a
quality floor so a card can't win on rarity alone.

With the fly:
```
final = (1 - taste_weight) * score + taste_weight * taste
```

### Why the fly, honestly
It's reservoir computing: a frozen high-dimensional nonlinear feature
expansion. **A random sparse matrix of the same size and density would very
likely perform identically.** The connectome's topology encodes fly
behaviour, not Magic. All learning lives in `Readout.W`, one ridge
regression. It's in here because it's fun and reproducible, not because the
fly knows anything about deckbuilding. Don't over-read its output.

---

## Files

| file | purpose |
|---|---|
| `cli.py` | entry point; `--verify-tags`, `--spec` |
| `deckbuilder.py` | DeckSpec, scoring, assembly, curve, lands, refine |
| `edhrec_client.py` | mightstone wrapper: themes, pools, curve, recs() |
| `scryfall.py` | search, collection, Tagger role map, tag verification |
| `cache.py` | disk cache (7-day TTL) |
| `fly_reservoir.py` | connectome loading, propagation, ridge readout |
| `train_readout.py` | trains readout on your decks |
| `taste.py` | loads trained readout; no-ops if absent |
| `fetch_training_decks.py` | your decks + optional public deck fetch |
| `app.py` / `templates/` | Flask UI with theme dropdown |

---

## Robustness

The builder degrades rather than crashing. Verified by simulating total
failure (EDHREC down + every otag slug broken): still produced a legal
100-card deck with three warnings explaining what went wrong.

Fallback chain: EDHREC theme → EDHREC untuned → Scryfall only; Tagger
roles → oracle-text matching; short pool → widened search. Every fallback
appends to `deck["warnings"]`, shown in both CLI and UI.

## Known gaps / open decisions

- **Role quotas are floors, not ceilings.** Protection with quota 3 can end
  up with 10 slots because leftover backfill ignores role. If you want caps,
  filter `leftover` by `used_roles[c['role']] < quota`.
- **Query-sourced cards have synergy 0.** They can fill role quotas (roles
  now come from Scryfall) but never outrank EDHREC picks on score. Scryfall
  knows a card *is* card-draw; it has no opinion on whether it's good with
  your commander. Only EDHREC has that, only for themes it has pages for.
- **EDHREC budget ≠ your price cap.** EDHREC's budget subsets are deck-level
  percentiles (top 10% cheapest decks for that commander). `max_price` is a
  per-card hard cutoff. Complementary; both are wired in.
- **Budget and theme are mutually exclusive** on EDHREC's side.
- No LLM refinement stage yet. The design discussed: fan the assembled 99 +
  a 30-card bench out to several models independently, tally cut/keep votes,
  gate every suggestion through Scryfall validation (exists, colour identity,
  legality, price) before applying. Not built.
- `land_split` does basics only. No duals, no utility lands.

## Data sources

- Scryfall API — official, documented: https://scryfall.com/docs/api
  Syntax incl. Tagger tags: https://scryfall.com/docs/syntax
- EDHREC — **no official API**. Reverse-engineered static JSON at
  json.edhrec.com plus the dynamic edhrec.com/api/, accessed via mightstone:
  https://mightstone.readthedocs.io/en/latest/reference/api.html
  This can break without notice.
- MaleCNS v1.0 connectome: https://male-cns.janelia.org/download/
