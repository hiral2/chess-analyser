"""Orchestrates the full pipeline: Chess.com -> Stockfish -> coach -> persist -> PDF -> email."""
import argparse
import datetime as dt
import os
import sys

from src import config
from src.chess_com_client import get_games_in_range, get_recent_games, group_by_day
from src.mailer import send_report_email
from src.pdf_report import build_pdf
from src.persistence import load_history, persist_report, remove_report_for_date, report_exists
from src.stockfish_engine import StockfishAnalyzer, format_metrics_block


def parse_args():
    parser = argparse.ArgumentParser(description="Run one Chess.com analysis cycle.")
    parser.add_argument(
        "--limit",
        type=int,
        default=config.GAMES_LIMIT,
        help="Default mode only: max recent games to scan when checking for new activity since "
        "the last run. Each affected day is still analyzed in full regardless of this cap — "
        "increase it if the runner has been idle long enough that more than this many new "
        "games, potentially spanning more days than this can see, may have piled up.",
    )
    parser.add_argument("--skip-email", action="store_true", help="Do not send the PDF via email")
    parser.add_argument("--skip-pdf", action="store_true", help="Do not build a PDF report")
    parser.add_argument("--dry-run", action="store_true", help="Do everything except persist/email")
    parser.add_argument(
        "--use-claude",
        action="store_true",
        help="Call the Claude API for the coaching/fair-play write-up instead of the local rule-based engine",
    )
    parser.add_argument(
        "--since",
        type=str,
        default=None,
        help="Backfill mode: pull every game from this date onward (YYYY-MM-DD, UTC) and "
        "generate one report per day instead of a single combined report.",
    )
    parser.add_argument(
        "--until",
        type=str,
        default=None,
        help="Backfill mode only: last date to include (YYYY-MM-DD, UTC). Defaults to today.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Backfill mode only: overwrite a day's report if one already exists instead of skipping it",
    )
    return parser.parse_args()


def analyze_games(games: list[dict]) -> list:
    analyses = []
    with StockfishAnalyzer(config.STOCKFISH_PATH, config.STOCKFISH_DEPTH, config.STOCKFISH_BOOK_PLIES) as engine:
        for game in games:
            url = game.get("url", "unknown")
            try:
                analyses.append(engine.analyze_pgn(game["pgn"], url))
            except Exception as e:
                print(f"  Skipping {url}: {e}")
    return analyses


def build_report(args, games: list[dict], analyses: list, current_date: str) -> dict:
    if args.use_claude:
        from src.claude_client import generate_analysis as generate_analysis_claude

        stockfish_metrics = format_metrics_block(analyses, config.STOCKFISH_BOOK_PLIES)
        pgn_data = "\n\n---\n\n".join(f"[GameURL \"{g.get('url', '')}\"]\n{g['pgn']}" for g in games)
        print(f"  Requesting analysis from {config.ANTHROPIC_MODEL}...")
        return generate_analysis_claude(
            api_key=config.ANTHROPIC_API_KEY,
            model=config.ANTHROPIC_MODEL,
            username=config.CHESS_USERNAME,
            current_date=current_date,
            pgn_data=pgn_data,
            stockfish_metrics=stockfish_metrics,
            stockfish_depth=config.STOCKFISH_DEPTH,
        )

    from src.rule_based_coach import generate_analysis as generate_analysis_rules

    print("  Generating analysis with the local rule-based engine (no API call)...")
    return generate_analysis_rules(
        username=config.CHESS_USERNAME,
        current_date=current_date,
        analyses=analyses,
        book_plies=config.STOCKFISH_BOOK_PLIES,
    )


def attach_pgns(report: dict, games: list[dict]) -> None:
    """Embed each game's raw PGN so the dashboard can render full move-by-move replay."""
    pgn_by_url = {g.get("url"): g.get("pgn", "") for g in games}
    for g in report.get("games", []):
        g["pgn"] = pgn_by_url.get(g.get("game_id"), "")


def persist_and_output(args, report: dict, current_date: str, last_game_end_time: int | None = None) -> None:
    persist_report(report, config.ANALYSIS_FILE, last_game_end_time=last_game_end_time)
    print(f"  Report persisted to {config.ANALYSIS_FILE}")

    pdf_path = None
    if not args.skip_pdf:
        os.makedirs(config.REPORTS_DIR, exist_ok=True)
        file_slug = current_date.replace(":", "").replace(" ", "_")
        pdf_path = f"{config.REPORTS_DIR}/chess_report_{file_slug}.pdf"
        build_pdf(report, pdf_path, config.CHESS_USERNAME)
        print(f"  PDF written to {pdf_path}")

    if not args.skip_email and pdf_path:
        if not config.SMTP_HOST or not config.EMAIL_TO:
            print("  SMTP not configured; skipping email.")
        else:
            send_report_email(
                smtp_host=config.SMTP_HOST,
                smtp_port=config.SMTP_PORT,
                smtp_username=config.SMTP_USERNAME,
                smtp_password=config.SMTP_PASSWORD,
                email_from=config.EMAIL_FROM,
                email_to=config.EMAIL_TO,
                subject=f"Chess Analysis Report — {config.CHESS_USERNAME} — {current_date}",
                body=report.get("summary", "See attached report."),
                pdf_path=pdf_path,
            )
            print(f"  Email sent to {config.EMAIL_TO}")


def process_day(args, day: dt.date, day_games: list[dict], force_overwrite: bool) -> None:
    """Analyze one calendar day's full game list and persist it as that day's report.

    If a report for this date already exists and `force_overwrite` is False, it's
    left untouched. Otherwise a fresh report is built from `day_games` (which
    should be the *complete* set of games for that day, not just newly-found
    ones) and replaces whatever report was previously stored for that date.
    """
    date_str = day.isoformat()
    already_exists = report_exists(config.ANALYSIS_FILE, date_str)
    if already_exists and not force_overwrite:
        print(f"[{date_str}] report already exists, skipping (pass --force to overwrite)")
        return

    print(f"[{date_str}] analyzing {len(day_games)} game(s) with Stockfish (depth {config.STOCKFISH_DEPTH})...")
    analyses = analyze_games(day_games)
    if not analyses:
        print(f"[{date_str}] no games could be analyzed, skipping")
        return

    report = build_report(args, day_games, analyses, date_str)
    attach_pgns(report, day_games)

    if args.dry_run:
        print(f"[{date_str}] dry run — report generated but not persisted/emailed")
        return

    if already_exists:
        remove_report_for_date(config.ANALYSIS_FILE, date_str)

    last_game_end_time = max(g.get("end_time", 0) for g in day_games)
    persist_and_output(args, report, date_str, last_game_end_time=last_game_end_time)


def run_single(args) -> None:
    """Default mode: check for games played since the last run, and refresh the
    report for each calendar day touched by any new game.

    Reports are grouped strictly by day: if a game is discovered on a day that
    already has a report, that whole day's report is rebuilt from its complete,
    current game list (old + new together) and replaces the old one — it's
    never split into a second report for the same day. A day with no new games
    is left completely untouched, and a run that finds nothing new is a no-op.
    """
    history = load_history(config.ANALYSIS_FILE)
    since_epoch = history.get("last_game_end_time")

    print(f"Checking for games played by {config.CHESS_USERNAME} since the last run...")
    new_games = get_recent_games(config.CHESS_USERNAME, args.limit, since_epoch)
    if not new_games:
        print("No new games found since the last run. Exiting.")
        return

    affected_days = sorted(group_by_day(new_games).keys())
    print(
        f"{len(new_games)} new game(s) found, touching {len(affected_days)} day(s): "
        f"{', '.join(d.isoformat() for d in affected_days)}"
    )

    for day in affected_days:
        print(f"[{day.isoformat()}] refreshing report with that day's complete game list...")
        day_games = get_games_in_range(config.CHESS_USERNAME, day, day)
        if not day_games:
            continue
        process_day(args, day, day_games, force_overwrite=True)


def run_backfill(args) -> None:
    """Pull every game in [--since, --until] and produce one report per day."""
    try:
        start = dt.date.fromisoformat(args.since)
    except ValueError:
        sys.exit(f"--since must be YYYY-MM-DD, got {args.since!r}")
    end = dt.date.today()
    if args.until:
        try:
            end = dt.date.fromisoformat(args.until)
        except ValueError:
            sys.exit(f"--until must be YYYY-MM-DD, got {args.until!r}")
    if start > end:
        sys.exit("--since must be on or before --until")

    print(f"Fetching all games for {config.CHESS_USERNAME} from {start} to {end}...")
    games = get_games_in_range(config.CHESS_USERNAME, start, end)
    if not games:
        print("No games found in that range. Exiting.")
        return

    groups = group_by_day(games)
    print(f"Found {len(games)} games across {len(groups)} day(s). Processing oldest first...")

    for day in sorted(groups):
        process_day(args, day, groups[day], force_overwrite=args.force)


def main():
    args = parse_args()

    if not config.CHESS_USERNAME:
        sys.exit("CHESS_USERNAME is not set.")
    if args.use_claude and not config.ANTHROPIC_API_KEY:
        sys.exit("ANTHROPIC_API_KEY is not set (required for --use-claude).")

    if args.since:
        run_backfill(args)
    else:
        run_single(args)


if __name__ == "__main__":
    main()
