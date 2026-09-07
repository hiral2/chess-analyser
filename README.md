# Chess Analyser

Autonomous hourly pipeline that pulls whatever Chess.com games you've played
since the last run, analyzes them with a local Stockfish engine, turns the
engine telemetry into a coaching + fair-play review, and publishes the
results as a history file, an interactive GitHub Pages dashboard, and an
emailed PDF.

Reports are grouped strictly by calendar day. Each run only checks for games
newer than the last one it saw; if nothing new was played, it's a no-op. If
new games are found, every calendar day touched by one of them gets its
report rebuilt from that day's *complete* game list (old + new together) and
replaces whatever was there before — a day never ends up with more than one
report, no matter how many times new games trigger a refresh of it.

By default the coaching/fair-play write-up is generated locally by a
deterministic rule engine (no API key or network call needed). Pass
`--use-claude` to send the PGNs + telemetry to Claude for a richer,
LLM-generated write-up instead.

```
Chess.com API -> Stockfish (ACPL / top-1 match) -> rule engine (or Claude) -> data/<username>/...
                                                                            -> reports/*.pdf -> email
                                                                            -> index.html (GitHub Pages)
```

## Setup

1. Install dependencies (Python 3.10+):

   ```
   pip install -r requirements.txt
   ```

2. Install Stockfish locally:

   ```
   brew install stockfish   # macOS
   ```

3. Copy `.env.example` to `.env` and fill in:
   - `CHESS_USERNAME` — the Chess.com username to analyze
   - `ANTHROPIC_API_KEY` — only needed if you pass `--use-claude`
   - `SMTP_*` / `EMAIL_*` — optional, only needed to email the PDF

## Pulling a new analysis

Run one cycle locally (checks for games played since the last run; for every
day touched by a new game, re-fetches that day's complete game list, runs
Stockfish at depth 14, rebuilds the report, and replaces that day's file
under `data/<username>/`; also writes a PDF to `reports/`):

```
python main.py --skip-email
```

Running it again immediately is safe and cheap — with no new games it just
prints "No new games found since the last run" and exits without touching
anything. This is the mode the hourly GitHub Actions workflow uses. `--limit`
bounds how many recent games it scans to detect new activity (default from
`GAMES_LIMIT`); bump it if the runner has been idle long enough that more new
games than that may have piled up.

Add `--use-claude` to generate the write-up with Claude instead of the local
rule engine (requires `ANTHROPIC_API_KEY` and API credits). Other flags:
`--skip-pdf`, `--dry-run` (print the report without persisting/emailing
anything).

### Backfilling a date range

`--since YYYY-MM-DD` (optionally with `--until YYYY-MM-DD`, default today)
switches to backfill mode: it pulls every game in that range and generates
one report per calendar day, skipping days that already have a report
(pass `--force` to regenerate one):

```
python main.py --since 2026-08-01 --until 2026-08-31 --skip-email
```

The "Backfill Date Range" GitHub Actions workflow (Actions tab → run
manually) exposes the same `since`/`until`/`force` inputs if you'd rather
trigger it from the repo than from a local checkout.

## Viewing the dashboard locally

`index.html` fetches its data over HTTP (`data/latest.json`, then
`data/<username>/...`), so open it through a local server rather than as a
`file://` URL:

```
python -m http.server 8934
```

Then browse to **http://localhost:8934/index.html**. Re-run `python main.py`
and refresh the page to see a new report appear in the dropdown.

## Running the tests

```
pip install -r requirements-dev.txt
pytest
```

## GitHub Actions (hourly runs + Pages dashboard)

The workflow at `.github/workflows/analysis.yml` runs every hour on the hour
(and on manual dispatch), installs Stockfish, runs
`python main.py --skip-email --skip-pdf`, and deploys the repo root
(including `index.html` and the freshly-updated `data/`) to GitHub Pages. It
never commits anything back to git — `main.py` fetches the currently-published
data from the live Pages URL itself as its starting state
(`REMOTE_DATA_BASE_URL`, set automatically in the workflow), updates it in
memory/on disk for this run only, and that updated copy is what gets deployed.
This sidesteps needing write access to `master` entirely (see "Persistence
model" below). Hours with no new games are cheap no-ops.

`.github/workflows/backfill-day.yml` ("Backfill Date Range") is the same
pipeline triggered manually with a `since`/`until`/`force` date range instead
of the hourly incremental check.

Configure once in the repo's **Settings**:

- **Settings → Pages → Build and deployment → Source**: "GitHub Actions"
- **Settings → Secrets and variables → Actions → Secrets**:
  `CHESS_USERNAME`, and optionally `ANTHROPIC_API_KEY` (only if the workflow
  passes `--use-claude`), `SMTP_HOST`, `SMTP_PORT`, `SMTP_USERNAME`,
  `SMTP_PASSWORD`, `EMAIL_FROM`, `EMAIL_TO`
- **Settings → Secrets and variables → Actions → Variables** (optional):
  `ANTHROPIC_MODEL`, `GAMES_LIMIT`

Email is skipped automatically if `SMTP_HOST`/`EMAIL_TO` aren't set.

## Persistence model

`data/` is **not** tracked in git (see `.gitignore`) and CI never commits it.
The live GitHub Pages deployment is the source of truth. Data is split into
three levels under `data/<username>/`, so no single file grows unbounded and
the dashboard never downloads more than it's currently displaying:

- `data/latest.json` — `{"username": "..."}`, so the static frontend knows
  which folder to load without the username being hardcoded into it.
- `data/<username>/index.json` — a small manifest: the incremental cursor
  (`last_game_end_time`), lifetime totals (`general_summary`), and the list
  of available dates (`analysis_dates`).
- `data/<username>/analysis-date/<date>.json` — one full report per day.
  Games reference their PGN via a `game_slug` pointer instead of embedding
  it.
- `data/<username>/games/<slug>.json` — one file per game (immutable once
  written): metadata plus the raw PGN.

At the start of a run, if `REMOTE_DATA_BASE_URL` is set (as it is in CI, to
the workflow's own live Pages URL), it fetches the current index, every day
report it lists, and every game those reports reference — skipping games
already present locally, since they never change once written — and mirrors
all of it locally before doing anything else. This has to pull the *entire*
history, not just what this run touches: a Pages deployment replaces the
whole published tree rather than merging into it, so anything missing
locally when the artifact is built would vanish from the live site. The run
then updates whatever it needs to and the Pages deploy step publishes the
result — nothing is ever pushed to git. If the fetch fails (nothing deployed
yet, a network hiccup), it falls back to local/default state, which is fine
— a missing index just means the dashboard starts with no history.

Locally, with `REMOTE_DATA_BASE_URL` unset, `main.py` just reads/writes
`data/` directly — nothing changes from a normal script's perspective, and a
fresh `git clone` simply won't have a `data/` directory until you run
`python main.py` yourself.

## How it works

- `src/chess_com_client.py` — pulls monthly archives from the public
  Chess.com API and returns the games not already covered by a prior run
  (tracked via `last_game_end_time`, an exact Chess.com timestamp — not
  just a calendar date, so hourly runs never re-report a game already
  included in an earlier run the same day).
- `src/stockfish_engine.py` — plays through each game with Stockfish at a
  fixed depth, computing per-move centipawn loss and top-1 engine-match rate
  per player, and pre-computing FENs for any move that loses ≥100cp so
  Claude doesn't have to derive board state itself.
- `src/rule_based_coach.py` — the default analysis engine: builds the same
  report schema as the Claude path using fixed rules over the Stockfish
  telemetry (ACPL buckets, opponent risk thresholds, phase/opening
  weaknesses, and `overall_metrics.total_brilliant_moves` — the analyzed
  user's own brilliant moves only, summed across every game that day, never
  counting an opponent's). No network access required.
- `src/claude_client.py` — used only with `--use-claude`: the exact
  system/user prompts and JSON schema from the spec, sent via the Anthropic
  SDK.
- `src/persistence.py` — the three-level file-per-game/file-per-day/index
  storage described above, plus `sync_from_remote` (mirrors the live site
  before a run) and `write_latest_pointer`. A day's report can be replaced
  in place (when new games are found for that day, or via `--force` in
  backfill mode) but a day never ends up with more than one report.
- `src/pdf_report.py` / `src/mailer.py` — render the report as a PDF and
  email it.
- `index.html` — GitHub Pages dashboard: a dropdown of historical dates, a
  fair-play risk banner, and a full move-by-move replay board per game
  (start/prev/next/end controls, a slider, and a Chess.com-style move list
  with per-move think-time bars), fetched lazily from `games/<slug>.json`
  and rendered with Chess.js. `games/<slug>.json` carries `moves_analysis` —
  every move's engine best-move, centipawn loss, and heuristic "brilliant"
  flag, not just the handful flagged as key moments — classified client-side
  into the same eight Chess.com-style tiers everywhere in the UI (Brilliant /
  Best / Excellent / Good / Book / Inaccuracy / Mistake / Blunder, using
  each report's `book_plies` field for the Book cutoff):
  - every move in the **move list** gets that tier's color and, for the
    notable tiers, a standard annotation glyph (`!!`, `?!`, `?`, `??`);
  - the **board arrow** for whatever move is currently shown uses that same
    tier's color during normal navigation, plus a fixed green arrow for the
    engine's alternative whenever the move played wasn't already the top
    choice;
  - a flagged key moment's "Jump to this position" button uses the same
    tier-colored pair, just via the dedicated jump path rather than regular
    stepping.

  "Brilliant" itself is a heuristic, not a reproduction of Chess.com's
  algorithm: a move is flagged when it's the engine's own top choice, not
  forced, not in an already-decided position, and a proper multi-attacker
  exchange evaluation (`_static_exchange_eval` in `src/stockfish_engine.py`)
  says the opponent nets material on its destination square. It has no
  notion of checks, pins, or mating nets, so a move whose real justification
  is purely tactical can still get flagged. Each game also shows the
  per-player tier-count breakdown as a small table, and the board orients
  from the analyzed user's own perspective — flipped when `user_color` is
  "black" — with the arrow-overlay pixel math flipped to match, not just the
  board widget itself. Each game card also gets a Win/Loss/Draw badge and a
  matching colored accent border, computed from `result` + `user_color`
  together (the raw PGN result alone only says which color won).
