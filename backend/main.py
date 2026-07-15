"""
main.py
-------
The FastAPI server - the layer the frontend talks to over HTTP. It contains NO
game rules (game.py) and NO model logic (question_gen / answer_judge /
mirror_answer). Its job: receive requests, call the right pieces, return JSON.

It supports all three modes through a small set of endpoints. The frontend
drives the round flow turn by turn:

  POST /game/new        {topic, mode, difficulty}      -> start a match
  POST /game/question                                   -> get a question for the
                                                           ACTIVE side (the server
                                                           knows whose turn it is)
  POST /game/answer     {player_answer, time_taken}     -> judge the active side's
                                                           answer, score it
  POST /game/mirror-turn                                -> (mode "mirror" only)
                                                           the Mirror answers its
                                                           own question and is judged
  POST /game/next                                        -> advance to next round
  GET  /game/state                                       -> full snapshot

Typical loops:
  solo:    new -> [question -> answer -> next] repeat
  mirror:  new -> question(p1) -> answer(p1) -> question(opp) -> mirror-turn -> next
  player:  new -> question(p1) -> answer(p1) -> question(p2) -> answer(p2) -> next

Run it (keep off the tunnel's port):
  uvicorn main:app --reload --port 8001
Try it by hand at http://127.0.0.1:8001/docs
"""

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

import config
import question_gen
import answer_judge
import mirror_answer
import leaderboard
from game import Game, GameStateError


app = FastAPI(title="Lexarena Backend")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],      # TODO: restrict to the frontend URL before deploy
    allow_methods=["*"],
    allow_headers=["*"],
)

# One match in memory - single active session, as agreed.
game = Game()


# ===========================================================================
# Request bodies
# ===========================================================================

class NewGameRequest(BaseModel):
    topic: str
    mode: str = "solo"            # "solo" | "mirror" | "player"
    difficulty: str = "easy"      # starting difficulty
    language: str = "en"          # "en" | "de" - questions/verdicts language


class AnswerRequest(BaseModel):
    player_answer: str
    time_taken: float             # seconds, measured by the frontend


class LeaderboardRequest(BaseModel):
    name: str
    mode: str = "solo"            # "solo" | "mirror" | "player"
    difficulty: str = "easy"      # starting difficulty the run was played on
    score: int = 0


# ===========================================================================
# Endpoints
# ===========================================================================

@app.post("/game/new")
def new_game(req: NewGameRequest) -> dict:
    """Start a fresh match for the chosen topic, mode, and starting difficulty."""
    global game
    topic = req.topic.strip()
    if not topic:
        raise HTTPException(status_code=400, detail="A topic is required.")
    game = Game(
        topic=topic,
        mode=req.mode,
        start_difficulty=req.difficulty,
        max_rounds=config.MAX_ROUNDS,
        language=req.language,
    )
    return {"message": "New game started.", "state": game.snapshot()}


@app.post("/game/question")
def get_question() -> dict:
    """
    Generate a question for the ACTIVE side. This endpoint is the single driver
    of round flow:
      - brand new game (round 0)  -> begin the first round
      - previous round complete    -> advance and begin the next round
      - mid-round (awaiting next turn) -> just load this turn's question
    """
    try:
        if game.round_number == 0:
            game.begin_round()                      # first round ever
        elif game.state.value == "round_complete":
            game.next_round()                       # reset to first turn
            game.begin_round()                      # start the new round
        # else: mid-round, state is awaiting_question for the next turn -> load

        summary = game.summary_for(game.active_side)
        # Each side gets its OWN difficulty: p1's adapts (Hard/Advanced only),
        # the opponent (Mirror or player 2) stays fixed at the chosen level.
        side_difficulty = game.difficulty_for(game.active_side)
        q = question_gen.generate_question(
            topic=game.topic,
            difficulty=side_difficulty,
            tracker_summary=summary,
            for_player=game.active_side,
            asked_questions=game.asked_questions,
            language=game.language,
        )
        # Make sure the question is LABELLED with the difficulty it was made at,
        # so scoring/streak-bonus and the on-screen tag match this side's level
        # rather than defaulting to p1's current difficulty.
        if isinstance(q, dict):
            q["difficulty"] = side_difficulty
        loaded = game.load_question(q)
    except GameStateError as e:
        raise HTTPException(status_code=409, detail=str(e))

    return {
        "round_number": game.round_number,
        "active_side": game.active_side,
        "topic": game.topic,
        "question": loaded.question,
        "category": loaded.category,
        "difficulty": loaded.difficulty,
    }


@app.post("/game/answer")
def submit_answer(req: AnswerRequest) -> dict:
    """Judge the ACTIVE side's answer, score it, and report what happens next."""
    if game.current_question is None:
        raise HTTPException(status_code=409, detail="No active question to answer.")

    verdict = answer_judge.judge_answer(
        topic=game.topic,
        question=game.current_question.question,
        player_answer=req.player_answer,
        language=game.language,
    )
    try:
        result = game.submit_answer(
            player_answer=req.player_answer,
            time_taken=req.time_taken,
            was_correct=verdict["valid"],
            base_score=verdict["base_score"],
            bonus_score=verdict["bonus_score"],
        )
    except GameStateError as e:
        raise HTTPException(status_code=409, detail=str(e))

    return {
        **result,
        "reasoning": verdict["reasoning"],
        "answer_example": verdict.get("answer_example", result.get("answer_example", "")),
        "next_difficulty": game.difficulty,
        "is_over": game.is_over(),
    }


@app.post("/game/mirror-turn")
def mirror_turn() -> dict:
    """
    Mode "mirror" only: the Mirror answers ITS own current question, then that
    answer is judged exactly like a human's. Call this instead of /game/answer
    when active_side is 'opp' in vs-Mirror mode.
    """
    if game.mode != "mirror":
        raise HTTPException(status_code=400, detail="Mirror turns only exist in 'mirror' mode.")
    if game.current_question is None:
        raise HTTPException(status_code=409, detail="No active question for the Mirror.")

    # The deliberately-weaker Mirror produces an answer.
    answer = mirror_answer.mirror_answer(
        topic=game.topic,
        question=game.current_question.question,
        difficulty=game.current_question.difficulty,
        language=game.language,
    )
    # Judged by the SAME fair judge as the human.
    verdict = answer_judge.judge_answer(
        topic=game.topic,
        question=game.current_question.question,
        player_answer=answer,
        language=game.language,
    )
    try:
        result = game.submit_answer(
            player_answer=answer,
            time_taken=0.0,           # the Mirror isn't timed
            was_correct=verdict["valid"],
            base_score=verdict["base_score"],
            bonus_score=verdict["bonus_score"],
        )
    except GameStateError as e:
        raise HTTPException(status_code=409, detail=str(e))

    return {
        **result,
        "mirror_answer": answer,
        "reasoning": verdict["reasoning"],
        "is_over": game.is_over(),
    }


@app.post("/game/next")
def next_round() -> dict:
    """
    Acknowledge readiness for the next round. The actual advancement happens in
    /game/question (the single round-flow driver), so this just returns the
    current snapshot. Kept for frontends that prefer an explicit call.
    """
    return {"state": game.snapshot()}


@app.get("/game/state")
def game_state() -> dict:
    """Full snapshot: mode, topic, difficulty, round, scores, state."""
    return game.snapshot()


@app.post("/leaderboard")
def leaderboard_submit(req: LeaderboardRequest) -> dict:
    """
    Record one finished run on the per-(mode,difficulty) board and report its
    placement. Called automatically by the frontend on the recap screen.
    """
    result = leaderboard.submit(
        name=req.name, mode=req.mode, difficulty=req.difficulty, score=req.score
    )
    return result


@app.get("/leaderboard")
def leaderboard_get(mode: str = "", difficulty: str = "", n: int = leaderboard.TOP_N) -> dict:
    """
    Top-n rows. With ?mode=solo&difficulty=easy returns that one board;
    with no params, returns every board at once.
    """
    n = max(1, min(int(n), leaderboard.TOP_N))
    if mode in leaderboard.VALID_MODES and difficulty in leaderboard.VALID_DIFFS:
        return {"mode": mode, "difficulty": difficulty,
                "top": leaderboard.top(mode, difficulty, n)}
    return {"boards": leaderboard.all_top(n)}


@app.get("/")
def root() -> dict:
    return {"message": "Lexarena backend is running. See /docs to try it out."}
