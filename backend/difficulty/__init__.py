"""
difficulty/__init__.py
----------------------
Makes the `difficulty` folder an importable package and provides one helper,
get_difficulty(), so the rest of the backend can fetch a level by name without
importing each file by hand.

Usage:
    from difficulty import get_difficulty, LEVELS

    level = get_difficulty("medium")
    level.DIFFICULTY_LABEL   # "Medium"
    level.BENCHMARK          # "This question should be answerable by..."
    level.TIME_LIMIT         # 25

LEVELS is the ordered ladder (easy -> advanced), used by game.py to step
difficulty up or down.
"""

from . import easy, medium, hard, advanced

# Ordered easiest -> hardest. game.py uses this order to ladder difficulty.
LEVELS = ["easy", "medium", "hard", "advanced"]

_MODULES = {
    "easy": easy,
    "medium": medium,
    "hard": hard,
    "advanced": advanced,
}


def get_difficulty(name: str):
    """
    Return the difficulty module for `name` (e.g. "medium").
    Falls back to easy if an unknown name is passed, so a bad value never
    crashes question generation.
    """
    key = (name or "").strip().lower()
    return _MODULES.get(key, easy)
