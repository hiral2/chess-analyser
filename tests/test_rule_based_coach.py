from src.rule_based_coach import generate_analysis
from src.stockfish_engine import GameAnalysis, MoveRecord


def _move(ply, color, cp_loss, eval_before=0, is_top1=False, san="e4", best="e4", is_brilliant=False):
    return MoveRecord(
        ply=ply,
        move_number=(ply + 1) // 2,
        mover_color=color,
        fen_before="startpos",
        san_played=san,
        san_best=best,
        cp_loss=cp_loss,
        is_top1=is_top1,
        eval_before=eval_before,
        is_brilliant=is_brilliant,
    )


def test_win_loss_draw_and_blunder_key_moments():
    won_game = GameAnalysis(url="g1", white="hero", black="villain", result="1-0")
    won_game.moves = [_move(1, "white", 10), _move(2, "black", 10)]

    lost_game = GameAnalysis(url="g2", white="villain", black="hero", result="1-0")
    lost_game.moves = [
        _move(1, "white", 10),
        _move(2, "black", 400, eval_before=0, san="Qxh7", best="O-O"),  # hero blunders as black
    ]

    report = generate_analysis("hero", "2026-09-06", [won_game, lost_game], book_plies=0)

    assert report["overall_metrics"]["wins"] == 1
    assert report["overall_metrics"]["losses"] == 1
    assert report["overall_metrics"]["draws"] == 0

    lost_game_out = next(g for g in report["games"] if g["game_id"] == "g2")
    assert lost_game_out["user_color"] == "black"
    assert len(lost_game_out["key_moments"]) == 1
    assert lost_game_out["key_moments"][0]["move_type"] == "Blunder"
    assert lost_game_out["key_moments"][0]["blunder_move"] == "Qxh7"


def test_opponent_flagged_as_high_risk_when_metrics_are_extreme():
    game = GameAnalysis(url="g1", white="hero", black="suspect", result="0-1")
    game.moves = [_move(1, "white", 50), _move(2, "black", 2, is_top1=True)] * 20

    report = generate_analysis("hero", "2026-09-06", [game], book_plies=0)

    opp = report["games"][0]["opponent_fair_play"]
    assert opp["opponent_username"] == "suspect"
    assert opp["risk_level"] == "HIGH"
    assert report["fair_play_assessment"]["overall_risk_level"] == "HIGH"
    assert report["fair_play_assessment"]["suspicious_activity_detected"] is True


def test_total_brilliant_moves_counts_only_the_analyzed_user_across_all_games():
    # hero is white in game 1 (1 brilliant move) and black in game 2 (2
    # brilliant moves). The opponent also has brilliant moves in both games,
    # which must NOT be counted toward hero's total.
    game1 = GameAnalysis(url="g1", white="hero", black="villain", result="1-0")
    game1.moves = [
        _move(1, "white", 0, is_brilliant=True),  # hero: brilliant
        _move(2, "black", 0, is_brilliant=True),  # villain: brilliant (must not count)
    ]
    game2 = GameAnalysis(url="g2", white="villain", black="hero", result="0-1")
    game2.moves = [
        _move(1, "white", 0, is_brilliant=True),  # villain: brilliant (must not count)
        _move(2, "black", 0, is_brilliant=True),  # hero: brilliant
        _move(3, "white", 10),
        _move(4, "black", 0, is_brilliant=True),  # hero: brilliant
    ]

    report = generate_analysis("hero", "2026-09-06", [game1, game2], book_plies=0)

    assert report["overall_metrics"]["total_brilliant_moves"] == 3


def test_no_games_produces_zeroed_report_without_crashing():
    report = generate_analysis("hero", "2026-09-06", [], book_plies=10)

    assert report["overall_metrics"]["total_games"] == 0
    assert report["games"] == []
    assert report["overall_metrics"]["primary_opening_weakness"] == "Insufficient opening data"
