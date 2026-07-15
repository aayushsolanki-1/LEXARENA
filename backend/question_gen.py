"""
question_gen.py
---------------
THE QUESTION MASTER. Generates ONE fresh question for ONE player, for one round.

This is called once per player per round (so in a 2-player round it runs twice,
producing two DIFFERENT questions - players never share a question).

What it receives:
  topic            - the player's chosen subject (e.g. "volcanoes")
  difficulty       - one of: easy / medium / hard / advanced
  tracker_summary  - plain-English profile of how the player has been doing,
                     produced by tracker.py (never raw numbers)
  for_player       - a label of who this question is for: "human" / "mirror" /
                     "player2". Used only to vary phrasing slightly; the question
                     is always about the same topic.

What it returns (always this exact JSON shape):
  {
    "question":   "<the question text shown to the player>",
    "category":   "<short label for the KIND of question, e.g. association,
                    double-meaning, obscure, precision>",
    "answer_example": "<one example answer the master would accept>",
    "difficulty": "<easy|medium|hard|advanced>"
  }

KEY IDEA (Tim's benchmark system): we don't let the model guess how hard
"medium" is. We inject the difficulty file's BENCHMARK ("answerable by 5/10
people...") straight into the prompt, so the model calibrates precisely.

ROBUSTNESS: call the model, try to parse JSON, retry once, then fall back to a
safe question so the game never crashes. Each new module carries its own parsing
(no shared helper), as agreed.

Needs: pip install httpx
"""

import json
import httpx

import config
from difficulty import get_difficulty


def generate_question(
    topic: str,
    difficulty: str,
    tracker_summary: str,
    for_player: str = "human",
    asked_questions: list[str] | None = None,
    language: str = "en",
) -> dict:
    """Generate one question. Always returns the JSON shape documented above."""
    level = get_difficulty(difficulty)   # the difficulty module (easy/medium/...)

    # Which language the question text should be written in.
    lang_name = {"de": "German", "en": "English"}.get(language, "English")
    lang_instruction = (
        f"Write the question, category, and example answer in {lang_name}."
    )

    system = (
        "You are THE MIRROR, the question master of a word-duel game. "
        "You invent short, fair language questions about a given topic, calibrated "
        "to an exact difficulty benchmark, and adapted to how the player has been "
        "performing. You ALWAYS reply with a single JSON object and nothing else."
    )

    # Build a "don't repeat these" block from questions already asked this game.
    avoid_block = ""
    if asked_questions:
        # Keep the prompt manageable: show the most recent ones (up to 20).
        recent = asked_questions[-20:]
        listed = "\n".join(f"- {q}" for q in recent)
        avoid_block = (
            "\n\nQuestions ALREADY ASKED this game (do NOT repeat any of these, "
            "and avoid asking for the same answer in different words):\n"
            f"{listed}\n"
        )

    user = f"""Topic: {topic}
Difficulty: {level.DIFFICULTY_LABEL}
Difficulty benchmark: {level.BENCHMARK}

What you know about this player so far:
{tracker_summary}{avoid_block}

Write ONE question about the topic "{topic}".
- Calibrate its hardness to the benchmark above.
- Lean toward the kinds of question the player has been weak on, but keep it fair.
- The question must be answerable with a short free-text answer (a word or phrase).
- It must be DIFFERENT from every already-asked question above, and must not
  have the same answer as one of them.
- {lang_instruction}

Reply with ONLY this JSON (no markdown, no extra text):
{{
  "question": "<the question text>",
  "category": "<short kind label, e.g. association, double-meaning, obscure, precision>",
  "answer_example": "<one example answer you would accept>",
  "difficulty": "{difficulty}"
}}"""

    # Safe fallback so a model hiccup never crashes a round (localized).
    if language == "de":
        fallback = {
            "question": f"Nenne ein einzelnes Wort, das stark mit {topic} verbunden ist.",
            "category": "Assoziation",
            "answer_example": (topic.split()[0] if topic else "Wort"),
            "difficulty": difficulty,
        }
    else:
        fallback = {
            "question": f"Name a single word strongly associated with {topic}.",
            "category": "association",
            "answer_example": (topic.split()[0] if topic else "word"),
            "difficulty": difficulty,
        }
    required = ["question", "category", "answer_example", "difficulty"]

    # --- call + parse, retry once, then fall back -------------------------
    for attempt in (1, 2):
        try:
            raw = _post_to_model(system, user)
        except Exception as e:
            print(f"[question_gen] WARNING: request failed (attempt {attempt}): {e}")
            continue
        parsed = _extract_json(raw)
        if parsed is not None and all(k in parsed for k in required):
            # make sure difficulty echoes what we asked, even if model omitted it
            parsed["difficulty"] = parsed.get("difficulty") or difficulty
            return parsed
        print(f"[question_gen] WARNING: bad JSON (attempt {attempt}). Raw:\n{raw}\n")

    print("[question_gen] NOTICE: using fallback question so the game continues.")
    return fallback


# --- internals (self-contained, not shared) -------------------------------

def _post_to_model(system: str, user: str) -> str:
    """POST a chat request to the cluster and return the raw reply text."""
    payload = {
        "model": config.MODEL_NAME,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "temperature": config.TEMPERATURE,
        # Turn OFF Qwen's "thinking out loud" so replies are fast (this model
        # otherwise writes long internal monologues before answering).
        "chat_template_kwargs": {"enable_thinking": False},
        # Hard cap so a reply can never run away. A question is short.
        "max_tokens": 220,
    }
    with httpx.Client(timeout=config.REQUEST_TIMEOUT) as client:
        resp = client.post(config.LLM_URL, json=payload)
        resp.raise_for_status()
        data = resp.json()
    return data["choices"][0]["message"]["content"]


def _extract_json(text: str) -> dict | None:
    """
    Pull a JSON object out of the model's reply. Handles clean JSON, ```json
    fenced blocks, and JSON buried in surrounding chatter. Returns the dict or
    None if nothing parseable is found.
    """
    if not text:
        return None
    cleaned = text.strip()
    if "```" in cleaned:
        for part in cleaned.split("```"):
            p = part.strip()
            if p.startswith("json"):
                p = p[4:].strip()
            if p.startswith("{"):
                cleaned = p
                break
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass
    start, end = cleaned.find("{"), cleaned.rfind("}")
    if start != -1 and end != -1 and end > start:
        try:
            return json.loads(cleaned[start:end + 1])
        except json.JSONDecodeError:
            return None
    return None


# --- manual test -----------------------------------------------------------
if __name__ == "__main__":
    q = generate_question(
        topic="volcanoes",
        difficulty="medium",
        tracker_summary="No rounds played yet. This is the player's first challenge.",
        for_player="human",
    )
    print(json.dumps(q, indent=2))
