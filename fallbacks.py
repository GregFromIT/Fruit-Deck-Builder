"""Graceful degradation. The builder must always produce a legal 100-card
deck, even when EDHREC is down, a theme slug is wrong, or every otag: slug
is broken. A crash produces no deck and no feedback; a degraded deck
produces both.

Every fallback records WHY it fired so the output says what went wrong
instead of silently handing you a worse deck.
"""

import scryfall

# Used only when Tagger otag: slugs return nothing. Cruder than Tagger —
# oracle text matching misses a lot — but it keeps role quotas functioning.
ORACLE_ROLE_FALLBACK = {
    "ramp": ['o:"add {c}"', 'o:"add one mana"', 'o:"search your library for a basic land"'],
    "draw": ['o:"draw a card"', 'o:"draw two cards"', 'o:"draws a card"'],
    "removal": ['o:"destroy target"', 'o:"exile target"', 'o:"destroy all"'],
    "wincons": ['o:"wins the game"', 'o:"loses the game"', 'o:"double"'],
    "protection": ['o:"counter target spell"', 'o:hexproof', 'o:indestructible'],
}


def role_map_with_fallback(scope, warnings):
    """Tagger first. If it yields too little, add oracle-text matching."""
    mapping = {}
    try:
        mapping = scryfall.role_map(scope)
    except Exception as e:
        warnings.append(f"Tagger role map failed ({e}); using oracle text only")

    if len(mapping) < 50:
        warnings.append(
            f"Tagger returned only {len(mapping)} classified cards — otag: slugs "
            f"are probably wrong. Run `python cli.py --verify-tags`. "
            f"Falling back to oracle-text matching."
        )
        for role, queries in ORACLE_ROLE_FALLBACK.items():
            for q in queries:
                try:
                    for name in scryfall.search_names(f"{scope} {q}"):
                        mapping.setdefault(name, role)
                except Exception:
                    continue
    return mapping


def pool_with_fallback(spec, scope, warnings):
    """EDHREC first. If it fails or the theme is bad, degrade step by step
    rather than returning nothing."""
    import edhrec_client as edhrec

    sub = spec.theme or spec.budget_sub

    if sub:
        try:
            pool = edhrec.commander_pool(spec.commander, sub=sub)
            if pool:
                return pool
            warnings.append(f"EDHREC theme '{sub}' returned no cards; ignoring it")
        except Exception as e:
            warnings.append(f"EDHREC theme '{sub}' failed ({e}); ignoring it")

    try:
        pool = edhrec.commander_pool(spec.commander, sub=None)
        if pool:
            return pool
        warnings.append("EDHREC returned no cards for this commander")
    except Exception as e:
        warnings.append(f"EDHREC unavailable ({e}); building from Scryfall alone")

    return []


def scryfall_only_pool(commander, scope, warnings):
    """Last resort: no EDHREC at all. Pull a broad staple-ish pool so the
    build still completes. Quality will be mediocre and says so."""
    warnings.append(
        "No EDHREC data — deck built from Scryfall alone. Expect generic "
        "goodstuff, not synergy. Check your commander name spelling."
    )
    pool = {}
    for q in ["otag:ramp", 'o:"draw a card"', 'o:"destroy target"',
              "t:creature", "t:artifact"]:
        try:
            for c in scryfall.search(f"{scope} {q}")[:200]:
                pool.setdefault(c["name"], {
                    "name": c["name"], "synergy": 0.0,
                    "inclusion_pct": 0.0, "edhrec_tag": None,
                })
        except Exception:
            continue
    return list(pool.values())


def pad_pool(pool, commander, scope, needed, warnings):
    """If the pool is smaller than the deck needs (aggressive price cap,
    narrow colours), widen it rather than returning a short deck."""
    if len(pool) >= needed:
        return pool
    warnings.append(
        f"Only {len(pool)} cards passed filters, need {needed}. "
        f"Widening search — relax max_price if the deck looks thin."
    )
    have = {c["name"] for c in pool}
    try:
        for c in scryfall.search(f"{scope} -t:land"):
            if c["name"] not in have:
                pool.append({"name": c["name"], "synergy": 0.0,
                             "inclusion_pct": 0.0, "edhrec_tag": None})
                have.add(c["name"])
            if len(pool) >= needed * 2:
                break
    except Exception as e:
        warnings.append(f"Could not widen pool ({e})")
    return pool
