import chess

from src.stockfish_engine import _is_brilliant_move, _static_exchange_eval


def test_see_single_undefended_attacker():
    # A lone attacker with no recapture: they simply win the piece outright
    # (they don't "lose" their own capturing piece merely by using it).
    assert _static_exchange_eval(9, [3], []) == 9


def test_see_defended_piece_is_an_even_trade():
    # Attacker takes (worth 3), defender of equal value recaptures: net 0.
    assert _static_exchange_eval(3, [3], [3]) == 0


def test_see_attacker_stops_when_continuing_is_unprofitable():
    # Real position from analysis: queen (9) attacked by a knight (3) and a
    # queen (9), defended by two knights (3, 3). The attacking side should
    # capture with the knight and then stop (netting +6) rather than trade
    # queens too (which would net only 0) — this is the whole point of SEE's
    # backward resolution over a naive "just multiply out every capture".
    assert _static_exchange_eval(9, [3, 9], [3, 3]) == 6


def test_see_full_exchange_favors_more_numerous_side():
    # Rook (5) attacked by one pawn (1), defended by nothing: clean win.
    assert _static_exchange_eval(5, [1], []) == 5


def test_hanging_queen_with_no_defender_is_flagged():
    # White queen a5 -> d5. Black pawn c6 attacks d5 (diagonal capture
    # square); nothing white defends d5. A genuine, uncompensated sacrifice.
    board = chess.Board("4k3/8/2p5/Q7/8/8/8/4K3 w - - 0 1")
    move = chess.Move.from_uci("a5d5")
    assert move in board.legal_moves
    assert _is_brilliant_move(board, move, chess.WHITE, is_top1=True, eval_before=0) is True


def test_not_flagged_when_not_the_engines_top_choice():
    board = chess.Board("4k3/8/2p5/Q7/8/8/8/4K3 w - - 0 1")
    move = chess.Move.from_uci("a5d5")
    assert _is_brilliant_move(board, move, chess.WHITE, is_top1=False, eval_before=0) is False


def test_not_flagged_in_already_decided_position():
    board = chess.Board("4k3/8/2p5/Q7/8/8/8/4K3 w - - 0 1")
    move = chess.Move.from_uci("a5d5")
    assert _is_brilliant_move(board, move, chess.WHITE, is_top1=True, eval_before=900) is False


def test_equal_value_trade_with_defender_is_not_a_sacrifice():
    # White knight c4 -> e3. Black knight d5 attacks e3, but white pawn d2
    # defends it: recapturing the attacking knight nets back its full value,
    # so the overall trade is even, not a material sacrifice.
    board = chess.Board("4k3/8/8/3n4/2N5/8/3P4/4K3 w - - 0 1")
    move = chess.Move.from_uci("c4e3")
    assert move in board.legal_moves
    assert _is_brilliant_move(board, move, chess.WHITE, is_top1=True, eval_before=0) is False


def test_no_attackers_after_move_is_not_flagged():
    board = chess.Board("4k3/8/8/3n4/8/8/3R4/3NK3 w - - 0 1")
    move = chess.Move.from_uci("d1b2")
    assert move in board.legal_moves
    # b2 isn't attacked by anything black here — nothing hanging, no sacrifice.
    assert _is_brilliant_move(board, move, chess.WHITE, is_top1=True, eval_before=0) is False


def test_pawn_moves_are_never_flagged():
    board = chess.Board()
    move = chess.Move.from_uci("e2e4")
    assert _is_brilliant_move(board, move, chess.WHITE, is_top1=True, eval_before=0) is False


def test_forced_move_is_not_flagged():
    # Black king h8 in check from Rh1, with h7/g7 controlled by white king
    # f6 — Kh8-g8 is the only legal move.
    board = chess.Board("7k/8/5K2/8/8/8/8/7R b - - 0 1")
    assert board.legal_moves.count() == 1
    move = next(iter(board.legal_moves))
    assert _is_brilliant_move(board, move, chess.BLACK, is_top1=True, eval_before=0) is False
