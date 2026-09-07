"""Three-level per-user data storage.

Layout under data/<username>/:
  index.json           - manifest: last_game_end_time, general_summary
                          (lifetime totals), and analysis_dates (a small
                          [{"date": "..."}] list, newest first)
  analysis-date/<date>.json - one full day report, games reference their
                          PGN via a "game_slug" pointer rather than
                          embedding it
  games/<slug>.json    - one file per game (immutable once written): the
                          raw PGN plus basic metadata, keyed by a filesystem
                          -safe slug derived from the Chess.com game id

data/latest.json (sibling to the per-username folders) just points the
static frontend at which username's data to load: {"username": "..."}.

Splitting things this way means persisting a report is "write a couple of
small files", not "load one ever-growing blob, mutate it, rewrite it whole" —
and a game's PGN, once written, never needs to be re-fetched or re-embedded
just because its day's report gets refreshed with a newly-found game.
"""
import json
import os
import re

import requests


def _slugify_game_id(game_id: str) -> str:
    """Chess.com game URLs end in a stable numeric id; use that as the
    filename. Fall back to sanitizing the whole id for anything else."""
    match = re.search(r"(\d+)/?$", game_id or "")
    if match:
        return match.group(1)
    return re.sub(r"[^A-Za-z0-9_-]+", "_", game_id or "game").strip("_") or "game"


def _games_dir(user_root: str) -> str:
    return os.path.join(user_root, "games")


def _analysis_dir(user_root: str) -> str:
    return os.path.join(user_root, "analysis-date")


def _index_path(user_root: str) -> str:
    return os.path.join(user_root, "index.json")


def _game_path(user_root: str, slug: str) -> str:
    return os.path.join(_games_dir(user_root), f"{slug}.json")


def _day_path(user_root: str, date_str: str) -> str:
    return os.path.join(_analysis_dir(user_root), f"{date_str}.json")


def write_latest_pointer(data_dir: str, username: str) -> None:
    """Write data/latest.json so the static frontend knows which username's
    folder to load without the username being hardcoded into index.html."""
    os.makedirs(data_dir, exist_ok=True)
    with open(os.path.join(data_dir, "latest.json"), "w", encoding="utf-8") as f:
        json.dump({"username": username}, f, indent=2, ensure_ascii=False)


def load_index(user_root: str) -> dict:
    index_path = _index_path(user_root)
    if os.path.exists(index_path):
        try:
            with open(index_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except json.JSONDecodeError:
            pass
    return {"last_game_end_time": 0, "general_summary": {}, "analysis_dates": []}


def _write_index(user_root: str, index: dict) -> None:
    os.makedirs(user_root, exist_ok=True)
    with open(_index_path(user_root), "w", encoding="utf-8") as f:
        json.dump(index, f, indent=2, ensure_ascii=False)


def report_exists(user_root: str, date_str: str) -> bool:
    index = load_index(user_root)
    return any(r.get("date") == date_str for r in index.get("analysis_dates", []))


def load_report(user_root: str, date_str: str) -> dict | None:
    path = _day_path(user_root, date_str)
    if not os.path.exists(path):
        return None
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def remove_report_for_date(user_root: str, date_str: str) -> None:
    index = load_index(user_root)
    index["analysis_dates"] = [r for r in index.get("analysis_dates", []) if r.get("date") != date_str]
    index["general_summary"] = _compute_general_summary(user_root, [r["date"] for r in index["analysis_dates"]])
    _write_index(user_root, index)

    path = _day_path(user_root, date_str)
    if os.path.exists(path):
        os.remove(path)


def _compute_general_summary(user_root: str, dates: list[str]) -> dict:
    total_games = wins = losses = draws = 0
    for date_str in dates:
        report = load_report(user_root, date_str)
        if not report:
            continue
        om = report.get("overall_metrics", {})
        total_games += om.get("total_games", 0)
        wins += om.get("wins", 0)
        losses += om.get("losses", 0)
        draws += om.get("draws", 0)
    return {
        "days_analyzed": len(dates),
        "total_games": total_games,
        "wins": wins,
        "losses": losses,
        "draws": draws,
    }


def persist_report(new_report: dict, user_root: str, last_game_end_time: int | None = None) -> dict:
    """Split `new_report` into its game files + one day file, and update the
    index manifest. Replaces any existing report for the same date (both the
    day's file and its index entry) rather than duplicating it.

    `last_game_end_time` is the Chess.com `end_time` (unix epoch) of the
    newest game included in `new_report`, tracked in the index so incremental
    runs (e.g. hourly) can fetch exactly the games played since the last run.
    """
    date_str = new_report.get("date")
    os.makedirs(_games_dir(user_root), exist_ok=True)
    os.makedirs(_analysis_dir(user_root), exist_ok=True)

    day_report = dict(new_report)
    day_report["games"] = []
    for game in new_report.get("games", []):
        game = dict(game)
        pgn = game.pop("pgn", None)
        moves_analysis = game.pop("moves_analysis", None)
        if pgn:
            slug = _slugify_game_id(game.get("game_id", ""))
            with open(_game_path(user_root, slug), "w", encoding="utf-8") as f:
                json.dump(
                    {
                        "game_id": game.get("game_id"),
                        "white": game.get("white"),
                        "black": game.get("black"),
                        "result": game.get("result"),
                        "pgn": pgn,
                        "moves_analysis": moves_analysis or [],
                    },
                    f,
                    indent=2,
                    ensure_ascii=False,
                )
            game["game_slug"] = slug
        day_report["games"].append(game)

    with open(_day_path(user_root, date_str), "w", encoding="utf-8") as f:
        json.dump(day_report, f, indent=2, ensure_ascii=False)

    index = load_index(user_root)
    index["analysis_dates"] = [r for r in index.get("analysis_dates", []) if r.get("date") != date_str]
    index["analysis_dates"].append({"date": date_str})
    index["analysis_dates"].sort(key=lambda r: r["date"], reverse=True)
    if last_game_end_time is not None:
        index["last_game_end_time"] = max(last_game_end_time, index.get("last_game_end_time", 0))
    index["general_summary"] = _compute_general_summary(user_root, [r["date"] for r in index["analysis_dates"]])
    _write_index(user_root, index)

    return index


def sync_from_remote(base_url: str, user_root: str) -> None:
    """Mirror the currently-published index, every day's report, and every
    game those reports reference, into the local user_root.

    This has to pull every historical day (and the games they reference),
    not just whatever this run touches: a GitHub Pages deployment replaces
    the whole published tree rather than merging into it, so anything
    missing locally when this run's artifact is built would vanish from the
    live site entirely. Game files are immutable once written, so an
    already-present local copy is trusted rather than re-fetched.

    `base_url` is the directory the index/reports/games live under (e.g.
    "https://user.github.io/repo/data/<username>", no trailing slash). Any
    failure fetching the index itself is swallowed (first-ever run, network
    hiccup) and local/default state is used instead; a failure fetching one
    day's report or one game just skips that item.
    """
    base_url = base_url.rstrip("/")
    try:
        resp = requests.get(f"{base_url}/index.json", timeout=15)
        resp.raise_for_status()
        remote_index = resp.json()
    except Exception as e:
        print(f"Could not fetch remote index from {base_url}/index.json ({e}); using local state instead.")
        return

    _write_index(user_root, remote_index)

    os.makedirs(_analysis_dir(user_root), exist_ok=True)
    os.makedirs(_games_dir(user_root), exist_ok=True)

    for entry in remote_index.get("analysis_dates", []):
        date_str = entry.get("date")
        if not date_str:
            continue
        try:
            resp = requests.get(f"{base_url}/analysis-date/{date_str}.json", timeout=15)
            resp.raise_for_status()
            day_report = resp.json()
        except Exception as e:
            print(f"  Could not fetch remote day report {date_str} ({e}); skipping.")
            continue
        with open(_day_path(user_root, date_str), "w", encoding="utf-8") as f:
            json.dump(day_report, f, indent=2, ensure_ascii=False)

        for game in day_report.get("games", []):
            slug = game.get("game_slug")
            if not slug:
                continue
            local_path = _game_path(user_root, slug)
            if os.path.exists(local_path):
                continue  # immutable once written; no need to re-fetch
            try:
                resp = requests.get(f"{base_url}/games/{slug}.json", timeout=15)
                resp.raise_for_status()
                game_data = resp.json()
            except Exception as e:
                print(f"    Could not fetch remote game {slug} ({e}); skipping.")
                continue
            with open(local_path, "w", encoding="utf-8") as f:
                json.dump(game_data, f, indent=2, ensure_ascii=False)
