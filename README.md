# Chess Analyser

Autonomous hourly pipeline that pulls whatever Chess.com games you've played
since the last run, analyzes them with a local Stockfish engine, turns the
engine telemetry into a coaching + fair-play review, and publishes the
results as a history file, an interactive GitHub Pages dashboard, and an
emailed PDF.

Each run only fetches games newer than the last one it processed. If nothing
new was played, it's a no-op; if new games are found, they're grouped into a
single fresh report and prepended to the history — so a day with sporadic
play ends up with several reports, one per burst of games, instead of one
report per calendar day.

By default the coaching/fair-play write-up is generated locally by a
deterministic rule engine (no API key or network call needed). Pass
`--use-claude` to send the PGNs + telemetry to Claude for a richer,
LLM-generated write-up instead.

```
Chess.com API -> Stockfish (ACPL / top-1 match) -> rule engine (or Claude) -> data/analysis.json
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

Run one cycle locally (fetches every game played since the last run, runs
Stockfish at depth 14, generates the report, prepends it to
`data/analysis.json`, and writes a PDF to `reports/`):

```
python main.py --skip-email
```

Running it again immediately is safe and cheap — with no new games it just
prints "No new games found since the last run" and exits without touching
anything. This is the mode the hourly GitHub Actions workflow uses.

Add `--use-claude` to generate the write-up with Claude instead of the local
rule engine (requires `ANTHROPIC_API_KEY` and API credits). Other flags:
`--limit N` (max games to pull per run), `--skip-pdf`, `--dry-run` (print the
report without persisting/emailing anything).

### Backfilling a date range

`--since YYYY-MM-DD` (optionally with `--until YYYY-MM-DD`, default today)
switches to backfill mode: it pulls every game in that range and generates
one report per calendar day, skipping days that already have a report
(pass `--force` to regenerate one):

```
python main.py --since 2026-08-01 --until 2026-08-31 --skip-email
```

## Viewing the dashboard locally

`index.html` fetches `data/analysis.json` over HTTP, so open it through a
local server rather than as a `file://` URL:

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
`python main.py --skip-email --skip-pdf`, commits the updated
`data/analysis.json` back to the repo if it changed, and deploys the repo
root (including `index.html`) to GitHub Pages. Hours with no new games are
cheap no-ops (no commit, no new report).

Configure once in the repo's **Settings**:

- **Settings → Pages → Build and deployment → Source**: "GitHub Actions"
- **Settings → Secrets and variables → Actions → Secrets**:
  `CHESS_USERNAME`, and optionally `ANTHROPIC_API_KEY` (only if the workflow
  passes `--use-claude`), `SMTP_HOST`, `SMTP_PORT`, `SMTP_USERNAME`,
  `SMTP_PASSWORD`, `EMAIL_FROM`, `EMAIL_TO`
- **Settings → Secrets and variables → Actions → Variables** (optional):
  `ANTHROPIC_MODEL`, `GAMES_LIMIT`

Email is skipped automatically if `SMTP_HOST`/`EMAIL_TO` aren't set.

## How it works

- `src/chess_com_client.py` — pulls monthly archives from the public
  Chess.com API and returns the games not already covered by a prior run
  (tracked via `last_game_end_time`, an exact Chess.com timestamp, in
  `data/analysis.json` — not just a calendar date, so hourly runs never
  re-report a game already included in an earlier run the same day).
- `src/stockfish_engine.py` — plays through each game with Stockfish at a
  fixed depth, computing per-move centipawn loss and top-1 engine-match rate
  per player, and pre-computing FENs for any move that loses ≥100cp so
  Claude doesn't have to derive board state itself.
- `src/rule_based_coach.py` — the default analysis engine: builds the same
  report schema as the Claude path using fixed rules over the Stockfish
  telemetry (ACPL buckets, opponent risk thresholds, phase/opening
  weaknesses). No network access required.
- `src/claude_client.py` — used only with `--use-claude`: the exact
  system/user prompts and JSON schema from the spec, sent via the Anthropic
  SDK.
- `src/persistence.py` — append-only history: each run prepends a report to
  `data/analysis.json` (newest first), never overwriting past runs.
- `src/pdf_report.py` / `src/mailer.py` — render the report as a PDF and
  email it.
- `index.html` — GitHub Pages dashboard: a dropdown of historical runs, a
  fair-play risk banner, and a full move-by-move replay board per game
  (start/prev/next/end controls plus a slider) built from each game's
  embedded PGN with Chess.js. Every flagged key moment has a "Jump to this
  position" button that scrubs the replay board straight to it.
