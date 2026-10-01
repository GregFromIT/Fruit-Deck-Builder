"""Collect decklists for training the fly readout.

READ THIS BEFORE USING OTHER PEOPLE'S DECKS
-------------------------------------------
The fly readout's ONLY justification is learning YOUR taste. Train it on
strangers' decks and it learns crowd taste — which EDHREC's inclusion_pct
already gives you, computed over vastly more decks, for free. Public decks
are therefore NOT a substitute for your own lists.

They are useful for exactly one thing the pipeline currently lacks:
CO-OCCURRENCE. EDHREC gives you per-card inclusion rates but throws away
which cards appear TOGETHER. Public decks preserve that, which is the
signal you'd need to catch "payoffs with no enablers". That's a different
model to the taste readout — don't mix the two training sets.

Sources
-------
- Your own decks: Moxfield/Archidekt -> More -> Export -> Plain Text.
  Drop into decks/mine/<commander-name>.txt  <- PRIMARY TRAINING DATA
- Moxfield public API: https://api2.moxfield.com/v3/decks/all/<deckId>
- Archidekt public API: https://archidekt.com/api/decks/<deckId>/
  Both are unofficial-but-public; be polite, rate limit, cache.
"""

import json
import os
import re
import time

import requests

MINE_DIR = os.path.join("decks", "mine")
PUBLIC_DIR = os.path.join("decks", "public")
HEADERS = {"User-Agent": "personal-deckbuilder/0.1 (hobby project)"}
DELAY = 1.0  # be a good citizen; these are free community services


def read_decklist(path):
    names = []
    for line in open(path, encoding="utf-8"):
        line = line.strip()
        if not line or line.startswith(("#", "//", "SIDEBOARD")):
            continue
        names.append(re.sub(r"^\d+x?\s+", "", line).split(" (")[0].strip())
    return names


def load_my_decks():
    """{commander_name: [card names]} from decks/mine/*.txt

    Filename is the commander: emry-lurker-of-the-loch.txt
    """
    decks = {}
    if not os.path.isdir(MINE_DIR):
        return decks
    for fn in os.listdir(MINE_DIR):
        if fn.endswith(".txt"):
            commander = fn[:-4].replace("-", " ")
            decks[commander] = read_decklist(os.path.join(MINE_DIR, fn))
    return decks


def _deck_id(url_or_id):
    m = re.search(r"/decks/(?:all/)?([A-Za-z0-9_\-]+)", url_or_id)
    return m.group(1) if m else url_or_id


def fetch_moxfield(url_or_id):
    """Returns {'commander': str, 'cards': [names]} or None."""
    did = _deck_id(url_or_id)
    r = requests.get(f"https://api2.moxfield.com/v3/decks/all/{did}",
                     headers=HEADERS, timeout=20)
    if r.status_code != 200:
        return None
    data = r.json()
    boards = data.get("boards", {})

    def names(board):
        return [c["card"]["name"]
                for c in boards.get(board, {}).get("cards", {}).values()]

    cmd = names("commanders")
    return {"commander": cmd[0] if cmd else None,
            "cards": names("mainboard"),
            "source": f"moxfield:{did}"}


def fetch_archidekt(url_or_id):
    did = _deck_id(url_or_id)
    r = requests.get(f"https://archidekt.com/api/decks/{did}/",
                     headers=HEADERS, timeout=20)
    if r.status_code != 200:
        return None
    data = r.json()
    commander, cards = None, []
    for entry in data.get("cards", []):
        name = entry.get("card", {}).get("oracleCard", {}).get("name")
        if not name:
            continue
        cats = entry.get("categories") or []
        if any(c.lower() == "commander" for c in cats):
            commander = name
        else:
            cards.append(name)
    return {"commander": commander, "cards": cards, "source": f"archidekt:{did}"}


def fetch_public(urls, out_path=os.path.join(PUBLIC_DIR, "decks.jsonl")):
    """Fetch a list of deck URLs into JSONL. For CO-OCCURRENCE work only —
    see the warning at the top of this file."""
    os.makedirs(PUBLIC_DIR, exist_ok=True)
    got = 0
    with open(out_path, "a", encoding="utf-8") as f:
        for url in urls:
            fetcher = fetch_archidekt if "archidekt" in url else fetch_moxfield
            try:
                deck = fetcher(url)
            except requests.RequestException as e:
                print(f"  {url}: {e}")
                deck = None
            if deck and deck["cards"]:
                f.write(json.dumps(deck) + "\n")
                got += 1
                print(f"  ok  {deck['commander']} ({len(deck['cards'])} cards)")
            else:
                print(f"  --  {url}: no data (private? wrong id?)")
            time.sleep(DELAY)
    return got


if __name__ == "__main__":
    mine = load_my_decks()
    print(f"Your decks in {MINE_DIR}: {len(mine)}")
    for commander, cards in mine.items():
        print(f"  {commander}: {len(cards)} cards")
    if not mine:
        print(f"\nNothing found. Export your decks as plain text into {MINE_DIR}/")
        print("Name each file after its commander, e.g. emry-lurker-of-the-loch.txt")
