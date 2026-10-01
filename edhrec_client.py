"""EDHREC access via mightstone, with sync wrappers and caching.

EDHREC has NO official API. mightstone reverse-engineered the static JSON at
json.edhrec.com and the dynamic API at edhrec.com/api/. Everything here can
break without notice if EDHREC changes their site.

Verified against the mightstone 0.4.0 wheel source:
  EdhRecStatic.commander(name, sub)  -> /pages/commanders/<slug>[/<sub>].json
  EdhRecCommander.themes / .budget   -> available sub-slugs (value, suffix, count)
  EdhRecCommander.cards[].items[]    -> EdhRecCardItem
  EdhRecCardItem.name / .synergy / .num_decks / .potential_decks
  EdhRecCommander.mana_curve         -> {cmc: count}
  EdhRecApi.recs(commanders, cards)  -> EdhRecRecs(inRecs=[...], outRecs=[...])

Docs: https://mightstone.readthedocs.io/en/latest/reference/api.html
"""

import asyncio
import inspect

from mightstone.services.edhrec import EdhRecApi, EdhRecStatic

from cache import cached


def _sync(value):
    """mightstone methods may be coroutines or already-wrapped sync callables
    depending on version. Handle both rather than assuming."""
    if inspect.isawaitable(value):
        return asyncio.run(_await(value))
    return value


async def _await(coro):
    return await coro


def _commander_page(name, sub=None):
    return _sync(EdhRecStatic().commander(name, sub=sub))


def list_themes(name):
    """[(value, suffix, deck_count)] — the themes EDHREC actually has pages
    for. You cannot request a sub-slug EDHREC has not built."""
    def fetch():
        page = _commander_page(name)
        return [[t.value, t.suffix, t.count] for t in page.themes]
    return [tuple(t) for t in cached(f"themes:{name}", fetch)]


def list_budget_subs(name):
    """EDHREC's budget/expensive subsets. NOTE: these are deck-level
    percentiles (top 10% cheapest / most expensive decks for this commander),
    NOT a per-card price cap. Mutually exclusive with themes."""
    def fetch():
        page = _commander_page(name)
        return [[b.value, b.suffix, b.count] for b in page.budget]
    return [tuple(b) for b in cached(f"budget:{name}", fetch)]


def commander_pool(name, sub=None):
    """Recommended cards with synergy and inclusion rate."""
    def fetch():
        page = _commander_page(name, sub=sub)
        out = []
        for cardlist in page.cards:
            for item in cardlist.items:
                denom = item.potential_decks or 0
                out.append({
                    "name": item.name,
                    "edhrec_tag": cardlist.tag,
                    "synergy": item.synergy or 0.0,
                    "inclusion_pct": (item.num_decks / denom) if denom else 0.0,
                })
        return out
    return cached(f"pool:{name}:{sub}", fetch)


def target_curve(name, sub=None):
    """EDHREC's observed mana curve for this commander/theme, as
    {cmc: proportion}. Used to constrain the build instead of guessing."""
    def fetch():
        page = _commander_page(name, sub=sub)
        curve = {int(k): v for k, v in (page.mana_curve or {}).items()}
        total = sum(curve.values())
        return {str(k): (v / total if total else 0.0) for k, v in curve.items()}
    raw = cached(f"curve:{name}:{sub}", fetch)
    return {int(k): v for k, v in raw.items()}


def refine(commander_name, current_cards):
    """Ask EDHREC what to ADD and what to CUT given a partial list.

    This is the dynamic endpoint — it sees your actual card choices, unlike
    the static pages which only know the commander. Returns (add, cut) name
    lists. Not cached: the whole point is that it varies with the list.
    """
    recs = _sync(EdhRecApi().recs([commander_name], list(current_cards)))
    add = [c.name for c in (recs.inRecs or []) if getattr(c, "name", None)]
    cut = [c.name for c in (recs.outRecs or []) if getattr(c, "name", None)]
    return add, cut
