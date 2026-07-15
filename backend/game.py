"""
game.py
-------
The referee and scorekeeper. Holds everything that defines one match across
the three modes, manages the two-turn round flow, the 7-round counter, and the
dual scoreboard. It does NOT talk to the model - it only manages STATE. The
question master, judge, and Mirror-as-player live in their own modules and are
called by main.py, which feeds the results back into the methods here.

THREE MODES (set when the game is created):
  "solo"   - one human vs the Mirror persona. No round limit. One turn per round
             (just the human). Difficulty ladders up/down with performance.
  "mirror" - 7 rounds. Each round has TWO turns: the human answers their own
             question, then the Mirror answers ITS own (different) question.
  "player" - 7 rounds. Each round has TWO turns: player 1, then player 2, each
             with their own question. The Mirror is a neutral question master.

ROUND FLOW (a tiny state machine):
  AWAITING_QUESTION -> a question needs to be generated for the active turn
  AWAITING_ANSWER   -> question shown, waiting for the answer to be judged
  ROUND_COMPLETE    -> all turns done this round, ready for the next round

Scores live in a dict: {"p1": int, "opp": int}. "opp" is the Mirror (modes
solo/mirror) or player 2 (mode player). Solo only ever uses "p1".

Difficulty adapts (Tim's system): we start at the player's chosen level and
step UP a rung after a correct p1 answer, DOWN after a miss. Fair, never buried.

Timing is measured by the FRONTEND and passed in - game.py never runs a clock.
"""

from dataclasses import dataclass
from enum import Enum

from tracker import BehaviorTracker
from difficulty import LEVELS   # ["easy","medium","hard","advanced"]


VALID_MODES = ("solo", "mirror", "player")

# --- Streak bonus -----------------------------------------------------------
# When a side answers 3 (or more) correct IN A ROW, they earn a bonus on top of
# the normal points. The bonus depends on the difficulty of the answer that
# completed/continued the streak: harder streaks are worth more.
#   easy +5, medium +7, hard +9, advanced +11  (i.e. +5 base, +2 per level up)
# A wrong answer resets the streak to zero.
STREAK_THRESHOLD = 3
STREAK_BONUS_BY_DIFFICULTY = {
    "easy": 5,
    "medium": 7,
    "hard": 9,
    "advanced": 11,
}


class RoundState(Enum):
    AWAITING_QUESTION = "awaiting_question"
    AWAITING_ANSWER = "awaiting_answer"
    ROUND_COMPLETE = "round_complete"


@dataclass
class CurrentQuestion:
    question: str
    category: str
    answer_example: str = ""
    difficulty: str = ""
    for_side: str = "p1"     # "p1" or "opp" - whose turn this question is for


class Game:
    """Manages one match in one of the three modes."""

    def __init__(self, topic: str = "", mode: str = "solo",
                 start_difficulty: str = "easy", max_rounds: int = 7,
                 language: str = "en") -> None:
        if mode not in VALID_MODES:
            mode = "solo"
        self.topic = topic.strip()
        self.mode = mode
        # Language the questions/verdicts should be written in ("en" or "de").
        self.language = language if language in ("en", "de") else "en"
        self.max_rounds = float("inf") if mode == "solo" else max_rounds

        # Two trackers so each side gets its own behaviour profile.
        self.trackers = {"p1": BehaviorTracker(), "opp": BehaviorTracker()}

        self.difficulty = start_difficulty if start_difficulty in LEVELS else "easy"
        # The level the player originally chose. Easy/Medium LOCK the difficulty
        # for the whole match (every round stays at that level); Hard/Advanced
        # let the difficulty ladder up/down with performance (see submit_answer).
        self.start_difficulty = self.difficulty
        self.round_number = 0
        self.scores = {"p1": 0, "opp": 0}
        self.state = RoundState.AWAITING_QUESTION
        self.active_side = "p1"          # whose turn it is right now
        self.current_question: CurrentQuestion | None = None
        self.history: list[dict] = []    # flat log of every turn, for recap
        self.asked_questions: list[str] = []  # every question asked this game,
        #                                       used to avoid repeats
        # Correct-answer streaks per side, for streak bonuses (3+ in a row)
        self.streaks = {"p1": 0, "opp": 0}

    # -- which turns happen this round, given the mode -----------------------

    def _turn_order(self) -> list[str]:
        """Solo = just the human. Mirror/player = human then opponent."""
        return ["p1"] if self.mode == "solo" else ["p1", "opp"]

    # -- difficulty ladder ---------------------------------------------------

    def _bump_difficulty_up(self) -> None:
        i = LEVELS.index(self.difficulty)
        self.difficulty = LEVELS[min(i + 1, len(LEVELS) - 1)]

    def _ease_difficulty_down(self) -> None:
        i = LEVELS.index(self.difficulty)
        self.difficulty = LEVELS[max(i - 1, 0)]

    # -- round / turn control ------------------------------------------------

    def begin_round(self) -> None:
        """Start a new round. Sets the active side to the first turn (p1)."""
        if self.state != RoundState.AWAITING_QUESTION:
            raise GameStateError(
                f"Can't begin a round now (state is {self.state.value})."
            )
        if self.round_number >= self.max_rounds:
            raise GameStateError("All rounds are complete.")
        self.round_number += 1
        self.active_side = self._turn_order()[0]

    def load_question(self, question_data: dict) -> CurrentQuestion:
        """
        Load a question (produced by question_gen) for the ACTIVE side and move
        to AWAITING_ANSWER. main.py calls this once per turn.
        """
        if self.state != RoundState.AWAITING_QUESTION:
            raise GameStateError(
                f"Not waiting for a question (state is {self.state.value})."
            )
        self.current_question = CurrentQuestion(
            question=question_data["question"],
            category=question_data.get("category", "uncategorised"),
            answer_example=question_data.get("answer_example", ""),
            difficulty=question_data.get("difficulty", self.difficulty),
            for_side=self.active_side,
        )
        # Remember this question so future ones in this game don't repeat it
        self.asked_questions.append(self.current_question.question)
        self.state = RoundState.AWAITING_ANSWER
        return self.current_question

    def submit_answer(self, player_answer: str, time_taken: float,
                      was_correct: bool, base_score: int,
                      bonus_score: int = 0) -> dict:
        """
        Record the active side's answer + the judge's verdict. Updates score,
        logs to that side's tracker, advances to the next turn or completes the
        round. Returns a summary of this turn.
        """
        if self.state != RoundState.AWAITING_ANSWER:
            raise GameStateError(
                f"No question is awaiting an answer (state is {self.state.value})."
            )
        if self.current_question is None:
            raise GameStateError("Internal error: no current question.")

        side = self.active_side
        points = (base_score + bonus_score) if was_correct else 0

        # --- Streak bonus -------------------------------------------------
        # Award a bonus each time a side COMPLETES a run of 3 correct in a row -
        # i.e. on the 3rd, 6th, 9th, ... consecutive correct answer, but NOT on
        # the answers in between (4th, 5th, 7th, 8th, ...). A wrong answer resets
        # the streak, so the count starts over. Bonus scales with the answered
        # question's difficulty.
        streak_bonus = 0
        streak_hit = False
        if was_correct:
            self.streaks[side] += 1
            if self.streaks[side] % STREAK_THRESHOLD == 0:
                diff = self.current_question.difficulty or self.difficulty
                streak_bonus = STREAK_BONUS_BY_DIFFICULTY.get(diff, 5)
                points += streak_bonus
                streak_hit = True
        else:
            self.streaks[side] = 0

        self.scores[side] += points

        self.trackers[side].log_round(
            round_number=self.round_number,
            challenge_category=self.current_question.category,
            player_answer=player_answer,
            time_taken=time_taken,
            was_correct=was_correct,
        )

        turn_result = {
            "round_number": self.round_number,
            "side": side,
            "question": self.current_question.question,
            "category": self.current_question.category,
            "answer_example": self.current_question.answer_example,
            "player_answer": player_answer,
            "time_taken": time_taken,
            "was_correct": was_correct,
            "points_awarded": points,
            "streak": self.streaks[side],      # current correct-in-a-row count
            "streak_bonus": streak_bonus,      # bonus points from the streak (0 if none)
            "streak_hit": streak_hit,          # True if a streak bonus fired this turn
            "difficulty": self.current_question.difficulty,
            "scores": dict(self.scores),
        }
        self.history.append(turn_result)

        # Difficulty adapts to the HUMAN player's performance (p1) only, and
        # ONLY when the player started on Hard or Advanced. If they chose Easy
        # or Medium, the level is LOCKED for the whole match - every round in
        # every mode stays at the chosen difficulty, no laddering.
        if side == "p1" and self.start_difficulty in ("hard", "advanced"):
            if was_correct:
                self._bump_difficulty_up()
            else:
                self._ease_difficulty_down()

        # Advance: is there another turn this round, or is the round done?
        order = self._turn_order()
        idx = order.index(side)
        if idx + 1 < len(order):
            self.active_side = order[idx + 1]
            self.state = RoundState.AWAITING_QUESTION   # next turn needs a question
            turn_result["next"] = "turn"
        else:
            self.state = RoundState.ROUND_COMPLETE
            turn_result["next"] = "round_complete"

        return turn_result

    def next_round(self) -> None:
        """Return to AWAITING_QUESTION for the next round, active side reset."""
        if self.state != RoundState.ROUND_COMPLETE:
            raise GameStateError(
                f"Round isn't complete yet (state is {self.state.value})."
            )
        self.current_question = None
        self.active_side = self._turn_order()[0]   # back to the first turn
        self.state = RoundState.AWAITING_QUESTION

    # -- queries -------------------------------------------------------------

    def is_over(self) -> bool:
        """True when the round limit is reached (never true in solo)."""
        return self.round_number >= self.max_rounds and \
            self.state == RoundState.ROUND_COMPLETE

    def difficulty_for(self, side: str) -> str:
        """
        The difficulty a given side's NEXT question should use.

        Only the human player (p1) has an adapting difficulty (self.difficulty),
        and only when they started on Hard/Advanced. Everyone else - the Mirror
        in vs-Mirror mode, or player 2 in vs-Player mode - always plays at the
        level the match was created with (self.start_difficulty). This keeps the
        opponent's challenge fixed and independent of how p1 is doing.
        """
        return self.difficulty if side == "p1" else self.start_difficulty

    def summary_for(self, side: str) -> str:
        """The plain-English profile for a side, fed to question_gen."""
        return self.trackers.get(side, self.trackers["p1"]).get_summary()

    def winner(self) -> str:
        """'p1', 'opp', or 'draw' (meaningful for mirror/player modes)."""
        if self.scores["p1"] > self.scores["opp"]:
            return "p1"
        if self.scores["opp"] > self.scores["p1"]:
            return "opp"
        return "draw"

    def snapshot(self) -> dict:
        """A full picture of the game right now - for the API."""
        return {
            "topic": self.topic,
            "mode": self.mode,
            "language": self.language,
            "difficulty": self.difficulty,
            "round_number": self.round_number,
            "max_rounds": None if self.max_rounds == float("inf") else self.max_rounds,
            "active_side": self.active_side,
            "scores": dict(self.scores),
            "state": self.state.value,
            "current_question": (
                self.current_question.__dict__ if self.current_question else None
            ),
            "is_over": self.is_over(),
        }


class GameStateError(Exception):
    """Raised when an action is attempted in the wrong round state."""


# --- manual test: play a fake 2-round vs-Mirror match, no model ------------
if __name__ == "__main__":
    g = Game(topic="volcanoes", mode="mirror", start_difficulty="easy", max_rounds=2)

    for _ in range(2):
        g.begin_round()
        # p1 turn
        g.load_question({"question": "Q for player", "category": "association",
                         "answer_example": "lava", "difficulty": g.difficulty})
        r = g.submit_answer("magma", 6.0, True, 10, 5)
        print(f"R{r['round_number']} p1 -> +{r['points_awarded']} (next: {r['next']})")
        # opp (Mirror) turn
        g.load_question({"question": "Q for mirror", "category": "association",
                         "answer_example": "ash", "difficulty": g.difficulty})
        r = g.submit_answer("not sure", 1.0, False, 0, 0)
        print(f"R{r['round_number']} opp -> +{r['points_awarded']} (next: {r['next']})")
        if not g.is_over():
            g.next_round()

    print("scores:", g.scores, "| winner:", g.winner(), "| over:", g.is_over())
