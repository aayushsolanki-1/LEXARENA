"""
tracker.py
----------
The BehaviorTracker watches how the player behaves over the course of a game
and turns those observations into a short plain-English summary.

That summary is the ONLY thing the LLM sees about the player. The LLM never
sees raw numbers or tables - it reads a human-readable paragraph like:

    "Player answers fairly slowly (avg 12s). Prefers short, common words.
     Weak on double-meaning challenges (1/4 correct).
     Strong on rhyme challenges (3/3 correct)."

This is the heart of the project's argument: all the *counting* happens here in
plain Python (LLMs are bad at statistics), and all the *reasoning* about what to
do with it happens in the LLM. Clean separation.

Usage:
    from tracker import BehaviorTracker

    tracker = BehaviorTracker()
    tracker.log_round(
        round_number=1,
        challenge_category="double-meaning",
        player_answer="turbulent",
        time_taken=12.4,
        was_correct=True,
    )
    summary = tracker.get_summary()   # -> a string to feed the LLM
"""

from dataclasses import dataclass, field
from statistics import mean


# ---------------------------------------------------------------------------
# One round's worth of data. A dataclass is just a tidy container for fields -
# think of it as a labelled row in a spreadsheet.
# ---------------------------------------------------------------------------
@dataclass
class RoundRecord:
    round_number: int
    challenge_category: str   # the label the LLM gave this challenge
    player_answer: str
    time_taken: float         # seconds the player took to answer
    was_correct: bool         # the LLM's verdict on the answer


class BehaviorTracker:
    """Logs every round and summarises the player's patterns so far."""

    # If the player is slower than this (seconds) on average, we call them slow.
    SLOW_THRESHOLD = 10.0
    # Average answer length (in characters) below this counts as "short words".
    SHORT_WORD_THRESHOLD = 6

    def __init__(self) -> None:
        # Every round we've seen, in order. Starts empty.
        self.rounds: list[RoundRecord] = []

    # -- recording -----------------------------------------------------------

    def log_round(
        self,
        round_number: int,
        challenge_category: str,
        player_answer: str,
        time_taken: float,
        was_correct: bool,
    ) -> None:
        """Store one round. Called once per round, after the LLM has judged."""
        self.rounds.append(
            RoundRecord(
                round_number=round_number,
                challenge_category=challenge_category.strip().lower(),
                player_answer=player_answer.strip(),
                time_taken=float(time_taken),
                was_correct=bool(was_correct),
            )
        )

    # -- the summary the LLM reads ------------------------------------------

    def get_summary(self) -> str:
        """
        Build the plain-English paragraph the LLM uses to adapt the next
        challenge. If no rounds have happened yet, say so plainly - the LLM
        will then produce a neutral opening challenge (this is exactly the
        "fresh profile" behaviour you'll show off in the live demo).
        """
        if not self.rounds:
            return "No rounds played yet. This is the player's first challenge."

        parts: list[str] = []
        parts.append(self._speed_sentence())
        parts.append(self._word_length_sentence())
        parts.extend(self._category_sentences())

        # Filter out any empty strings, then join into one paragraph.
        return " ".join(p for p in parts if p)

    # -- private helpers (one sentence each) ---------------------------------

    def _speed_sentence(self) -> str:
        avg_time = mean(r.time_taken for r in self.rounds)
        pace = "slowly" if avg_time > self.SLOW_THRESHOLD else "quickly"
        return f"Player tends to answer {pace} (avg {avg_time:.0f}s)."

    def _word_length_sentence(self) -> str:
        # Only count answers that actually have content.
        lengths = [len(r.player_answer) for r in self.rounds if r.player_answer]
        if not lengths:
            return ""
        avg_len = mean(lengths)
        if avg_len < self.SHORT_WORD_THRESHOLD:
            return "Prefers short, common words."
        return "Tends to use longer, more elaborate words."

    def _category_sentences(self) -> list[str]:
        """
        Group rounds by the challenge category the LLM assigned, then report
        how the player did in each. e.g. "Weak on double-meaning (1/4)."
        """
        # tally[category] = [correct_count, total_count]
        tally: dict[str, list[int]] = {}
        for r in self.rounds:
            cat = r.challenge_category or "uncategorised"
            if cat not in tally:
                tally[cat] = [0, 0]
            tally[cat][1] += 1            # total
            if r.was_correct:
                tally[cat][0] += 1        # correct

        sentences: list[str] = []
        for category, (correct, total) in tally.items():
            ratio = correct / total
            if ratio >= 0.7:
                strength = "Strong"
            elif ratio <= 0.4:
                strength = "Weak"
            else:
                strength = "Mixed"
            sentences.append(
                f"{strength} on {category} challenges ({correct}/{total} correct)."
            )
        return sentences

    # -- small conveniences --------------------------------------------------

    @property
    def total_score_eligible_rounds(self) -> int:
        """How many rounds have been logged so far."""
        return len(self.rounds)

    def reset(self) -> None:
        """Wipe all history - used to start a brand-new game."""
        self.rounds.clear()

if __name__ == "__main__":
    t = BehaviorTracker()
    print("EMPTY:", t.get_summary())
    t.log_round(1, "rhyme", "cat", 4.2, True)
    t.log_round(2, "double-meaning", "thing", 15.8, False)
    t.log_round(3, "rhyme", "bat", 3.9, True)
    print("AFTER 3:", t.get_summary())