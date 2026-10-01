"""
Fly-connectome reservoir scorer.

The connectome is a FROZEN recurrent network. Nothing about it is trained.
Card features go in, activity propagates a few steps through real synaptic
weights, and the resulting high-dimensional state is read out by a ridge
regression trained on the user's own deck decisions.

Honest framing: this is reservoir computing. The reservoir supplies a fixed
nonlinear feature expansion; a random sparse matrix of similar size/density
would likely score the same. The fly's topology encodes fly behaviour, not
Magic. All learning lives in Readout.W.

Connectome source (THIRD-PARTY repackaging of Janelia MaleCNS v1.0, not
official — verify against neuPrint before trusting):
  https://huggingface.co/QuixiAI/MaleCNS
Official data + docs: https://male-cns.janelia.org/download/

pip install numpy scipy safetensors
"""

import numpy as np
from scipy import sparse
from safetensors.numpy import load_file

# Feature order must stay stable — the readout is trained against these slots.
FEATURES = ["cmc", "synergy", "inclusion_pct", "is_creature",
            "is_ramp", "is_draw", "is_removal", "is_protection"]


def load_connectome(path, max_neurons=20000):
    """Build a sparse weight matrix from the safetensors dump.

    max_neurons subsamples to the lowest-id neurons. The full graph is
    ~166k neurons / 125M edges — dense is impossible, and even sparse the
    full thing is slow to iterate on. Start small, scale up once it works.
    """
    t = load_file(path)
    src, dst, w = t["edge_src"], t["edge_dst"], t["synapse_count"]

    keep = (src < max_neurons) & (dst < max_neurons)
    src, dst, w = src[keep], dst[keep], w[keep].astype(np.float32)

    W = sparse.csr_matrix((w, (src, dst)), shape=(max_neurons, max_neurons))

    # Spectral scaling: keeps activity from exploding or dying across steps.
    # 0.9 < 1.0 means the reservoir forgets slowly instead of saturating.
    norm = sparse.linalg.norm(W)
    return W * (0.9 / norm) if norm else W


def card_features(card):
    role = card.get("role", "other")
    return np.array([
        float(card.get("cmc") or 0) / 10.0,
        float(card.get("synergy") or 0.0),
        float(card.get("inclusion_pct") or 0.0),
        1.0 if "creature" in (card.get("type_line") or "").lower() else 0.0,
        1.0 if role == "ramp" else 0.0,
        1.0 if role == "draw" else 0.0,
        1.0 if role == "removal" else 0.0,
        1.0 if role == "protection" else 0.0,
    ], dtype=np.float32)


class FlyReservoir:
    def __init__(self, W, steps=5, leak=0.7, seed=0):
        self.W, self.steps, self.leak = W, steps, leak
        n = W.shape[0]
        rng = np.random.default_rng(seed)
        # Fixed random projection from feature space into neuron space.
        # Sparse on purpose: each feature stimulates a small neuron subset,
        # the way a sensory input would.
        self.W_in = rng.normal(0, 1, size=(len(FEATURES), n)).astype(np.float32)
        self.W_in *= (rng.random((len(FEATURES), n)) < 0.01)

    def state(self, features):
        """Propagate and return the settled activity vector."""
        x = np.zeros(self.W.shape[0], dtype=np.float32)
        drive = features @ self.W_in
        for _ in range(self.steps):
            x = (1 - self.leak) * x + self.leak * np.tanh(x @ self.W + drive)
        return x


class Readout:
    """Ridge regression. This is the only trained component."""

    def __init__(self, alpha=1.0):
        self.alpha, self.W = alpha, None

    def fit(self, states, labels):
        X = np.asarray(states, dtype=np.float32)
        y = np.asarray(labels, dtype=np.float32)
        A = X.T @ X + self.alpha * np.eye(X.shape[1], dtype=np.float32)
        self.W = np.linalg.solve(A, X.T @ y)

    def predict(self, state):
        if self.W is None:
            raise RuntimeError("Readout not trained — call fit() first.")
        return float(state @ self.W)


def build_training_set(reservoir, kept_cards, rejected_cards):
    """kept -> 1.0, rejected -> 0.0.

    Rejected cards are NOT optional. Trained on positives only, the readout
    learns to output 1.0 for everything and tells you nothing. Use cards you
    considered and cut, or cards in-identity you deliberately never played.
    """
    if not rejected_cards:
        raise ValueError("Need rejected cards — positives-only training is useless.")
    states, labels = [], []
    for card in kept_cards:
        states.append(reservoir.state(card_features(card)))
        labels.append(1.0)
    for card in rejected_cards:
        states.append(reservoir.state(card_features(card)))
        labels.append(0.0)
    return states, labels


def taste_scores(reservoir, readout, pool):
    return {c["name"]: readout.predict(reservoir.state(card_features(c)))
            for c in pool}


def blend(stat_score, taste_score, taste_weight=0.3):
    """Keep the statistical score dominant. The fly is a personal-taste
    nudge on top of real data, not a replacement for it."""
    return (1 - taste_weight) * stat_score + taste_weight * taste_score
