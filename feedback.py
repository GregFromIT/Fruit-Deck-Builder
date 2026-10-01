"""Learn from decks you actually build.

WHY THIS MATTERS MORE THAN THE BATCH TRAINING
---------------------------------------------
Training on your ~6 exported decks gives maybe 500 labelled cards, once.
Every build you edit here gives ~100 more, forever, and they're BETTER
labels: a card you cut from a generated list is a card you saw in context
and rejected, which is exactly the near-miss signal the readout needs.
Exported decks only tell you what survived; they don't tell you what was
considered.

FLOW
----
  build  ->  log_build()          records what the builder proposed
  you edit the list
  edit   ->  log_feedback()       records kept / cut / added
  later  ->  training_pairs()     feeds train_readout.py

Storage: feedback.jsonl, one JSON object per event. Append-only so nothing
is lost and you can always re-derive labels differently later.
"""

import json
import os
import time
import uuid

LOG = os.environ.get("MTG_FEEDBACK_LOG", "feedback.jsonl")


def _append(record):
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(json.dumps(record) + "\n")


def log_build(spec, deck, pool_names):
    """Record a generated deck plus the pool it was drawn from.

    The pool matters: cards in the pool that did NOT make the deck are the
    builder's own rejections, and if you later add one back manually that's
    a strong signal the scoring got it wrong.
    """
    build_id = uuid.uuid4().hex[:12]
    _append({
        "type": "build",
        "build_id": build_id,
        "ts": time.time(),
        "commander": spec.commander,
        "theme": spec.theme,
        "taste_weight": spec.taste_weight,
        "proposed": [c["name"] for c in deck["cards"]],
        "pool": list(pool_names),
    })
    return build_id


def log_feedback(build_id, final_cards, note=None):
    """Record your edited list against what was proposed.

    final_cards: the decklist you actually settled on (names).
    Derives kept/cut/added by diffing against the build record.
    """
    build = find_build(build_id)
    if not build:
        raise ValueError(f"No build {build_id} in {LOG}")

    proposed = set(build["proposed"])
    final = set(final_cards)

    _append({
        "type": "feedback",
        "build_id": build_id,
        "ts": time.time(),
        "commander": build["commander"],
        "kept": sorted(proposed & final),
        "cut": sorted(proposed - final),
        "added": sorted(final - proposed),
        "note": note,
    })


def _read():
    if not os.path.exists(LOG):
        return []
    out = []
    with open(LOG, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    out.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    return out


def find_build(build_id):
    for r in _read():
        if r.get("type") == "build" and r["build_id"] == build_id:
            return r
    return None


def recent_builds(n=10):
    builds = [r for r in _read() if r.get("type") == "build"]
    done = {r["build_id"] for r in _read() if r.get("type") == "feedback"}
    for b in builds:
        b["has_feedback"] = b["build_id"] in done
    return builds[-n:][::-1]


def training_pairs():
    """(name, label, commander) from all feedback.

    kept  -> 1.0   you saw it in context and kept it
    added -> 1.0   you wanted it enough to add it manually (strongest signal)
    cut   -> 0.0   you saw it in context and rejected it

    Cards the builder never proposed and you never added are unlabelled —
    absence is not rejection, so they're excluded rather than assumed 0.
    """
    pairs = []
    for r in _read():
        if r.get("type") != "feedback":
            continue
        c = r["commander"]
        for name in r.get("kept", []):
            pairs.append((name, 1.0, c))
        for name in r.get("added", []):
            pairs.append((name, 1.0, c))
        for name in r.get("cut", []):
            pairs.append((name, 0.0, c))
    return pairs


def stats():
    pairs = training_pairs()
    builds = [r for r in _read() if r.get("type") == "build"]
    fb = [r for r in _read() if r.get("type") == "feedback"]
    pos = sum(1 for _, l, _ in pairs if l == 1.0)
    return {
        "builds": len(builds),
        "with_feedback": len(fb),
        "labelled_cards": len(pairs),
        "positive": pos,
        "negative": len(pairs) - pos,
    }


if __name__ == "__main__":
    s = stats()
    print(json.dumps(s, indent=2))
    if s["labelled_cards"] < 300:
        print(f"\n{s['labelled_cards']} labels so far. Retraining is worth it "
              f"from roughly 300; more is better.")
    else:
        print("\nEnough to retrain: python train_readout.py")
    print("\nBuilds awaiting your feedback:")
    for b in recent_builds():
        if not b["has_feedback"]:
            print(f"  {b['build_id']}  {b['commander']}  theme={b['theme']}")
