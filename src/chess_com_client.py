"""Minimal client for the public (unauthenticated) Chess.com API."""
import datetime as dt
from collections import defaultdict
from typing import Optional

import requests

BASE_URL = "https://api.chess.com/pub"
# Chess.com asks API consumers to identify themselves with a descriptive UA.
HEADERS = {"User-Agent": "chess-analyser (contact: repo owner via GitHub)"}


def get_archive_urls(username: str) -> list[str]:
    resp = requests.get(f"{BASE_URL}/player/{username}/games/archives", headers=HEADERS, timeout=30)
    resp.raise_for_status()
    return resp.json().get("archives", [])


def get_recent_games(username: str, limit: int, since_epoch: Optional[int] = None) -> list[dict]:
    """Return up to `limit` most recent finished games, newest first.

    If `since_epoch` is given, only games that ended after that unix
    timestamp are considered (used to avoid re-analyzing games already
    present in a previous run's history).
    """
    archive_urls = get_archive_urls(username)
    if not archive_urls:
        return []

    games: list[dict] = []
    # Walk archives newest-first until we have enough games.
    for url in reversed(archive_urls):
        resp = requests.get(url, headers=HEADERS, timeout=30)
        resp.raise_for_status()
        month_games = resp.json().get("games", [])
        # Chess.com returns games oldest-first within a month.
        for game in reversed(month_games):
            if "pgn" not in game:
                continue
            if since_epoch and game.get("end_time", 0) <= since_epoch:
                continue
            games.append(game)
            if len(games) >= limit:
                return games
        if since_epoch and month_games and month_games[0].get("end_time", 0) <= since_epoch:
            # Older archives are entirely before the cutoff; stop early.
            break
    return games


def get_games_in_range(username: str, start: dt.date, end: dt.date) -> list[dict]:
    """Return every game played in [start, end] (inclusive, UTC), oldest first."""
    games: list[dict] = []
    year, month = start.year, start.month
    while (year, month) <= (end.year, end.month):
        url = f"{BASE_URL}/player/{username}/games/{year}/{month:02d}"
        resp = requests.get(url, headers=HEADERS, timeout=30)
        if resp.status_code == 404:
            month_games = []
        else:
            resp.raise_for_status()
            month_games = resp.json().get("games", [])

        for game in month_games:
            if "pgn" not in game or "end_time" not in game:
                continue
            game_date = dt.datetime.fromtimestamp(game["end_time"], tz=dt.timezone.utc).date()
            if start <= game_date <= end:
                games.append(game)

        month, year = (1, year + 1) if month == 12 else (month + 1, year)

    games.sort(key=lambda g: g.get("end_time", 0))
    return games


def group_by_day(games: list[dict]) -> dict[dt.date, list[dict]]:
    """Bucket games by the UTC calendar date they ended on."""
    groups: dict[dt.date, list[dict]] = defaultdict(list)
    for game in games:
        day = dt.datetime.fromtimestamp(game["end_time"], tz=dt.timezone.utc).date()
        groups[day].append(game)
    return dict(groups)
