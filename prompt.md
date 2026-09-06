# Autonomous Chess Analysis & Fair-Play Coaching System

This document contains the complete system architecture, prompt engineering specifications, JSON schemas, and implementation rules for the automated Chess.com analysis pipeline powered by Claude, Stockfish, and GitHub Actions.

---

## 1. System Architecture Overview

┌────────────────────────┐
                      │   Chess.com Public API │
                      └───────────┬────────────┘
                                  │ (Fetch PGNs)
                                  ▼
                      ┌────────────────────────┐
                      │ Local Stockfish Engine │
                      └───────────┬────────────┘
                                  │ (Calculate ACPL & Top-1 Matches)
                                  ▼
                      ┌────────────────────────┐
                      │   Anthropic Claude API │
                      └───────────┬────────────┘
                                  │ (Generate Structured Analysis)
                                  ▼
     ┌────────────────────────────┴────────────────────────────┐
     │                                                         │
     ▼                                                         ▼
┌─────────────────────────┐                               ┌─────────────────┐
│   data/analysis.json    │                               │ ReportLab Engine│
└────────┬────────────────┘                               └────────┬────────┘
│ (Persist History)                                       │ (Build PDF)
▼                                                         ▼
┌─────────────────────────┐                               ┌─────────────────┐
│ GitHub Pages Dashboard  │                               │ SMTP Mailer     │
│ (Interactive Chessboard)│                               │ (Send Email)    │
└─────────────────────────┘                               └─────────────────┘


---

## 2. Master System Prompt (API `system` parameter)

Set this exact text as the `system` parameter when calling `client.messages.create()`.

```text
You are an elite Grandmaster chess coach, data analyst, and fair-play compliance reviewer.

Your objective is to analyze raw PGN chess records alongside engine telemetry metrics (Average Centipawn Loss and Top-1 Match Rates) to evaluate player performance, identify tactical mistakes, detect potential opponent computer assistance, and formulate an actionable coaching plan.

Strict Execution Rules:
1. OUTPUT FORMAT: Respond ONLY with a valid JSON object strictly matching the schema provided by the user. Do not wrap the response in markdown code block syntax (do NOT use ```json). Do not include any introductory text, preambles, or concluding text outside the JSON structure.
2. FEN ACCURACY: Ensure FEN (Forsyth-Edwards Notation) strings represent the precise board state immediately PRIOR to the blunder or missed tactical move.
3. MOVE NOTATION: Use standard algebraic notation (SAN) for all move values (e.g., "Nxe5", "O-O", "Qh5+").
4. FAIR-PLAY BENCHMARKS:
   - ACPL below 15 in complex middlegames by non-titled players is statistically abnormal.
   - Top-1 Engine Match Rates exceeding 85-90% outside established opening theory indicate potential engine reliance.
5. CONCISE, HIGH-VALUE EXPLANATIONS: Avoid move-by-move summaries. Focus on systemic tactical patterns, positional flaws, time management, and clear corrective advice.
3. Master User Prompt Template (API messages parameter)
Inject your dynamic variables ({USERNAME}, {CURRENT_DATE}, {PGN_DATA}, and {STOCKFISH_METRICS}) into this template prior to invoking the Claude API.

Plaintext
Analyze the following PGN games played on Chess.com by user "{USERNAME}".

EVALUATION DATE: {CURRENT_DATE}

LOCAL STOCKFISH ENGINE METRICS (Depth 14):
---
{STOCKFISH_METRICS}
---

RAW PGN DATA:
---
{PGN_DATA}
---

Generate a comprehensive review as a single, valid JSON object matching this EXACT schema:

{
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
}
4. Frontend Interactive Dashboard Integration (index.html)
When GitHub Actions updates data/analysis.json, the following frontend template (hosted on GitHub Pages) fetches the JSON history, displays historical weekly runs, and renders interactive chessboards for every identified blunder using Chessboard.js.

HTML
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <title>Chess Performance & Fair-Play Dashboard</title>
  <link rel="stylesheet" href="https://unpkg.com/@chrisoakman/chessboardjs@1.0.0/dist/chessboard-1.0.0.min.css">
  <script src="https://code.jquery.com/jquery-3.5.1.min.js"></script>
  <script src="https://unpkg.com/@chrisoakman/chessboardjs@1.0.0/dist/chessboard-1.0.0.min.js"></script>
  <style>
    body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; max-width: 900px; margin: 40px auto; padding: 0 20px; background: #f7fafc; color: #2d3748; }
    .header { background: #fff; padding: 24px; border-radius: 8px; box-shadow: 0 1px 3px rgba(0,0,0,0.1); margin-bottom: 24px; }
    .card { background: #fff; border: 1px solid #e2e8f0; padding: 20px; border-radius: 8px; margin-bottom: 20px; box-shadow: 0 1px 2px rgba(0,0,0,0.05); }
    .board { width: 320px; margin: 15px 0; }
    .badge { display: inline-block; padding: 4px 8px; border-radius: 4px; font-size: 12px; font-weight: bold; text-transform: uppercase; }
    .badge-low { background: #c6f6d5; color: #22543d; }
    .badge-medium { background: #feebc8; color: #744210; }
    .badge-high { background: #fed7d7; color: #742a2a; }
    select { padding: 8px 12px; border-radius: 6px; border: 1px solid #cbd5e0; font-size: 14px; margin-bottom: 16px; }
  </style>
</head>
<body>

  <div class="header">
    <h1>Chess Analysis Dashboard</h1>
    <label for="report-select"><strong>Select Analysis Run:</strong></label>
    <select id="report-select" onchange="renderSelectedReport()"></select>
    <p id="summary-text"></p>
    <div id="fair-play-banner"></div>
  </div>

  <div id="moments-container"></div>

  <script>
    let reportHistory = [];

    fetch('./data/analysis.json')
      .then(res => res.json())
      .then(data => {
        reportHistory = data.reports || [];
        const select = document.getElementById('report-select');

        reportHistory.forEach((report, index) => {
          const opt = document.createElement('option');
          opt.value = index;
          opt.textContent = `Report Date: ${report.date}`;
          select.appendChild(opt);
        });

        if (reportHistory.length > 0) {
          renderReport(0);
        }
      });

    function renderSelectedReport() {
      const idx = document.getElementById('report-select').value;
      renderReport(idx);
    }

    function renderReport(index) {
      const report = reportHistory[index];
      document.getElementById('summary-text').innerText = report.summary;
      
      const fp = report.fair_play_assessment || {};
      const fpClass = fp.overall_risk_level === 'HIGH' ? 'badge-high' : (fp.overall_risk_level === 'MEDIUM' ? 'badge-medium' : 'badge-low');
      document.getElementById('fair-play-banner').innerHTML = `
        <p><strong>Fair-Play Risk Level:</strong> <span class="badge ${fpClass}">${fp.overall_risk_level || 'LOW'}</span> — ${fp.summary_notes || 'No engine anomalies detected.'}</p>
      `;

      const container = document.getElementById('moments-container');
      container.innerHTML = '';

      report.games.forEach((game, gIdx) => {
        game.key_moments.forEach((moment, mIdx) => {
          const boardId = `board-${index}-${gIdx}-${mIdx}`;
          const card = document.createElement('div');
          card.className = 'card';
          card.innerHTML = `
            <h3>Move ${moment.move_number}: <span style="color: #e53e3e;">${moment.blunder_move}</span> (${moment.move_type})</h3>
            <p><strong>Recommended Move:</strong> <span style="color: #38a169;">${moment.best_move}</span></p>
            <div id="${boardId}" class="board"></div>
            <p><em>${moment.explanation}</em></p>
          `;
          container.appendChild(card);

          Chessboard(boardId, {
            position: moment.fen,
            draggable: false
          });
        });
      });
    }
  </script>
</body>
</html>
5. Persistence Protocol (Historical JSON Tracking)
To ensure past run metadata is never overwritten in data/analysis.json, use this append-only logic within the execution environment:

Python
import json
import os

ANALYSIS_FILE = "data/analysis.json"


def persist_report(new_report: dict):
    os.makedirs(os.path.dirname(ANALYSIS_FILE), exist_ok=True)

    if os.path.exists(ANALYSIS_FILE):
        try:
            with open(ANALYSIS_FILE, "r", encoding="utf-8") as f:
                history = json.load(f)
        except json.JSONDecodeError:
            history = {"last_updated": "", "reports": []}
    else:
        history = {"last_updated": "", "reports": []}

    # Prepend new report to keep chronological sequence (newest first)
    history["last_updated"] = new_report.get("date")
    history["reports"].insert(0, new_report)

    with open(ANALYSIS_FILE, "w", encoding="utf-8") as f:
        json.dump(history, f, indent=2, ensure_ascii=False)