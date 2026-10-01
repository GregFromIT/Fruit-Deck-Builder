"""Command line entry point.

  python cli.py                      build a deck (interactive)
  python cli.py --verify-tags        check otag: slugs resolve (DO THIS FIRST)
  python cli.py --feedback <id>      record what you kept from a build
  python cli.py --stats              training data progress
  python cli.py --spec f.json        build from a saved spec
"""

import sys

import feedback
import scryfall
from deckbuilder import DeckSpec, build, build_pool, to_decklist
from edhrec_client import list_budget_subs, list_themes
from taste import load_taste


def verify_tags():
    print("Scryfall Tagger slugs (0 hits = WRONG SLUG, not zero cards):\n")
    bad = 0
    for tag, (role, count) in scryfall.verify_role_tags().items():
        broken = count == 0 or isinstance(count, str)
        bad += broken
        print(f" {'!!' if broken else '  '} {tag:<30} {role:<12} {count}")
    if bad:
        print(f"\n{bad} broken slug(s). Search them on scryfall.com and fix "
              f"ROLE_OTAGS in scryfall.py. Until then the oracle-text "
              f"fallback covers you, but worse.")
    else:
        print("\nAll slugs resolve.")


def show_stats():
    s = feedback.stats()
    print(f"builds: {s['builds']}   with feedback: {s['with_feedback']}")
    print(f"labelled cards: {s['labelled_cards']} "
          f"({s['positive']}+ / {s['negative']}-)")
    print("\nretrain worthwhile from ~300 labels"
          if s["labelled_cards"] < 300 else "\nenough to retrain: python train_readout.py")
    pending = [b for b in feedback.recent_builds() if not b["has_feedback"]]
    if pending:
        print("\nawaiting feedback:")
        for b in pending:
            print(f"  {b['build_id']}  {b['commander']}  theme={b['theme']}")


def record_feedback(build_id):
    b = feedback.find_build(build_id)
    if not b:
        return print(f"No build {build_id}")
    print(f"{b['commander']} — {len(b['proposed'])} cards proposed.")
    print("Paste your FINAL list (one card per line), blank line to finish:\n")
    final = []
    while True:
        try:
            line = input().strip()
        except EOFError:
            break
        if not line:
            break
        final.append(line.split(" (")[0].lstrip("0123456789x ").strip())
    feedback.log_feedback(build_id, final)
    kept = len(set(b["proposed"]) & set(final))
    print(f"\nlogged: {kept} kept, {len(b['proposed']) - kept} cut, "
          f"{len(set(final) - set(b['proposed']))} added")


def interactive():
    name = input("Commander: ").strip()

    try:
        themes = list_themes(name)
    except Exception as e:
        themes = []
        print(f"(EDHREC theme list unavailable: {e})")

    if themes:
        print(f"\nEDHREC themes for {name}:")
        for value, suffix, count in themes:
            print(f"  {suffix:<28} {value}  ({count} decks)")
    try:
        for value, suffix, count in list_budget_subs(name):
            print(f"  [budget] {suffix:<19} {value}  ({count} decks)")
    except Exception:
        pass

    theme = input("\nTheme slug (blank = none): ").strip() or None
    price = input("Max $ per card (blank = none): ").strip()
    extra = input("Extra Scryfall queries, comma separated: ").strip()

    spec = DeckSpec(
        commander=name, theme=theme,
        max_price=float(price) if price else None,
        otag_queries=[q.strip() for q in extra.split(",") if q.strip()],
    )

    taste_fn = load_taste()
    taste = None
    if taste_fn:
        spec.taste_weight = 0.3
        _, pool, _ = build_pool(spec)
        taste = taste_fn(pool)
        print("\n[fly readout loaded — taste_weight=0.3]")
    else:
        print("\n[no trained readout — statistical scoring only]")

    print("Building...\n")
    deck = build(spec, taste)

    for w in deck["warnings"]:
        print(f"  ! {w}")
    print(f"\n{'=' * 52}")
    print(f"{deck['commander']}   theme={deck['theme']}   "
          f"{deck['total_cards']} cards")
    print(f"roles: {deck['roles']}")
    print(f"curve: {dict(sorted(deck['curve'].items()))}")
    for line in deck["refine_log"]:
        print(f"refine: {line}")
    print(f"{'=' * 52}\n")
    print(to_decklist(deck))

    out = f"{name.split(',')[0].replace(' ', '-').lower()}.txt"
    with open(out, "w") as f:
        f.write(to_decklist(deck))
    print(f"\nWritten to {out}")
    print(f"\nAfter you've edited it, teach the builder:")
    print(f"  python cli.py --feedback {deck.get('build_id')}")


if __name__ == "__main__":
    args = sys.argv[1:]
    if "--verify-tags" in args:
        verify_tags()
    elif "--stats" in args:
        show_stats()
    elif "--feedback" in args:
        record_feedback(args[args.index("--feedback") + 1])
    elif "--spec" in args:
        print(to_decklist(build(DeckSpec.from_json(args[args.index("--spec") + 1]))))
    else:
        interactive()
