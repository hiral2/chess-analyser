"""Append-only history tracking for data/analysis.json."""
import json
import os

import requests


def sync_from_remote(url: str, analysis_file: str) -> None:
    """Overwrite the local analysis file with the content currently published
    at `url` (e.g. the live GitHub Pages data/analysis.json), so this run
    starts from the real deployed state rather than a git-checked-out copy
    that may be stale or, in a git-push-free setup, never updated at all.

    Any failure (nothing deployed yet, network hiccup, bad JSON) is swallowed
    and the existing local file / defaults are used instead — this is a
    best-effort sync, not a hard dependency.
    """
    try:
        resp = requests.get(url, timeout=15)
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        print(f"Could not fetch remote history from {url} ({e}); using local state instead.")
        return

    os.makedirs(os.path.dirname(analysis_file) or ".", exist_ok=True)
    with open(analysis_file, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def load_history(analysis_file: str) -> dict:
    if os.path.exists(analysis_file):
        try:
            with open(analysis_file, "r", encoding="utf-8") as f:
                return json.load(f)
        except json.JSONDecodeError:
            pass
    return {"last_updated": "", "reports": []}


def report_exists(analysis_file: str, date_str: str) -> bool:
    history = load_history(analysis_file)
    return any(r.get("date") == date_str for r in history.get("reports", []))


def remove_report_for_date(analysis_file: str, date_str: str) -> None:
    history = load_history(analysis_file)
    history["reports"] = [r for r in history.get("reports", []) if r.get("date") != date_str]
    with open(analysis_file, "w", encoding="utf-8") as f:
        json.dump(history, f, indent=2, ensure_ascii=False)


def persist_report(new_report: dict, analysis_file: str, last_game_end_time: int | None = None) -> dict:
    """Prepend `new_report` to the history file (newest first) and save it.

    `last_game_end_time` is the Chess.com `end_time` (unix epoch) of the
    newest game included in `new_report`. It's tracked separately from the
    human-readable `date` field so incremental runs (e.g. hourly) can fetch
    exactly the games played since the last run, not just "since midnight of
    the last report's date" — the latter has only day granularity and would
    re-fetch/re-report games already covered earlier the same day.
    """
    os.makedirs(os.path.dirname(analysis_file) or ".", exist_ok=True)

    history = load_history(analysis_file)
    history["last_updated"] = new_report.get("date")
    if last_game_end_time is not None:
        history["last_game_end_time"] = max(last_game_end_time, history.get("last_game_end_time", 0))
    history["reports"].insert(0, new_report)

    with open(analysis_file, "w", encoding="utf-8") as f:
        json.dump(history, f, indent=2, ensure_ascii=False)

    return history
