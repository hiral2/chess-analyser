import json

from src.persistence import load_history, persist_report


def test_persist_report_prepends_newest_first(tmp_path):
    analysis_file = str(tmp_path / "analysis.json")

    persist_report({"date": "2026-01-01", "summary": "first"}, analysis_file)
    persist_report({"date": "2026-01-08", "summary": "second"}, analysis_file)

    history = load_history(analysis_file)
    assert history["last_updated"] == "2026-01-08"
    assert [r["summary"] for r in history["reports"]] == ["second", "first"]


def test_load_history_returns_empty_default_when_missing(tmp_path):
    history = load_history(str(tmp_path / "missing.json"))
    assert history == {"last_updated": "", "reports": []}


def test_load_history_recovers_from_corrupt_json(tmp_path):
    analysis_file = tmp_path / "analysis.json"
    analysis_file.write_text("{not valid json", encoding="utf-8")

    history = load_history(str(analysis_file))
    assert history == {"last_updated": "", "reports": []}


def test_last_game_end_time_tracks_monotonic_max(tmp_path):
    analysis_file = str(tmp_path / "analysis.json")

    persist_report({"date": "d1", "summary": "a"}, analysis_file, last_game_end_time=1000)
    assert load_history(analysis_file)["last_game_end_time"] == 1000

    # A later run covering games up through a newer timestamp advances the cursor.
    persist_report({"date": "d2", "summary": "b"}, analysis_file, last_game_end_time=2000)
    assert load_history(analysis_file)["last_game_end_time"] == 2000

    # An out-of-order or repeated call never moves the cursor backward.
    persist_report({"date": "d3", "summary": "c"}, analysis_file, last_game_end_time=500)
    assert load_history(analysis_file)["last_game_end_time"] == 2000
