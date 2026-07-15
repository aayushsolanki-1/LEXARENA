"""
mirror_answer.py
----------------
THE MIRROR AS A PLAYER (Mode 2 only). Produces the Mirror's OWN answer to a
question, so it can be judged like a human's answer and score points.

Why this file exists at all: if the same capable model both asked the questions
AND answered them, the Mirror would never lose - no fun. So the Mirror-as-player
is DELIBERATELY WEAKER than the question master and judge. (Think of it as a
strong model writing/judging the quiz, and a weaker contestant taking it.)

Two ways to make it weaker, chosen in config.py via MIRROR_MODE:

  "prompt" (default) - same Qwen model, but we give it a HANDICAPPING prompt:
                       answer fast and instinctively, don't research, and you
                       genuinely sometimes get it wrong - more often on harder
                       questions. This is what the shared cluster supports.

  "model"            - call a SEPARATE smaller model (config.MIRROR_MODEL_NAME /
                       config.MIRROR_LLM_URL). Only if the cluster serves one.

Either way this file returns just the Mirror's answer STRING. It does NOT judge
itself - answer_judge.py does that next, exactly as it would for a human. That
keeps judging fair and identical for both sides.

What it receives:
  topic       - the subject
  question    - the question to answer
  difficulty  - easy/medium/hard/advanced (the Mirror plays worse on harder ones)

What it returns:
  a single string: the Mirror's answer.

ROBUSTNESS: call, retry once, then fall back to a vague answer (which the judge
will likely reject - acceptable, it just means the Mirror loses that round).

Needs: pip install httpx
"""

import httpx

import config


# How hard the Mirror "tries", by difficulty. Lower = more likely to whiff.
# Expressed to the model in words, not numbers (the model reads instructions,
# not probabilities). Harder questions => more permission to fail.
_EFFORT_BY_DIFFICULTY = {
    "easy": "You usually get easy questions right. Answer confidently.",
    "medium": "You get medium questions right about half the time. "
              "Don't overthink; sometimes your quick answer is wrong.",
    "hard": "Hard questions often beat you. Give your best quick guess, "
            "but you will frequently be wrong or imprecise.",
    "advanced": "Expert questions usually defeat you. Make a plausible guess, "
                "but you are very likely to be wrong.",
}


def mirror_answer(topic: str, question: str, difficulty: str = "medium",
                  language: str = "en") -> str:
    """Return the Mirror's answer string for a question. Never raises."""
    effort = _EFFORT_BY_DIFFICULTY.get(
        (difficulty or "medium").lower(),
        _EFFORT_BY_DIFFICULTY["medium"],
    )
    lang_name = {"de": "German", "en": "English"}.get(language, "English")

    system = (
        "You are THE MIRROR, playing as a CONTESTANT in a word-duel game. "
        "You are a fast, instinctive player - NOT an expert. You answer quickly "
        "with the first good word that comes to mind. You do not deliberate, "
        "look things up, or second-guess. You ALWAYS reply with ONLY your answer "
        "- a single word or short phrase, no explanation, no punctuation, no quotes."
    )
    user = f"""Topic: {topic}
Question: {question}

{effort}

Answer in {lang_name}.
Give your answer now - just the word or short phrase, nothing else."""

    # Which endpoint/model to use depends on the config switch.
    if config.MIRROR_MODE == "model":
        url, model = config.MIRROR_LLM_URL, config.MIRROR_MODEL_NAME
    else:  # "prompt"
        url, model = config.LLM_URL, config.MODEL_NAME

    for attempt in (1, 2):
        try:
            raw = _post_to_model(url, model, system, user)
        except Exception as e:
            print(f"[mirror_answer] WARNING: request failed (attempt {attempt}): {e}")
            continue
        answer = _clean_answer(raw)
        if answer:
            return answer
        print(f"[mirror_answer] WARNING: empty/odd reply (attempt {attempt}).")

    print("[mirror_answer] NOTICE: using fallback answer (Mirror likely loses this round).")
    return "not sure"


# --- internals (self-contained) -------------------------------------------

def _post_to_model(url: str, model: str, system: str, user: str) -> str:
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "temperature": config.MIRROR_TEMPERATURE,
        # Turn OFF thinking - the Mirror should answer fast and instinctively
        # anyway, so no internal monologue. This also keeps it quick.
        "chat_template_kwargs": {"enable_thinking": False},
        # The Mirror replies with just a word or short phrase.
        "max_tokens": 60,
    }
    with httpx.Client(timeout=config.REQUEST_TIMEOUT) as client:
        resp = client.post(url, json=payload)
        resp.raise_for_status()
        data = resp.json()
    return data["choices"][0]["message"]["content"]


def _clean_answer(text: str) -> str:
    """
    The Mirror should reply with just an answer, but models sometimes wrap it in
    quotes or add a stray line. Take the first non-empty line and strip quotes.
    """
    if not text:
        return ""
    first = text.strip().splitlines()[0].strip()
    return first.strip(' "\'.')


# --- manual test -----------------------------------------------------------
if __name__ == "__main__":
    ans = mirror_answer(
        topic="volcanoes",
        question="Name a single word strongly associated with volcanoes.",
        difficulty="medium",
    )
    print("Mirror answered:", repr(ans))
