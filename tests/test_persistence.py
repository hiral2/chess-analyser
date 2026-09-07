from unittest.mock import patch

from src.persistence import (
    load_index,
    load_report,
    persist_report,
    remove_report_for_date,
    report_exists,
    sync_from_remote,
    write_latest_pointer,
)


def _game(game_id="https://www.chess.com/game/live/12345", pgn="1. e4 e5"):
    return {"game_id": game_id, "white": "a", "black": "b", "result": "1-0", "pgn": pgn}


def test_persist_report_writes_day_file_and_game_file(tmp_path):
    user_root = str(tmp_path / "someuser")

    report = {"date": "2026-01-01", "summary": "first", "games": [_game()]}
    persist_report(report, user_root)

    index = load_index(user_root)
    assert [r["date"] for r in index["analysis_dates"]] == ["2026-01-01"]

    day_report = load_report(user_root, "2026-01-01")
    assert day_report["summary"] == "first"
    # The day file should reference the game by slug, not embed the PGN.
    assert "pgn" not in day_report["games"][0]
    slug = day_report["games"][0]["game_slug"]
    assert slug == "12345"

    game_file = tmp_path / "someuser" / "games" / "12345.json"
    assert game_file.exists()
    import json
    game_data = json.loads(game_file.read_text())
    assert game_data["pgn"] == "1. e4 e5"


def test_persist_report_replaces_existing_date_instead_of_duplicating(tmp_path):
    user_root = str(tmp_path / "someuser")

    persist_report({"date": "2026-01-01", "summary": "v1", "games": [_game()]}, user_root)
    persist_report({"date": "2026-01-01", "summary": "v2", "games": []}, user_root)

    index = load_index(user_root)
    assert len(index["analysis_dates"]) == 1
    assert load_report(user_root, "2026-01-01")["summary"] == "v2"


def test_dates_are_kept_sorted_newest_first_regardless_of_insertion_order(tmp_path):
    user_root = str(tmp_path / "someuser")

    persist_report({"date": "2026-01-01", "summary": "old", "games": []}, user_root)
    persist_report({"date": "2026-01-15", "summary": "newest", "games": []}, user_root)
    persist_report({"date": "2026-01-08", "summary": "middle", "games": []}, user_root)

    index = load_index(user_root)
    assert [r["date"] for r in index["analysis_dates"]] == ["2026-01-15", "2026-01-08", "2026-01-01"]


def test_general_summary_aggregates_across_all_days(tmp_path):
    user_root = str(tmp_path / "someuser")

    persist_report(
        {"date": "2026-01-01", "summary": "a", "games": [], "overall_metrics": {"total_games": 3, "wins": 2, "losses": 1, "draws": 0}},
        user_root,
    )
    persist_report(
        {"date": "2026-01-02", "summary": "b", "games": [], "overall_metrics": {"total_games": 2, "wins": 0, "losses": 1, "draws": 1}},
        user_root,
    )

    summary = load_index(user_root)["general_summary"]
    assert summary["days_analyzed"] == 2
    assert summary["total_games"] == 5
    assert summary["wins"] == 2
    assert summary["losses"] == 2
    assert summary["draws"] == 1


def test_load_index_returns_empty_default_when_missing(tmp_path):
    index = load_index(str(tmp_path / "missing"))
    assert index == {"last_game_end_time": 0, "general_summary": {}, "analysis_dates": []}


def test_load_index_recovers_from_corrupt_json(tmp_path):
    user_root = tmp_path / "someuser"
    user_root.mkdir()
    (user_root / "index.json").write_text("{not valid json", encoding="utf-8")

    index = load_index(str(user_root))
    assert index == {"last_game_end_time": 0, "general_summary": {}, "analysis_dates": []}


def test_load_report_returns_none_when_missing(tmp_path):
    assert load_report(str(tmp_path / "someuser"), "2026-01-01") is None


def test_report_exists_and_remove_report_for_date(tmp_path):
    user_root = str(tmp_path / "someuser")
    persist_report({"date": "2026-01-01", "summary": "a", "games": []}, user_root)

    assert report_exists(user_root, "2026-01-01") is True
    assert report_exists(user_root, "2026-01-02") is False

    remove_report_for_date(user_root, "2026-01-01")

    assert report_exists(user_root, "2026-01-01") is False
    assert load_report(user_root, "2026-01-01") is None
    # general_summary should be recomputed once that day is gone.
    assert load_index(user_root)["general_summary"]["days_analyzed"] == 0


def test_last_game_end_time_tracks_monotonic_max(tmp_path):
    user_root = str(tmp_path / "someuser")

    persist_report({"date": "2026-01-01", "summary": "a", "games": []}, user_root, last_game_end_time=1000)
    assert load_index(user_root)["last_game_end_time"] == 1000

    persist_report({"date": "2026-01-02", "summary": "b", "games": []}, user_root, last_game_end_time=2000)
    assert load_index(user_root)["last_game_end_time"] == 2000

    # An out-of-order or repeated call never moves the cursor backward.
    persist_report({"date": "2026-01-03", "summary": "c", "games": []}, user_root, last_game_end_time=500)
    assert load_index(user_root)["last_game_end_time"] == 2000


def test_write_latest_pointer(tmp_path):
    write_latest_pointer(str(tmp_path), "someuser")
    import json
    data = json.loads((tmp_path / "latest.json").read_text())
    assert data == {"username": "someuser"}


class _FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self._payload


def test_sync_from_remote_mirrors_index_reports_and_games(tmp_path):
    user_root = str(tmp_path / "someuser")
    remote_index = {
        "last_game_end_time": 999,
        "general_summary": {"days_analyzed": 2},
        "analysis_dates": [{"date": "2026-01-08"}, {"date": "2026-01-01"}],
    }
    remote_reports = {
        "2026-01-08": {"date": "2026-01-08", "summary": "newest", "games": [{"game_slug": "aaa"}]},
        "2026-01-01": {"date": "2026-01-01", "summary": "oldest", "games": [{"game_slug": "bbb"}]},
    }
    remote_games = {
        "aaa": {"game_id": "aaa", "pgn": "1. d4"},
        "bbb": {"game_id": "bbb", "pgn": "1. c4"},
    }

    def fake_get(url, timeout=None):
        if url.endswith("index.json"):
            return _FakeResponse(remote_index)
        if "/analysis-date/" in url:
            date_str = url.rsplit("/", 1)[-1].removesuffix(".json")
            return _FakeResponse(remote_reports[date_str])
        if "/games/" in url:
            slug = url.rsplit("/", 1)[-1].removesuffix(".json")
            return _FakeResponse(remote_games[slug])
        raise AssertionError(f"unexpected URL {url}")

    with patch("src.persistence.requests.get", side_effect=fake_get):
        sync_from_remote("https://example.com/data/someuser", user_root)

    index = load_index(user_root)
    assert index["last_game_end_time"] == 999
    assert [r["date"] for r in index["analysis_dates"]] == ["2026-01-08", "2026-01-01"]
    assert load_report(user_root, "2026-01-08")["summary"] == "newest"

    import json
    assert json.loads((tmp_path / "someuser" / "games" / "aaa.json").read_text())["pgn"] == "1. d4"
    assert json.loads((tmp_path / "someuser" / "games" / "bbb.json").read_text())["pgn"] == "1. c4"


def test_sync_from_remote_skips_games_already_present_locally(tmp_path):
    user_root = str(tmp_path / "someuser")
    games_dir = tmp_path / "someuser" / "games"
    games_dir.mkdir(parents=True)
    (games_dir / "aaa.json").write_text('{"game_id": "aaa", "pgn": "LOCAL COPY"}', encoding="utf-8")

    remote_index = {"last_game_end_time": 1, "analysis_dates": [{"date": "2026-01-01"}]}
    remote_report = {"date": "2026-01-01", "summary": "x", "games": [{"game_slug": "aaa"}]}
    calls = []

    def fake_get(url, timeout=None):
        calls.append(url)
        if url.endswith("index.json"):
            return _FakeResponse(remote_index)
        if "/analysis-date/" in url:
            return _FakeResponse(remote_report)
        raise AssertionError(f"should not re-fetch already-local game: {url}")

    with patch("src.persistence.requests.get", side_effect=fake_get):
        sync_from_remote("https://example.com/data/someuser", user_root)

    assert not any("/games/" in c for c in calls)
    import json
    assert json.loads((games_dir / "aaa.json").read_text())["pgn"] == "LOCAL COPY"


def test_sync_from_remote_falls_back_silently_when_index_fetch_fails(tmp_path):
    user_root = str(tmp_path / "someuser")

    def fake_get(url, timeout=None):
        raise ConnectionError("network is down")

    with patch("src.persistence.requests.get", side_effect=fake_get):
        sync_from_remote("https://example.com/data/someuser", user_root)

    assert load_index(user_root) == {"last_game_end_time": 0, "general_summary": {}, "analysis_dates": []}
