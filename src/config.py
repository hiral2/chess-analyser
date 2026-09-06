"""Central place for environment-driven configuration."""
import os

from dotenv import load_dotenv

load_dotenv()


def _int(name: str, default: int) -> int:
    value = os.environ.get(name)
    return int(value) if value else default


CHESS_USERNAME = os.environ.get("CHESS_USERNAME", "")

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
ANTHROPIC_MODEL = os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-5")

STOCKFISH_PATH = os.environ.get("STOCKFISH_PATH", "stockfish")
STOCKFISH_DEPTH = _int("STOCKFISH_DEPTH", 14)
STOCKFISH_BOOK_PLIES = _int("STOCKFISH_BOOK_PLIES", 10)

GAMES_LIMIT = _int("GAMES_LIMIT", 10)

ANALYSIS_FILE = os.environ.get("ANALYSIS_FILE", "data/analysis.json")
REPORTS_DIR = os.environ.get("REPORTS_DIR", "reports")

SMTP_HOST = os.environ.get("SMTP_HOST", "")
SMTP_PORT = _int("SMTP_PORT", 587)
SMTP_USERNAME = os.environ.get("SMTP_USERNAME", "")
SMTP_PASSWORD = os.environ.get("SMTP_PASSWORD", "")
EMAIL_FROM = os.environ.get("EMAIL_FROM", SMTP_USERNAME)
EMAIL_TO = os.environ.get("EMAIL_TO", "")
