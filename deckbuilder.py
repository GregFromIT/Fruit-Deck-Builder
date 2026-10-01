"""Theme-directed Commander deckbuilder.

Pipeline:
  1. POOL    EDHREC (theme-scoped) + your own Scryfall queries
  2. ENRICH  cmc / type / price / role, from Scryfall
  3. SCORE   synergy + novelty, optionally blended with fly taste score
  4. FILL    role quotas, then curve-constrained, then best-remaining
  5. REFINE  EDHREC dynamic recs() sees the actual list and suggests swaps
  6. LANDS   basics split by the deck's real colour pips
"""

import json
from collections import Counter
from dataclasses import asdict, dataclass, field

import edhrec_client as edhrec
import fallbacks
import scryfall


@dataclass
class DeckSpec:
    commander: str
    theme: str = None                 # EDHREC sub-slug from list_themes()
    budget_sub: str = None            # EDHREC budget subset (mutually exclusive w/ theme)
    otag_queries: list = field(default_factory=list)
    mechanic_queries: list = field(default_factory=list)
    max_price: float = None           # hard per-card USD cap
    synergy_weight: float = 0.6
    novelty_weight: float = 0.4
    min_synergy: float = 0.0
    taste_weight: float = 0.0         # 0 = fly readout off
    land_count: int = 37
    curve_tolerance: float = 1.5      # allow 1.5x EDHREC's share at each cmc
    refine_rounds: int = 1            # EDHREC dynamic recs() passes
    role_quotas: dict = field(default_factory=lambda: {
        "ramp": 10, "draw": 10, "removal": 10, "wincons": 8, "protection": 3,
    })

    def to_json(self, path):
        with open(path, "w") as f:
            json.dump(asdict(self), f, indent=2)

    @classmethod
    def from_json(cls, path):
        with open(path) as f:
            return cls(**json.load(f))


def score_card(card, spec, taste=None):
    """High synergy + low inclusion = good but non-obvious.
    min_synergy is a quality floor so rarity alone can't win."""
    synergy = card.get("synergy") or 0.0
    if synergy < spec.min_synergy:
        base = 0.0
    else:
        novelty = 1.0 - (card.get("inclusion_pct") or 0.0)
        base = spec.synergy_weight * synergy + spec.novelty_weight * novelty

    if spec.taste_weight and taste is not None:
        t = taste.get(card["name"], 0.0)
        return (1 - spec.taste_weight) * base + spec.taste_weight * t
    return base


def build_pool(spec, warnings=None):
    """Returns (commander, pool, warnings). Never raises on data-source
    failure — degrades and records why. See fallbacks.py."""
    warnings = warnings if warnings is not None else []

    try:
        commander = scryfall.named(spec.commander)
    except Exception as e:
        raise ValueError(
            f"Could not find commander '{spec.commander}' on Scryfall: {e}"
        ) from e

    colors = "".join(commander.get("color_identity", [])) or "C"
    scope = f"f:commander id<={colors} -t:land"

    pool = {}
    for c in fallbacks.pool_with_fallback(spec, scope, warnings):
        pool.setdefault(c["name"], dict(c))

    if not pool:
        for c in fallbacks.scryfall_only_pool(commander, scope, warnings):
            pool.setdefault(c["name"], dict(c))

    # Cards EDHREC would never suggest — makes an off-meta theme reachable.
    for q in spec.otag_queries + spec.mechanic_queries:
        try:
            for card in scryfall.search(f"{scope} {q}"):
                pool.setdefault(card["name"], {
                    "name": card["name"], "synergy": 0.0,
                    "inclusion_pct": 0.0, "edhrec_tag": None,
                })
        except Exception as e:
            warnings.append(f"query '{q}' failed ({e}); skipped")

    pool.pop(commander["name"], None)

    try:
        details = scryfall.collection(list(pool))
    except Exception as e:
        warnings.append(f"Scryfall card details unavailable ({e})")
        details = {}

    roles = fallbacks.role_map_with_fallback(scope, warnings)

    out, dropped_price = [], 0
    for name, card in pool.items():
        d = details.get(name)
        if not d:
            # No details: keep it, but it can't be price-filtered or curved.
            card.setdefault("cmc", None)
            card.setdefault("type_line", "")
            card.setdefault("mana_cost", "")
            card.setdefault("price_usd", None)
        else:
            if spec.max_price is not None:
                if d["price_usd"] is None or d["price_usd"] > spec.max_price:
                    dropped_price += 1
                    continue
            card.update(d)
        card["role"] = roles.get(name, "other")
        out.append(card)

    if dropped_price:
        warnings.append(f"{dropped_price} cards dropped by max_price=${spec.max_price}")

    out = fallbacks.pad_pool(out, commander, scope, 99 - spec.land_count, warnings)
    return commander, out, warnings


def _curve_caps(spec, slots):
    """Per-cmc ceilings derived from EDHREC's observed curve for this
    commander/theme. Without this nothing stops a top-heavy pile."""
    try:
        curve = edhrec.target_curve(spec.commander, sub=spec.theme)
    except Exception:
        curve = None
    if not curve:
        return None
    return {cmc: max(1, int(share * slots * spec.curve_tolerance))
            for cmc, share in curve.items()}


def assemble(commander, pool, spec, taste=None, deck_size=99):
    slots = deck_size - spec.land_count
    caps = _curve_caps(spec, slots)
    used = Counter()

    def fits(card):
        if caps is None:
            return True
        cmc = int(card.get("cmc") or 0)
        cap = caps.get(cmc, caps.get(max(caps), slots))
        return used[cmc] < cap

    def take(card):
        used[int(card.get("cmc") or 0)] += 1

    by_role = {}
    for c in pool:
        by_role.setdefault(c["role"], []).append(c)
    for role in by_role:
        by_role[role].sort(key=lambda c: score_card(c, spec, taste), reverse=True)

    chosen, names = [], set()
    for role, quota in spec.role_quotas.items():
        filled = 0
        for c in by_role.get(role, []):
            if filled >= quota:
                break
            if fits(c):
                chosen.append(c); names.add(c["name"]); take(c); filled += 1

    leftover = sorted((c for c in pool if c["name"] not in names),
                      key=lambda c: score_card(c, spec, taste), reverse=True)
    for c in leftover:
        if len(chosen) >= slots:
            break
        if fits(c):
            chosen.append(c); names.add(c["name"]); take(c)

    # Curve caps can leave the deck short; backfill ignoring them.
    if len(chosen) < slots:
        for c in leftover:
            if len(chosen) >= slots:
                break
            if c["name"] not in names:
                chosen.append(c); names.add(c["name"])

    return chosen


def refine(commander, chosen, pool, spec, taste=None):
    """Let EDHREC's dynamic endpoint see the actual list and suggest swaps.

    Only applies a swap if the incoming card is in our validated pool —
    never trust a name we haven't checked against Scryfall.
    """
    by_name = {c["name"]: c for c in pool}
    log = []

    for _ in range(spec.refine_rounds):
        names = [c["name"] for c in chosen]
        try:
            add, cut = edhrec.refine(spec.commander, names)
        except Exception as e:
            log.append(f"refine skipped: {e}")
            break

        cut_set = {n for n in cut if n in set(names)}
        candidates = [by_name[n] for n in add if n in by_name
                      and n not in set(names)]
        if not cut_set or not candidates:
            break

        candidates.sort(key=lambda c: score_card(c, spec, taste), reverse=True)
        swaps = min(len(cut_set), len(candidates), 10)  # cap churn per round
        dropped = list(cut_set)[:swaps]
        chosen = [c for c in chosen if c["name"] not in set(dropped)]
        chosen.extend(candidates[:swaps])
        log.append(f"swapped {swaps}: -{dropped[:3]}... +"
                   f"{[c['name'] for c in candidates[:3]]}...")

    return chosen, log


def land_split(commander, chosen, land_count):
    """Basics weighted by actual coloured pips in the deck. Crude but beats
    a flat split — it at least reflects what the deck is casting."""
    pips = Counter()
    for c in chosen:
        for sym in (c.get("mana_cost") or ""):
            if sym in "WUBRG":
                pips[sym] += 1
    identity = commander.get("color_identity", [])
    for c in identity:
        pips.setdefault(c, 0)
    if not pips:
        return {"Wastes": land_count}

    total = sum(pips.values()) or 1
    basics = {"W": "Plains", "U": "Island", "B": "Swamp",
              "R": "Mountain", "G": "Forest"}
    split, assigned = {}, 0
    for color in identity:
        n = round(land_count * (pips[color] / total))
        split[basics[color]] = n
        assigned += n
    if identity:  # fix rounding drift
        first = basics[identity[0]]
        split[first] += land_count - assigned
    return split


def build(spec, taste=None, log=True):
    """Always returns a deck dict. `warnings` lists anything that degraded."""
    commander, pool, warnings = build_pool(spec)
    chosen = assemble(commander, pool, spec, taste)
    chosen, refine_log = refine(commander, chosen, pool, spec, taste)
    lands = land_split(commander, chosen, spec.land_count)

    total = len(chosen) + sum(lands.values()) + 1
    if total != 100:
        warnings.append(f"Deck is {total} cards, not 100 — pool was too small")

    deck = {
        "commander": commander["name"],
        "theme": spec.theme,
        "cards": [{"name": c["name"], "role": c["role"],
                   "cmc": c.get("cmc"), "price": c.get("price_usd"),
                   "score": round(score_card(c, spec, taste), 3)}
                  for c in chosen],
        "lands": lands,
        "curve": dict(Counter(int(c.get("cmc") or 0) for c in chosen)),
        "roles": dict(Counter(c["role"] for c in chosen)),
        "refine_log": refine_log,
        "warnings": warnings,
        "total_cards": total,
    }

    if log:
        try:
            import feedback
            deck["build_id"] = feedback.log_build(
                spec, deck, [c["name"] for c in pool])
        except Exception as e:
            deck["warnings"].append(f"feedback log failed: {e}")

    return deck


def to_decklist(deck):
    """Moxfield/Archidekt-importable plain text."""
    lines = [f"1 {deck['commander']}", ""]
    lines += [f"1 {c['name']}" for c in deck["cards"]]
    lines += [f"{n} {name}" for name, n in deck["lands"].items() if n > 0]
    return "\n".join(lines)
