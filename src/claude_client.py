"""Claude API integration: master system prompt + user template from prompt.md."""
import json

from anthropic import Anthropic

SYSTEM_PROMPT = """You are an elite Grandmaster chess coach, data analyst, and fair-play compliance reviewer.

Your objective is to analyze raw PGN chess records alongside engine telemetry metrics (Average Centipawn Loss and Top-1 Match Rates) to evaluate player performance, identify tactical mistakes, detect potential opponent computer assistance, and formulate an actionable coaching plan.

Strict Execution Rules:
1. OUTPUT FORMAT: Respond ONLY with a valid JSON object strictly matching the schema provided by the user. Do not wrap the response in markdown code block syntax (do NOT use ```json). Do not include any introductory text, preambles, or concluding text outside the JSON structure.
2. FEN ACCURACY: Ensure FEN (Forsyth-Edwards Notation) strings represent the precise board state immediately PRIOR to the blunder or missed tactical move.
3. MOVE NOTATION: Use standard algebraic notation (SAN) for all move values (e.g., "Nxe5", "O-O", "Qh5+").
4. FAIR-PLAY BENCHMARKS:
   - ACPL below 15 in complex middlegames by non-titled players is statistically abnormal.
   - Top-1 Engine Match Rates exceeding 85-90% outside established opening theory indicate potential engine reliance.
5. CONCISE, HIGH-VALUE EXPLANATIONS: Avoid move-by-move summaries. Focus on systemic tactical patterns, positional flaws, time management, and clear corrective advice."""

JSON_SCHEMA_BLOCK = """{
  "date": "{CURRENT_DATE}",
  "summary": "High-level 2-3 sentence overview of main performance trends, strengths, and primary weaknesses observed across these games.",
  "overall_metrics": {
    "total_games": 0,
    "wins": 0,
    "losses": 0,
    "draws": 0,
    "primary_opening_weakness": "Name of opening or recurring structural weakness where most errors occurred",
    "tactical_accuracy_rating": "Poor / Average / Strong"
  },
  "fair_play_assessment": {
    "suspicious_activity_detected": false,
    "overall_risk_level": "LOW / MEDIUM / HIGH",
    "summary_notes": "Evaluation of opponents' play based on ACPL and top match percentages."
  },
  "games": [
    {
      "game_id": "Chess.com URL or unique ID",
      "white": "PlayerWhite",
      "black": "PlayerBlack",
      "result": "1-0 / 0-1 / 1/2-1/2",
      "user_color": "white or black",
      "opponent_fair_play": {
        "opponent_username": "OpponentName",
        "acpl": 0.0,
        "top_1_match_pct": 0.0,
        "risk_level": "LOW / MEDIUM / HIGH",
        "notes": "Specific notes on move quality or suspicious sequences played by opponent."
      },
      "key_moments": [
        {
          "move_number": 18,
          "fen": "r1bqk2r/pp1p1ppp/2n5/4p3/2B1P3/5N2/PPP2PPP/R2QK2R w KQkq - 0 9",
          "blunder_move": "Nxe5",
          "best_move": "O-O",
          "move_type": "Blunder / Missed Win / Positional Error",
          "explanation": "Nxe5 loses material to a tactical refutation. Castling keeps the position equal and safe."
        }
      ]
    }
  ],
  "coaching_plan": [
    "Specific exercise 1 (e.g., Practice Knight fork tactics in the middlegame)",
    "Specific exercise 2 (e.g., Review King and Pawn endgame technique)",
    "Specific exercise 3 (e.g., Avoid early queen pushes in the Sicilian Defense)"
  ]
}"""

USER_PROMPT_TEMPLATE = """Analyze the following PGN games played on Chess.com by user "{USERNAME}".

EVALUATION DATE: {CURRENT_DATE}

LOCAL STOCKFISH ENGINE METRICS (Depth {STOCKFISH_DEPTH}):
---
{STOCKFISH_METRICS}
---

RAW PGN DATA:
---
{PGN_DATA}
---

Generate a comprehensive review as a single, valid JSON object matching this EXACT schema:

{JSON_SCHEMA}"""


def build_user_prompt(username: str, current_date: str, pgn_data: str, stockfish_metrics: str, stockfish_depth: int) -> str:
    schema = JSON_SCHEMA_BLOCK.replace("{CURRENT_DATE}", current_date)
    return (
        USER_PROMPT_TEMPLATE
        .replace("{USERNAME}", username)
        .replace("{CURRENT_DATE}", current_date)
        .replace("{STOCKFISH_DEPTH}", str(stockfish_depth))
        .replace("{STOCKFISH_METRICS}", stockfish_metrics)
        .replace("{PGN_DATA}", pgn_data)
        .replace("{JSON_SCHEMA}", schema)
    )


def generate_analysis(
    api_key: str,
    model: str,
    username: str,
    current_date: str,
    pgn_data: str,
    stockfish_metrics: str,
    stockfish_depth: int,
    max_tokens: int = 8000,
) -> dict:
    client = Anthropic(api_key=api_key)
    user_prompt = build_user_prompt(username, current_date, pgn_data, stockfish_metrics, stockfish_depth)

    response = client.messages.create(
        model=model,
        max_tokens=max_tokens,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_prompt}],
    )

    text = "".join(block.text for block in response.content if block.type == "text").strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.startswith("json"):
            text = text[4:]
        text = text.strip()

    try:
        return json.loads(text)
    except json.JSONDecodeError as e:
        raise ValueError(f"Claude did not return valid JSON: {e}\n---\n{text[:2000]}") from e
