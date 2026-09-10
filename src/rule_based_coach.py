"""Deterministic, local replacement for the Claude analysis step.

Builds the exact same report schema as `src.claude_client.generate_analysis`,
but derives every field from Stockfish telemetry with fixed rules instead of
an LLM call. No network access or API key required.
"""
from src.stockfish_engine import GameAnalysis

BLUNDER_CP = 300
MISSED_WIN_CP = 150
MISSED_WIN_EVAL_FLOOR = 250

# Opponent fair-play thresholds, per the system prompt's benchmarks:
# ACPL below 15 in complex middlegames is statistically abnormal for a
# non-titled player; top-1 match > 85-90% outside book suggests engine use.
HIGH_RISK_ACPL = 10
HIGH_RISK_TOP1 = 90
MEDIUM_RISK_ACPL = 20
MEDIUM_RISK_TOP1 = 85

TACTICAL_STRONG_ACPL = 25
TACTICAL_AVERAGE_ACPL = 50

RISK_ORDER = {"LOW": 0, "MEDIUM": 1, "HIGH": 2}


def _match_color(username: str, white: str, black: str) -> str | None:
    u = username.lower()
    if u == white.lower():
        return "white"
    if u == black.lower():
        return "black"
    return None


def _game_result_for_user(result: str, user_color: str) -> str:
    if result == "1-0":
        return "win" if user_color == "white" else "loss"
    if result == "0-1":
        return "loss" if user_color == "white" else "win"
    return "draw"


def _opponent_risk(acpl: float, top1_pct: float) -> str:
    if acpl < HIGH_RISK_ACPL and top1_pct >= HIGH_RISK_TOP1:
        return "HIGH"
    if acpl < MEDIUM_RISK_ACPL or top1_pct >= MEDIUM_RISK_TOP1:
        return "MEDIUM"
    return "LOW"


def _opponent_notes(opponent: str, acpl: float, top1_pct: float, risk: str) -> str:
    if risk == "HIGH":
        return (
            f"{opponent}'s ACPL of {acpl} with a {top1_pct}% engine top-1 match rate is far "
            f"outside typical human variance and is consistent with computer assistance."
        )
    if risk == "MEDIUM":
        return (
            f"{opponent}'s ACPL of {acpl} and {top1_pct}% top-1 match rate are stronger than "
            f"typical human play at this level; not conclusive on its own, but worth noting."
        )
    return f"{opponent}'s ACPL of {acpl} and {top1_pct}% top-1 match rate are consistent with normal human play."


def _tactical_rating(acpl: float) -> str:
    if acpl < TACTICAL_STRONG_ACPL:
        return "Strong"
    if acpl < TACTICAL_AVERAGE_ACPL:
        return "Average"
    return "Poor"


def _classify_move_type(cp_loss: int, eval_before: int) -> str:
    if cp_loss >= BLUNDER_CP:
        return "Blunder"
    if eval_before >= MISSED_WIN_EVAL_FLOOR and cp_loss >= MISSED_WIN_CP:
        return "Missed Win"
    return "Positional Error"


def _explanation(san_played: str, san_best: str, cp_loss: int, move_type: str) -> str:
    base = f"{san_played} costs about {cp_loss} centipawns versus the engine's top choice, {san_best}."
    if move_type == "Blunder":
        return base + " This likely hangs material or allows a forced tactical shot."
    if move_type == "Missed Win":
        return base + " The position was winning and this move lets the advantage slip."
    return base + " This weakens the position without an immediate tactical cost."


def _worst_phase(phase_totals: dict) -> str | None:
    scored = {phase: vals for phase, vals in phase_totals.items() if vals}
    if not scored:
        return None
    averages = {phase: sum(vals) / len(vals) for phase, vals in scored.items()}
    return max(averages, key=averages.get)


def generate_analysis(username: str, current_date: str, analyses: list[GameAnalysis], book_plies: int) -> dict:
    games_out = []
    user_moves_all = []
    phase_totals = {"opening": [], "middlegame": [], "endgame": []}
    opening_losses: dict[str, list[float]] = {}
    wins = losses = draws = 0
    risk_levels = []
    flagged_opponents = 0

    for a in analyses:
        user_color = _match_color(username, a.white, a.black) or "white"
        opponent_color = "black" if user_color == "white" else "white"
        opponent_name = a.black if user_color == "white" else a.white

        outcome = _game_result_for_user(a.result, user_color)
        if outcome == "win":
            wins += 1
        elif outcome == "loss":
            losses += 1
        else:
            draws += 1

        user_metrics = a.player_metrics(user_color)
        opp_metrics = a.player_metrics(opponent_color)
        risk = _opponent_risk(opp_metrics["acpl"], opp_metrics["top_1_match_pct"])
        risk_levels.append(risk)
        if risk in ("HIGH", "MEDIUM"):
            flagged_opponents += 1

        user_moves = [m for m in a.moves if m.mover_color == user_color]
        user_moves_all.extend(user_moves)
        if a.opening_name:
            opening_losses.setdefault(a.opening_name, []).extend(m.cp_loss for m in user_moves)

        phases = a.phase_acpl(user_color, book_plies)
        for phase, avg in phases.items():
            if avg is not None:
                phase_totals[phase].append(avg)

        key_moments = []
        for m in a.deviations(book_plies):
            if m.mover_color != user_color:
                continue
            move_type = _classify_move_type(m.cp_loss, m.eval_before)
            key_moments.append(
                {
                    "move_number": m.move_number,
                    "fen": m.fen_before,
                    "blunder_move": m.san_played,
                    "best_move": m.san_best or "?",
                    "move_type": move_type,
                    "explanation": _explanation(m.san_played, m.san_best or "?", m.cp_loss, move_type),
                    "ply": m.ply,
                }
            )

        games_out.append(
            {
                "game_id": a.url,
                "white": a.white,
                "black": a.black,
                "white_elo": a.white_elo,
                "black_elo": a.black_elo,
                "result": a.result,
                "user_color": user_color,
                "opponent_fair_play": {
                    "opponent_username": opponent_name,
                    "acpl": opp_metrics["acpl"],
                    "top_1_match_pct": opp_metrics["top_1_match_pct"],
                    "risk_level": risk,
                    "notes": _opponent_notes(opponent_name, opp_metrics["acpl"], opp_metrics["top_1_match_pct"], risk),
                },
                "key_moments": key_moments,
            }
        )

    total_games = len(analyses)
    overall_acpl = round(sum(m.cp_loss for m in user_moves_all) / len(user_moves_all), 1) if user_moves_all else 0.0
    tactical_rating = _tactical_rating(overall_acpl)

    if opening_losses:
        opening_avgs = {name: sum(losses_) / len(losses_) for name, losses_ in opening_losses.items() if losses_}
        primary_opening_weakness = max(opening_avgs, key=opening_avgs.get) if opening_avgs else "Insufficient opening data"
    else:
        primary_opening_weakness = "Insufficient opening data"

    overall_risk = "LOW"
    for level in risk_levels:
        if RISK_ORDER[level] > RISK_ORDER[overall_risk]:
            overall_risk = level
    suspicious_activity_detected = overall_risk == "HIGH" or flagged_opponents >= 2

    if flagged_opponents:
        fair_play_notes = (
            f"{flagged_opponents} of {total_games} opponent(s) showed engine-like metrics "
            f"(low ACPL and/or high top-1 match rate outside book). Highest concern: {overall_risk}."
        )
    else:
        fair_play_notes = "All opponents' ACPL and top-1 match rates were consistent with normal human play."

    total_blunders = sum(1 for m in user_moves_all if m.cp_loss >= BLUNDER_CP)
    total_brilliant_moves = sum(1 for m in user_moves_all if m.is_brilliant)

    summary = (
        f"Across {total_games} games ({wins}W/{losses}L/{draws}D), {username} averaged {overall_acpl} "
        f"centipawn loss per move, rated '{tactical_rating}'. {total_blunders} outright blunder(s) were "
        f"detected. Fair-play scan: {overall_risk} risk across opponents."
    )

    coaching_plan = []
    worst_phase = _worst_phase(phase_totals)
    if worst_phase:
        coaching_plan.append(
            f"Your highest average centipawn loss is in the {worst_phase}: focus study time and puzzle "
            f"practice there before drilling other phases."
        )
    if primary_opening_weakness != "Insufficient opening data":
        coaching_plan.append(
            f"Review core theory and typical plans in {primary_opening_weakness}, where your average "
            f"centipawn loss was highest among openings played."
        )
    if total_blunders > 0:
        coaching_plan.append(
            f"You blundered {total_blunders} time(s) this batch. Before every move, scan for hanging "
            f"pieces and forcing replies (checks, captures, threats) from your opponent."
        )
    else:
        coaching_plan.append(
            "No outright blunders were detected in this batch — focus on tightening small positional "
            "inaccuracies instead of tactics."
        )

    return {
        "date": current_date,
        "summary": summary,
        "overall_metrics": {
            "total_games": total_games,
            "wins": wins,
            "losses": losses,
            "draws": draws,
            "primary_opening_weakness": primary_opening_weakness,
            "tactical_accuracy_rating": tactical_rating,
            "total_brilliant_moves": total_brilliant_moves,
        },
        "fair_play_assessment": {
            "suspicious_activity_detected": suspicious_activity_detected,
            "overall_risk_level": overall_risk,
            "summary_notes": fair_play_notes,
        },
        "games": games_out,
        "coaching_plan": coaching_plan,
    }
