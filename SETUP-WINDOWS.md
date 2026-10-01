# Setup — Windows (PowerShell)

Run every command from inside the `proj` folder. Start to first deck is
about 10 minutes, most of it waiting on the first build's Scryfall calls.

---

## 1. Unpack

Right-click `mtg-deckbuilder.zip` → Extract All. Then open PowerShell in
the extracted folder:

```powershell
cd path\to\proj
```

Check you're in the right place — this should list `cli.py`, `app.py`,
`requirements.txt`:

```powershell
dir
```

---

## 2. Check your Python version

```powershell
python --version
```

Needs 3.10–3.12. On 3.13+ scipy may try to compile from source instead of
pulling a prebuilt wheel, which fails without a C toolchain. If you're on
3.13, install 3.12 from python.org and use that.

If `python` isn't recognised at all, install from python.org and tick
"Add python.exe to PATH" during install.

---

## 3. Create and activate a venv

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

Your prompt should now start with `(.venv)`.

**If you get "running scripts is disabled on this system":** that's
PowerShell's execution policy blocking the activation script. Either:

```powershell
Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
```
then activate again — or use `cmd` instead, where activation is
`.\.venv\Scripts\activate.bat` and no policy change is needed.

---

## 4. Install dependencies

```powershell
pip install -r requirements.txt
```

**Expected problem: `mightstone` may fail** with a package-metadata or
build error. It failed in my environment. It's an older package with
pinned pydantic versions.

If it fails, try pinning explicitly:
```powershell
pip install "mightstone==0.4.0"
```

If it still fails, install the rest and carry on:
```powershell
pip install requests flask numpy scipy safetensors
```
The builder detects the missing library and falls back to Scryfall-only
mode, with a warning on every deck. **You lose EDHREC synergy data, which
is most of the value** — so this is worth coming back to, not living with.
Tell me the exact error and I'll work around it.

---

## 5. Verify the Tagger slugs

```powershell
python cli.py --verify-tags
```

Every line showing `0` is a **wrong slug**, not "no such cards exist". The
`otag:` values in `scryfall.py` are my educated guesses — Scryfall Tagger's
vocabulary is community-curated with no published canonical list.

To fix one: search the tag on scryfall.com (e.g. type `otag:ramp` into
their search box). If it returns nothing, find the right tag name and edit
`ROLE_OTAGS` in `scryfall.py`.

Not fatal if you skip it — the builder falls back to oracle-text matching
and says so — but role classification gets noticeably cruder.

This takes a minute or two and caches.

---

## 6. Build your first deck

```powershell
python cli.py
```

It will ask, in order:

1. **Commander** — full name, e.g. `Shorikai, Genesis Engine`
2. It prints EDHREC's available themes with deck counts
3. **Theme slug** — copy one from that list, or press Enter for none
4. **Max $ per card** — Enter to skip
5. **Extra Scryfall queries** — Enter to skip on your first run

**The first build is slow** (a minute or two) because it runs the role-map
searches. Results cache to `.cache\` for 7 days, so later builds are fast.

Output: the decklist printed to screen, written to a `.txt` file, plus a
`build_id`. Note that id down.

---

## 7. Or use the web UI

```powershell
python app.py
```

Open http://127.0.0.1:5000 in your browser. Same builder with a theme
dropdown, and tick-box feedback built in — easier than the CLI for step 8.

Ctrl+C in PowerShell to stop it.

---

## 8. Teach it (this is the part that matters)

Edit the deck however you want — in Moxfield, in the text file, wherever.
Then record what you actually did:

```powershell
python cli.py --feedback <build_id>
```

Paste your final list, one card per line, then a blank line to finish.
It diffs against what was proposed and logs kept / cut / added.

Or in the web UI: untick cards you'd cut, type replacements in the box,
click Save feedback.

**Why bother:** cards you cut are the training signal. A card you rejected
after seeing it in context is worth far more than an exported decklist,
which only shows survivors and never what was considered.

---

## 9. Check progress

```powershell
python cli.py --stats
```

Shows labelled card count. **Retraining is worth it from ~300 labels**,
roughly 3–4 builds with feedback.

Do nothing with the fly connectome until you hit that. Training on less
just fits noise.

---

## 10. Later — the fly stage

Only once step 9 shows 300+ labels.

Download MaleCNS v1.0 safetensors into the `proj` folder as
`malecns.safetensors`: https://huggingface.co/QuixiAI/MaleCNS

That's a **third-party repackaging**, not official Janelia. Verify the
tensor shapes against neuPrint before trusting it:
https://male-cns.janelia.org/download/

```powershell
python train_readout.py
```

It prints a holdout correlation per alpha value. **Send me that number.**
It decides whether the fly stage earns its place:

- `< 0.15` — noise. Expected early. Build more decks, give more feedback.
- `0.15–0.35` — weak but real signal.
- `> 0.35` — suspicious this early; check for leakage.

**Do not raise `NEURONS` to fix a bad number.** More reservoir dimensions
against the same small sample makes overfitting worse, not better.

Once `readout_W.npy` exists, `cli.py` and `app.py` pick it up automatically
and the taste weighting activates.

---

## Windows gotchas

- **Always run from the `proj` folder.** The cache and feedback log are
  relative paths; running from elsewhere creates a second empty set.
- **Deck `.txt` files use Unix line endings.** Notepad shows them as one
  long line. Use VS Code or Notepad++, or paste straight into Moxfield.
- **Environment variables** are `$env:CONNECTOME = "malecns.safetensors"`
  in PowerShell, not `export`.
- **Reactivate the venv** every new PowerShell session:
  `.\.venv\Scripts\Activate.ps1`
- **Stale results?** Delete the `.cache` folder.
- **Using WSL instead?** Follow Linux conventions (`source .venv/bin/activate`),
  and add `--break-system-packages` only if you skip the venv on Debian.

---

## Quick reference

```powershell
.\.venv\Scripts\Activate.ps1      # every new session
python cli.py                      # build a deck
python cli.py --verify-tags        # check otag slugs
python cli.py --feedback <id>      # teach it
python cli.py --stats              # training progress
python app.py                      # web UI on :5000
python train_readout.py            # train the fly readout (300+ labels first)
```
