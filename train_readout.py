"""Train the fly readout on YOUR deck decisions.

Label sources, best first:
  1. Your kept cards                        -> 1.0
  2. EDHREC outRecs for your own list       -> 0.0   (EDHREC says "cut this",
                                                      you kept it or not —
                                                      strongest near-miss signal)
  3. EDHREC recommends it, you didn't play  -> 0.0   (considered, rejected)

Random in-identity cards are NOT used as negatives. They'd teach the model
"is this card legal here", which EDHREC already answers.

Run:  python train_readout.py
"""

import os

import numpy as np

import edhrec_client as edhrec
import scryfall
from fetch_training_decks import load_my_decks
from fly_reservoir import FlyReservoir, Readout, card_features, load_connectome

CONNECTOME = os.environ.get("CONNECTOME", "malecns.safetensors")
NEURONS = 1500        # small on purpose: see the overfit note in README
ALPHA_SWEEP = [1.0, 10.0, 100.0, 1000.0, 10000.0]
OUT = "readout_W.npy"


def enrich(names):
    details = scryfall.collection(list(names))
    roles = {}
    out = []
    for name in names:
        d = details.get(name)
        if d:
            out.append({**d, "role": roles.get(name, "other"),
                        "synergy": 0.0, "inclusion_pct": 0.0})
    return out


def feedback_dataset(reservoir):
    """Labels from decks you actually built and edited here.

    These are BETTER than exported decklists: a cut card is one you saw in
    context and rejected. Exports only show survivors.
    """
    import feedback
    pairs = feedback.training_pairs()
    if not pairs:
        return [], []
    by_name = {}
    for name, label, _ in pairs:
        by_name.setdefault(name, []).append(label)
    # A card kept in one deck and cut from another averages out rather than
    # contradicting itself.
    states, labels = [], []
    for card in enrich(list(by_name)):
        vals = by_name[card["name"]]
        states.append(reservoir.state(card_features(card)))
        labels.append(sum(vals) / len(vals))
    print(f"feedback: {len(states)} labelled cards from your builds")
    return states, labels


def build_dataset(reservoir):
    decks = load_my_decks()
    states, labels = feedback_dataset(reservoir)
    seen = 0

    if not decks and not states:
        raise SystemExit(
            "No training data. Either export decks to decks/mine/ "
            "(see fetch_training_decks.py) or build and give feedback on a "
            "few decks first (see feedback.py)."
        )
    for commander, kept_list in decks.items():
        kept = set(kept_list)
        recs = {c["name"] for c in edhrec.commander_pool(commander)}

        rejected = recs - kept
        try:
            _, cut = edhrec.refine(commander, sorted(kept))
            rejected |= {n for n in cut if n in kept}   # EDHREC says cut it
        except Exception as e:
            print(f"  ({commander}: recs() unavailable — {e})")

        print(f"{commander}: {len(kept)} kept / {len(rejected)} rejected")
        seen += 1

        for card in enrich(kept):
            states.append(reservoir.state(card_features(card))); labels.append(1.0)
        for card in enrich(rejected):
            states.append(reservoir.state(card_features(card))); labels.append(0.0)

    if seen < 3 and len(labels) < 300:
        print("\nWARNING: thin training set. Expect the holdout correlation "
              "to be noise. Build decks and give feedback — that accumulates "
              "labels faster than exporting old decks.")
    return np.array(states), np.array(labels)


def holdout(X, y, alpha, frac=0.2, seed=0):
    """Train/test split. Near-zero test correlation means it memorised."""
    rng = np.random.default_rng(seed)
    idx = rng.permutation(len(y))
    cut = int(len(y) * (1 - frac))
    tr, te = idx[:cut], idx[cut:]
    r = Readout(alpha=alpha)
    r.fit(X[tr], y[tr])
    preds = np.array([r.predict(s) for s in X[te]])
    if preds.std() == 0 or y[te].std() == 0:
        return r, 0.0
    return r, float(np.corrcoef(preds, y[te])[0, 1])


if __name__ == "__main__":
    if not os.path.exists(CONNECTOME):
        raise SystemExit(f"Missing {CONNECTOME} — see README for the download.")

    print(f"Loading connectome ({NEURONS} neurons)...")
    reservoir = FlyReservoir(load_connectome(CONNECTOME, max_neurons=NEURONS))

    X, y = build_dataset(reservoir)
    print(f"\n{len(y)} samples, {X.shape[1]} state dims, {int(y.sum())} positive")

    best, best_corr = None, -2
    for alpha in ALPHA_SWEEP:
        r, corr = holdout(X, y, alpha)
        flag = "  <-- best" if corr > best_corr else ""
        if corr > best_corr:
            best, best_corr = r, corr
        print(f"  alpha={alpha:>9}  holdout corr={corr:+.3f}{flag}")

    np.save(OUT, best.W)
    print(f"\nSaved {OUT}  (corr={best_corr:+.3f})")
    if best_corr < 0.15:
        print("\nThat correlation is basically noise. In order of likelihood:")
        print("  1. too few decks (this is almost always it)")
        print("  2. feature vector too thin — 8 numbers is not much")
        print("  3. negatives too easy to separate")
        print("  MORE NEURONS WILL NOT HELP. Don't raise NEURONS to fix this.")
