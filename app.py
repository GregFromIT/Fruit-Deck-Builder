"""Flask frontend with feedback capture.

pip install -r requirements.txt
python app.py   ->  http://127.0.0.1:5000
"""

from flask import Flask, redirect, render_template, request, url_for

import feedback
from deckbuilder import DeckSpec, build, build_pool, to_decklist
from edhrec_client import list_budget_subs, list_themes
from taste import load_taste

app = Flask(__name__)
TASTE_FN = load_taste()


@app.route("/", methods=["GET", "POST"])
def index():
    ctx = {"deck": None, "error": None, "themes": [], "budget": [],
           "decklist": None, "taste_ready": TASTE_FN is not None,
           "stats": feedback.stats(), "pending": [
               b for b in feedback.recent_builds() if not b["has_feedback"]]}

    if request.method == "POST":
        name = request.form.get("commander", "").strip()
        action = request.form.get("action", "themes")
        try:
            try:
                ctx["themes"] = list_themes(name)
                ctx["budget"] = list_budget_subs(name)
            except Exception as e:
                ctx["error"] = f"EDHREC theme list unavailable: {e}"

            if action == "build":
                price = request.form.get("max_price", "").strip()
                extra = request.form.get("queries", "").strip()
                spec = DeckSpec(
                    commander=name,
                    theme=request.form.get("theme") or None,
                    max_price=float(price) if price else None,
                    otag_queries=[q.strip() for q in extra.split(",") if q.strip()],
                    taste_weight=float(request.form.get("taste_weight") or 0),
                )
                taste = None
                if TASTE_FN and spec.taste_weight:
                    _, pool, _ = build_pool(spec)
                    taste = TASTE_FN(pool)
                ctx["deck"] = build(spec, taste)
                ctx["decklist"] = to_decklist(ctx["deck"])
        except Exception as e:
            ctx["error"] = f"{type(e).__name__}: {e}"

    return render_template("index.html", **ctx)


@app.route("/feedback", methods=["POST"])
def submit_feedback():
    """Cards left checked are kept; unchecked are cut. Anything typed into
    the 'added' box counts as a manual add (the strongest positive signal)."""
    build_id = request.form["build_id"]
    kept = request.form.getlist("keep")
    added = [n.strip() for n in
             request.form.get("added", "").splitlines() if n.strip()]
    note = request.form.get("note", "").strip() or None
    try:
        feedback.log_feedback(build_id, kept + added, note=note)
    except Exception:
        pass
    return redirect(url_for("index"))


if __name__ == "__main__":
    app.run(debug=True)
