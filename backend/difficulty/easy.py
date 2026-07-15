"""
difficulty/easy.py
------------------
A difficulty level is just three pieces of information:

  DIFFICULTY_LABEL : the human-readable name, shown in the UI and given to the LLM.
  BENCHMARK        : a plain-English instruction telling the LLM HOW HARD to make
                     the question. This is the key idea Tim asked for - we don't
                     leave difficulty to the model's guess, we calibrate it with a
                     concrete "answerable by N out of 10 people" benchmark.
  TIME_LIMIT       : how many seconds the player gets, ENFORCED BY THE FRONTEND
                     (never the backend - the frontend owns all timing).

question_gen.py imports one of these modules and injects BENCHMARK straight
into the prompt it sends the LLM.
"""

DIFFICULTY_LABEL = "Easy"
BENCHMARK = (
    "This question should be answerable by roughly 8 out of 10 people. "
    "Keep it accessible."
)
TIME_LIMIT = 30  # seconds, enforced by frontend
