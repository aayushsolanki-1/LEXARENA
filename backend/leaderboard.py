"""
leaderboard.py
--------------
A tiny, file-backed leaderboard. No database - just a JSON file on disk next to
the backend. Good enough for a single-machine exhibition setup.

Boards are split by MODE ("solo", "mirror", "player") AND by the DIFFICULTY the
player STARTED on ("easy", "medium", "hard", "advanced"). So there are up to
3 x 4 = 12 separate top-15 lists. Difficulty is the starting choice, which is
the fair, comparable label (in Hard/Advanced the level can ladder mid-run, but
the starting rung is what we rank by).

Every finished run is its own entry (no dedup). Ranking within a board: highest
score first; ties broken by whoever reached it EARLIER.

Storage shape (leaderboard.json):
  {
    "solo":   {"easy":[{"name","score","ts"},...], "medium":[...], "hard":[...], "advanced":[...]},
    "mirror": {...},
    "player": {...}
  }

Everything is defensive: missing/corrupt file -> empty; writes are atomic
(temp file + os.replace) so a crash mid-write can't corrupt it.
"""

import json
import os
import time
import tempfile
import threading


_LB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "leaderboard.json")

VALID_MODES = ("solo", "mirror", "player")
VALID_DIFFS = ("easy", "medium", "hard", "advanced")
TOP_N = 15
_MAX_NAME_LEN = 24
_MAX_KEPT_PER_BOARD = 300      # cap rows per (mode,difficulty) board

_lock = threading.Lock()


def _empty() -> dict:
    return {m: {d: [] for d in VALID_DIFFS} for m in VALID_MODES}


def _valid_row(r) -> bool:
    return (
        isinstance(r, dict)
        and isinstance(r.get("name"), str)
        and isinstance(r.get("score"), (int, float))
        and isinstance(r.get("ts"), (int, float))
    )


def _load() -> dict:
    try:
        with open(_LB_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return _empty()
    if not isinstance(data, dict):
        return _empty()
    out = _empty()
    for m in VALID_MODES:
        mode_obj = data.get(m, {})
        if not isinstance(mode_obj, dict):
            continue
        for d in VALID_DIFFS:
            rows = mode_obj.get(d, [])
            if isinstance(rows, list):
                out[m][d] = [r for r in rows if _valid_row(r)]
    return out


def _save(data: dict) -> None:
    dirn = os.path.dirname(_LB_PATH)
    fd, tmp = tempfile.mkstemp(prefix=".lb_", suffix=".json", dir=dirn)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, _LB_PATH)
    except OSError:
        try:
            os.remove(tmp)
        except OSError:
            pass


def _sorted(rows: list) -> list:
    return sorted(rows, key=lambda r: (-float(r["score"]), float(r["ts"])))


def _clean_name(name: str) -> str:
    name = (name or "").strip()
    if not name:
        name = "ANON"
    return name[:_MAX_NAME_LEN]


def _norm_mode(mode: str) -> str:
    return mode if mode in VALID_MODES else "solo"


def _norm_diff(diff: str) -> str:
    diff = (diff or "").strip().lower()
    return diff if diff in VALID_DIFFS else "easy"


def submit(name: str, mode: str, difficulty: str, score: int) -> dict:
    """
    Record one finished run on the (mode, difficulty) board. Returns placement:
      {"rank", "total", "in_top", "top": [...]}
    """
    mode = _norm_mode(mode)
    difficulty = _norm_diff(difficulty)
    try:
        score = int(score)
    except (TypeError, ValueError):
        score = 0
    if score < 0:
        score = 0

    entry = {"name": _clean_name(name), "score": score, "ts": time.time()}

    with _lock:
        data = _load()
        board = data[mode][difficulty]
        board.append(entry)
        ordered = _sorted(board)
        if len(ordered) > _MAX_KEPT_PER_BOARD:
            ordered = ordered[:_MAX_KEPT_PER_BOARD]
        data[mode][difficulty] = ordered
        _save(data)

    rank = next(
        (i + 1 for i, r in enumerate(ordered)
         if r["ts"] == entry["ts"] and r["name"] == entry["name"]
         and r["score"] == entry["score"]),
        len(ordered),
    )
    return {
        "rank": rank,
        "total": len(ordered),
        "in_top": rank <= TOP_N,
        "top": top(mode, difficulty),
    }


def top(mode: str, difficulty: str, n: int = TOP_N) -> list:
    """Top-n rows for one (mode, difficulty) board, as {rank, name, score}."""
    mode = _norm_mode(mode)
    difficulty = _norm_diff(difficulty)
    with _lock:
        data = _load()
    ordered = _sorted(data[mode][difficulty])[:n]
    return [
        {"rank": i + 1, "name": r["name"], "score": int(r["score"])}
        for i, r in enumerate(ordered)
    ]


def all_top(n: int = TOP_N) -> dict:
    """Top-n for every (mode, difficulty) board."""
    return {m: {d: top(m, d, n) for d in VALID_DIFFS} for m in VALID_MODES}


def clear(mode: str = None, difficulty: str = None) -> None:
    """
    Admin wipe:
      clear()                      -> everything
      clear("solo")                -> all difficulties of Solo
      clear("solo", "easy")        -> just Solo/Easy
    """
    with _lock:
        data = _load()
        if mode in VALID_MODES and difficulty in VALID_DIFFS:
            data[mode][difficulty] = []
        elif mode in VALID_MODES:
            data[mode] = {d: [] for d in VALID_DIFFS}
        else:
            data = _empty()
        _save(data)


# --- manual test -----------------------------------------------------------
if __name__ == "__main__":
    clear()
    print(submit("AAYUSH", "solo", "easy", 40))
    print(submit("ROSE", "solo", "easy", 55))
    print(submit("LEWIS", "solo", "hard", 55))   # different board
    print("solo/easy:", top("solo", "easy"))
    print("solo/hard:", top("solo", "hard"))
