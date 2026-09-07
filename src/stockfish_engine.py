"""Local Stockfish analysis: per-move centipawn loss and top-1 match rate."""
from dataclasses import dataclass, field

import chess
import chess.engine
import chess.pgn
import io


MATE_SCORE = 100_000
# Cap per-move loss so a blunder into forced mate doesn't register as tens of
# thousands of centipawns and dominate the game's ACPL average.
MAX_CP_LOSS = 1000
DEVIATION_THRESHOLD_CP = 100  # flag moves that lose >= 1 pawn as candidate key moments
MAX_DEVIATIONS_PER_GAME = 5

_PIECE_VALUES = {
    chess.PAWN: 1,
    chess.KNIGHT: 3,
    chess.BISHOP: 3,
    chess.ROOK: 5,
    chess.QUEEN: 9,
    chess.KING: 0,
}
# Heuristic "brilliant move" thresholds — see _is_brilliant_move. This is a
# material-only approximation of Chess.com's "Brilliant!" annotation, not a
# faithful reproduction of it: it uses a proper multi-attacker exchange
# evaluation (see _static_exchange_eval) so it gets ordinary trades right,
# but it has no notion of checks, pins, or mating nets — a move whose real
# justification is purely tactical (not material) can still get flagged
# just because the engine also happens to confirm it's best. Good enough
# for a highlight, not a certification.
BRILLIANT_EVAL_CAP = 500  # skip already-decided positions
BRILLIANT_MIN_NET_LOSS = 2  # must risk at least a minor piece's worth, net


def _static_exchange_eval(occupied_value: int, first_side_attackers: list[int], second_side_attackers: list[int]) -> int:
    """Static Exchange Evaluation for captures piling up on one square.

    `occupied_value` is the value of whatever currently sits there, about to
    be captured by `first_side_attackers`'s cheapest piece. Recursively
    resolves the exchange: a side captures only if doing so doesn't leave
    them worse off than simply declining (0) — the standard "stop when it
    stops being profitable" rule, rather than naively playing out every
    possible capture regardless of whether it's a good idea. Returns the net
    material result for `first_side_attackers`'s side under optimal play by
    both sides.

    This ignores anything not reducible to piece values on this one square
    — discovered attacks, checks, pins, and x-ray attacks revealed as
    pieces are removed are all out of scope.
    """
    if not first_side_attackers:
        return 0
    capturing_value = first_side_attackers[0]
    remaining_first = first_side_attackers[1:]
    gain_if_capture = occupied_value - _static_exchange_eval(capturing_value, second_side_attackers, remaining_first)
    return max(0, gain_if_capture)


def _is_brilliant_move(board: chess.Board, move: chess.Move, mover_color: bool, is_top1: bool, eval_before: int) -> bool:
    """Best engine move, not forced, not in an already-decided position,
    that offers up real material: a full static-exchange evaluation of the
    destination square says the opponent nets a material gain there, yet
    the engine still endorses the move as best.
    """
    if not is_top1 or abs(eval_before) >= BRILLIANT_EVAL_CAP:
        return False
    if board.legal_moves.count() <= 1:
        return False  # forced move

    piece = board.piece_at(move.from_square)
    if piece is None or piece.piece_type in (chess.PAWN, chess.KING):
        return False
    moved_value = _PIECE_VALUES[piece.piece_type]

    captured = board.piece_at(move.to_square)
    gained_value = _PIECE_VALUES[captured.piece_type] if captured else 0

    board_after = board.copy(stack=False)
    board_after.push(move)
    opponent_color = not mover_color

    opponent_attackers = sorted(
        _PIECE_VALUES.get(board_after.piece_at(sq).piece_type, 0)
        for sq in board_after.attackers(opponent_color, move.to_square)
    )
    if not opponent_attackers:
        return False  # nothing en prise; not a sacrifice

    mover_defenders = sorted(
        _PIECE_VALUES.get(board_after.piece_at(sq).piece_type, 0)
        for sq in board_after.attackers(mover_color, move.to_square)
    )

    exchange_result = _static_exchange_eval(moved_value, opponent_attackers, mover_defenders)
    net_material_swing = gained_value - exchange_result
    return net_material_swing <= -BRILLIANT_MIN_NET_LOSS


@dataclass
class MoveRecord:
    ply: int
    move_number: int
    mover_color: str  # "white" or "black"
    fen_before: str
    san_played: str
    san_best: str | None
    cp_loss: int
    is_top1: bool
    eval_before: int  # centipawns, from the mover's point of view
    is_brilliant: bool = False


@dataclass
class GameAnalysis:
    url: str
    white: str
    black: str
    result: str
    opening_name: str = ""
    moves: list[MoveRecord] = field(default_factory=list)

    def player_metrics(self, color: str) -> dict:
        relevant = [m for m in self.moves if m.mover_color == color]
        if not relevant:
            return {"acpl": 0.0, "top_1_match_pct": 0.0, "moves_analyzed": 0}
        acpl = sum(m.cp_loss for m in relevant) / len(relevant)
        top1_pct = 100.0 * sum(1 for m in relevant if m.is_top1) / len(relevant)
        return {
            "acpl": round(acpl, 1),
            "top_1_match_pct": round(top1_pct, 1),
            "moves_analyzed": len(relevant),
        }

    def deviations(self, book_plies: int) -> list[MoveRecord]:
        candidates = [
            m for m in self.moves
            if m.ply > book_plies and m.cp_loss >= DEVIATION_THRESHOLD_CP
        ]
        candidates.sort(key=lambda m: m.cp_loss, reverse=True)
        return candidates[:MAX_DEVIATIONS_PER_GAME]

    def phase_acpl(self, color: str, book_plies: int, middlegame_end_ply: int = 40) -> dict:
        """Average centipawn loss for `color`, bucketed by game phase."""
        buckets = {"opening": [], "middlegame": [], "endgame": []}
        for m in self.moves:
            if m.mover_color != color:
                continue
            if m.ply <= book_plies:
                buckets["opening"].append(m.cp_loss)
            elif m.ply <= middlegame_end_ply:
                buckets["middlegame"].append(m.cp_loss)
            else:
                buckets["endgame"].append(m.cp_loss)
        return {
            phase: round(sum(losses) / len(losses), 1) if losses else None
            for phase, losses in buckets.items()
        }


class StockfishAnalyzer:
    def __init__(self, engine_path: str, depth: int, book_plies: int = 10):
        self.engine_path = engine_path
        self.depth = depth
        self.book_plies = book_plies
        self._engine = None

    def __enter__(self):
        self._engine = chess.engine.SimpleEngine.popen_uci(self.engine_path)
        return self

    def __exit__(self, exc_type, exc, tb):
        if self._engine:
            self._engine.quit()

    def analyze_pgn(self, pgn_text: str, url: str) -> GameAnalysis:
        game = chess.pgn.read_game(io.StringIO(pgn_text))
        if game is None:
            raise ValueError(f"Could not parse PGN for {url}")

        headers = game.headers
        analysis = GameAnalysis(
            url=url,
            white=headers.get("White", "?"),
            black=headers.get("Black", "?"),
            result=headers.get("Result", "*"),
            opening_name=_opening_name_from_headers(headers),
        )

        board = game.board()
        limit = chess.engine.Limit(depth=self.depth)
        info = self._engine.analyse(board, limit)

        for ply, move in enumerate(game.mainline_moves(), start=1):
            mover_color = "white" if board.turn == chess.WHITE else "black"
            move_number = board.fullmove_number
            fen_before = board.fen()

            score = info["score"].pov(board.turn)
            eval_before = score.score(mate_score=MATE_SCORE)
            pv = info.get("pv") or []
            best_move = pv[0] if pv else None
            san_best = board.san(best_move) if best_move else None
            is_top1 = best_move is not None and best_move == move
            san_played = board.san(move)
            is_brilliant = _is_brilliant_move(board, move, board.turn, is_top1, eval_before)

            board.push(move)
            info = self._engine.analyse(board, limit)
            eval_after = info["score"].pov(chess.WHITE if mover_color == "white" else chess.BLACK)
            eval_after = eval_after.score(mate_score=MATE_SCORE)

            cp_loss = min(MAX_CP_LOSS, max(0, eval_before - eval_after))

            analysis.moves.append(
                MoveRecord(
                    ply=ply,
                    move_number=move_number,
                    mover_color=mover_color,
                    fen_before=fen_before,
                    san_played=san_played,
                    san_best=san_best,
                    cp_loss=cp_loss,
                    is_top1=is_top1,
                    eval_before=eval_before,
                    is_brilliant=is_brilliant,
                )
            )

        return analysis


def _opening_name_from_headers(headers) -> str:
    """Best-effort human-readable opening name from Chess.com PGN headers."""
    if headers.get("Opening"):
        return headers["Opening"]
    eco_url = headers.get("ECOUrl", "")
    if eco_url:
        slug = eco_url.rstrip("/").rsplit("/", 1)[-1]
        words = slug.replace("-", " ").split()
        # Chess.com appends the disambiguating move sequence (e.g. "3.Bf4
        # Nf6 4.e3") to the slug; drop it once we hit a move-number token.
        name_words = []
        for word in words:
            if word[:1].isdigit() and "." in word:
                break
            name_words.append(word)
        name = " ".join(name_words).strip()
        if name:
            return name
    return headers.get("ECO", "")


def format_metrics_block(analyses: list[GameAnalysis], book_plies: int) -> str:
    """Render per-game engine telemetry as the STOCKFISH_METRICS text block."""
    lines = []
    for a in analyses:
        white_m = a.player_metrics("white")
        black_m = a.player_metrics("black")
        lines.append(f"Game: {a.url}")
        lines.append(f"  Result: {a.result}")
        lines.append(
            f"  White ({a.white}): ACPL={white_m['acpl']}, "
            f"Top-1 Match={white_m['top_1_match_pct']}% "
            f"(n={white_m['moves_analyzed']}, book plies excluded={book_plies})"
        )
        lines.append(
            f"  Black ({a.black}): ACPL={black_m['acpl']}, "
            f"Top-1 Match={black_m['top_1_match_pct']}% "
            f"(n={black_m['moves_analyzed']}, book plies excluded={book_plies})"
        )
        deviations = a.deviations(book_plies)
        if deviations:
            lines.append("  Significant deviations from engine best move (precomputed FEN before the move):")
            for d in deviations:
                lines.append(
                    f"    - Move {d.move_number} ({d.mover_color}): played {d.san_played}, "
                    f"engine best {d.san_best}, cp_loss={d.cp_loss}, "
                    f"fen_before=\"{d.fen_before}\""
                )
        lines.append("")
    return "\n".join(lines)
