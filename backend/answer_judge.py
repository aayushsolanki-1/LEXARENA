"""
answer_judge.py
---------------
THE JUDGE. Evaluates ONE answer to ONE question and returns a verdict.

Called once per answer - for the human's answer, the Mirror's answer, or
player 2's answer. It does not care who produced the answer; it only judges
whether the answer fits the question.

What it receives:
  topic          - the subject (gives the judge context)
  question       - the question that was asked
  player_answer  - the free-text answer to judge

What it returns (always this exact JSON shape):
  {
    "valid": true/false,
    "reasoning": "<one short sentence, addressed to the answerer>",
    "base_score": 10 or 0,
    "bonus_score": 0-5,
    "answer_example": "<a valid answer, shown when the player got it wrong>"
  }

Scoring: base 10 for a valid answer, 0 if invalid. An optional 0-5 bonus is
added ONLY for an especially clever / precise / elegant valid answer.

This is one of the "smart" roles - the judge stays sharp and fair. (The Mirror
as a *player* is the deliberately weaker role; that lives in mirror_answer.py.)

ROBUSTNESS: call, parse, retry once, then fall back. On fallback we are lenient
(accept a non-empty answer) so a model hiccup never wrongly penalises a player.

Needs: pip install httpx
"""

import json
import httpx

import config


def judge_answer(topic: str, question: str, player_answer: str,
                 language: str = "en") -> dict:
    """Judge one answer. Always returns the JSON shape documented above."""
    answer = (player_answer or "").strip()

    # Language the reasoning + example answer should be written in.
    lang_name = {"de": "German", "en": "English"}.get(language, "English")

    system = (
        "You are THE JUDGE in a word-duel game. You fairly evaluate whether a "
        "player's answer satisfies a question. You have taste: you reward clever, "
        "precise answers, but you are reasonable and accept answers that genuinely "
        "fit even if not the one you expected. You ALWAYS reply with a single JSON "
        "object and nothing else."
    )

    user = f"""Topic: {topic}
Question: {question}
Player's answer: "{answer}"

Decide whether the answer satisfies the question.
- Accept answers that genuinely fit, even if not what you had in mind.
- Reject answers that miss the point, are empty, or don't meet the constraint.

Scoring:
- base_score: 10 if valid, else 0.
- bonus_score: 0 to 5, added ONLY if valid AND the answer is especially clever,
  precise, or elegant. Otherwise 0.
- answer_example: give one answer you WOULD accept (useful to show the player
  when they got it wrong). Always include it.
- Write the "reasoning" and "answer_example" in {lang_name}. Judge the meaning
  of the player's answer fairly even if they wrote it in another language.

Reply with ONLY this JSON (no markdown, no extra text):
{{
  "valid": <true or false>,
  "reasoning": "<one short sentence explaining the verdict, addressed to the answerer>",
  "base_score": <0 or 10>,
  "bonus_score": <0 to 5>,
  "answer_example": "<a valid example answer>"
}}"""

    # Lenient fallback: if we truly can't judge, don't punish a real attempt.
    if language == "de":
        _r_allow = "Ich konnte das nicht ganz bewerten, also lasse ich es gelten."
        _r_none = "Es wurde keine Antwort gegeben."
    else:
        _r_allow = "I couldn't fully evaluate that one, so I'll allow it."
        _r_none = "No answer was given."
    fallback = {
        "valid": bool(answer),
        "reasoning": _r_allow if answer else _r_none,
        "base_score": 10 if answer else 0,
        "bonus_score": 0,
        "answer_example": "",
    }
    required = ["valid", "reasoning", "base_score", "bonus_score"]

    for attempt in (1, 2):
        try:
            raw = _post_to_model(system, user)
        except Exception as e:
            print(f"[answer_judge] WARNING: request failed (attempt {attempt}): {e}")
            continue
        parsed = _extract_json(raw)
        if parsed is not None and all(k in parsed for k in required):
            parsed.setdefault("answer_example", "")
            # guard against an inconsistent reply (valid but 0 base score, etc.)
            if parsed["valid"] and parsed["base_score"] == 0:
                parsed["base_score"] = 10
            if not parsed["valid"]:
                parsed["base_score"] = 0
                parsed["bonus_score"] = 0
            return parsed
        print(f"[answer_judge] WARNING: bad JSON (attempt {attempt}). Raw:\n{raw}\n")

    print("[answer_judge] NOTICE: using fallback judgement so the game continues.")
    return fallback


# --- internals (self-contained) -------------------------------------------

def _post_to_model(system: str, user: str) -> str:
    payload = {
        "model": config.MODEL_NAME,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        # Judging wants consistency more than creativity, so cooler temperature.
        "temperature": 0.3,
        # Turn OFF Qwen's "thinking out loud" so judging is fast.
        "chat_template_kwargs": {"enable_thinking": False},
        # A verdict is short: valid flag + one sentence + an example answer.
        "max_tokens": 220,
    }
    with httpx.Client(timeout=config.REQUEST_TIMEOUT) as client:
        resp = client.post(config.LLM_URL, json=payload)
        resp.raise_for_status()
        data = resp.json()
    return data["choices"][0]["message"]["content"]


def _extract_json(text: str) -> dict | None:
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
    v = judge_answer(
        topic="volcanoes",
        question="Name a single word strongly associated with volcanoes.",
        player_answer="magma",
    )
    print(json.dumps(v, indent=2))
