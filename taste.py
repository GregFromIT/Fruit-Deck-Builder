"""Load a trained readout and score a card pool. No-ops cleanly if untrained,
so the builder works with or without the fly stage."""

import os

import numpy as np

from fly_reservoir import FlyReservoir, Readout, card_features, load_connectome

CONNECTOME = os.environ.get("CONNECTOME", "malecns.safetensors")
WEIGHTS = "readout_W.npy"
NEURONS = 1500  # MUST match train_readout.NEURONS or the dims won't line up


def load_taste():
    """Returns a scorer fn, or None if not trained yet."""
    if not (os.path.exists(WEIGHTS) and os.path.exists(CONNECTOME)):
        return None
    reservoir = FlyReservoir(load_connectome(CONNECTOME, max_neurons=NEURONS))
    readout = Readout()
    readout.W = np.load(WEIGHTS)

    def score(pool):
        raw = {c["name"]: readout.predict(reservoir.state(card_features(c)))
               for c in pool}
        # Normalise to 0..1 so taste_weight blends against score_card sanely.
        vals = list(raw.values())
        lo, hi = min(vals), max(vals)
        span = (hi - lo) or 1.0
        return {k: (v - lo) / span for k, v in raw.items()}

    return score
