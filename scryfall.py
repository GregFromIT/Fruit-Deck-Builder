"""Scryfall access. Official, documented, stable.

API docs:    https://scryfall.com/docs/api
Search ref:  https://scryfall.com/docs/syntax  (includes the Tagger Tags section)

Tagger tags (otag:/atag:) are community-curated functional labels. They are
how we classify a card's ROLE without depending on EDHREC panel headers, so
cards found by our own queries get a role too.
"""

import time

import requests

from cache import cached

BASE = "https://api.scryfall.com"
RATE_DELAY = 0.1  # Scryfall asks for ~10 req/s max

# REQUIRED. Scryfall returns HTTP 400 without these — requests without a
# real User-Agent and an Accept header are flagged as junk traffic and
# rejected. Do NOT let requests/urllib pick the User-Agent for you.
# https://scryfall.com/docs/faqs/i-m-having-trouble-accessing-the-scryfall-api-or-i-m-blocked-17
# https://scryfall.com/blog/user-agent-and-accept-header-now-required-on-the-api-225
HEADERS = {
    "User-Agent": "MTGCommanderDeckbuilder/0.2 (personal hobby project)",
    "Accept": "application/json;q=0.9,*/*;q=0.8",
}


def named(name):
    """Fuzzy card lookup. https://scryfall.com/docs/api/cards/named"""
    def fetch():
        r = requests.get(f"{BASE}/cards/named", params={"fuzzy": name},
                         headers=HEADERS, timeout=20)
        r.raise_for_status()
        return r.json()
    return cached(f"named:{name}", fetch)


def search(query):
    """Paginated search. [] on 404 (no matches)."""
    def fetch():
        cards, url, params = [], f"{BASE}/cards/search", {"q": query}
        while url:
            r = requests.get(url, params=params, headers=HEADERS, timeout=20)
            if r.status_code == 404:
                break
            r.raise_for_status()
            data = r.json()
            cards.extend(data["data"])
            url, params = data.get("next_page"), None
            time.sleep(RATE_DELAY)
        return cards
    return cached(f"search:{query}", fetch)


def search_names(query):
    return {c["name"] for c in search(query)}


def collection(names):
    """Batch card lookup, 75 per request.
    https://scryfall.com/docs/api/cards/collection"""
    names = list(names)
    key = f"collection:{hash(tuple(sorted(names)))}"

    def fetch():
        out = {}
        for i in range(0, len(names), 75):
            r = requests.post(
                f"{BASE}/cards/collection",
                json={"identifiers": [{"name": n} for n in names[i:i + 75]]},
                headers=HEADERS, timeout=20,
            )
            r.raise_for_status()
            for c in r.json().get("data", []):
                usd = c.get("prices", {}).get("usd")
                out[c["name"]] = {
                    "name": c["name"],
                    "cmc": c.get("cmc"),
                    "type_line": c.get("type_line"),
                    "mana_cost": c.get("mana_cost"),
                    "color_identity": c.get("color_identity", []),
                    "price_usd": float(usd) if usd else None,
                }
            time.sleep(RATE_DELAY)
        return out
    return cached(key, fetch)


# --- role classification via Tagger -----------------------------------
#
# WARNING: these otag slugs are BEST-GUESS. Tagger's vocabulary is
# community-curated and there is no published canonical list. Verify each
# on scryfall.com before trusting it — a wrong slug fails SILENTLY as an
# empty bucket, which looks like "no ramp exists" rather than an error.
# verify_role_tags() below exists to catch exactly that.

# VERIFIED tags are documented working (EDHREC's Scryfall guide recommends
# otag:ramp / otag:removal / otag:card-advantage; otag:counterspell and
# otag:sacrifice-outlet appear in Scryfall's own tag index).
# UNVERIFIED ones are still guesses — run `python cli.py --verify-tags`,
# which now skips bad tags individually instead of failing the whole role.
# Full tag index: https://scryfall.com/docs/tagger-tags
ROLE_OTAGS = {
    "ramp": ["otag:ramp"],                                    # verified
    "draw": ["otag:card-advantage"],                          # verified
    "removal": ["otag:removal"],                              # verified
    "wincons": ["otag:infinite-combo", "otag:sacrifice-outlet"],
    "protection": ["otag:counterspell"],                      # verified
}


def verify_role_tags(scope="f:commander"):
    """Run each otag and report hit counts. Run this FIRST on a new setup.
    A count of 0 means the slug is wrong, not that no such cards exist."""
    report = {}
    for role, tags in ROLE_OTAGS.items():
        for tag in tags:
            try:
                report[tag] = (role, len(search(f"{scope} {tag}")))
            except requests.HTTPError as e:
                code = e.response.status_code
                if code == 400:
                    # With headers correct, a 400 here means Scryfall rejected
                    # the tag value itself — i.e. this slug does not exist.
                    report[tag] = (role, "unknown tag")
                else:
                    report[tag] = (role, f"HTTP {code}")
    return report


def role_map(color_scope):
    """name -> role. ~15 searches, cached. First tag to claim a card wins."""
    mapping = {}
    for role, tags in ROLE_OTAGS.items():
        for tag in tags:
            try:
                for name in search_names(f"{color_scope} {tag}"):
                    mapping.setdefault(name, role)
            except requests.HTTPError:
                continue  # unknown tag; verify_role_tags() names it
    return mapping
