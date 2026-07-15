# Lexarena

![Lexarena](./lexarena.png)

> **Summaery Exhibition · PlayAI SS26 · Bauhaus-Universität Weimar**

**Student:** Aayush Solanki (`vola6357`)
**Instructor:** Prof. Tim Gollub

Lexarena is a word duel against an AI that makes up the rules as it goes. You choose a topic — anything from football to philosophy — and face **The Mirror**, an opponent powered by a large language model. Every round it invents a fresh language challenge, judges your free-text answer with reasoning, and quietly learns how you think. The better you play, the harder it pushes; slip twice, and it starts using your own habits against you. No question bank, no fixed answers, no two games alike. Play solo, duel the AI across seven rounds, or go head-to-head with a friend while The Mirror referees.

---

## Game Modes

**Solo** — You vs The Mirror. Difficulty climbs as you perform well. No round limit; end the run whenever you like.

**vs Mirror** — Seven rounds. You and The Mirror both answer questions each round (different questions — no shared hints). Whoever scores more points wins.

**vs Player** — Seven rounds. Two humans take turns answering. The LLM acts as a neutral game master, no Mirror persona.

---

## Difficulty Levels

Four levels: **Easy**, **Medium**, **Hard**, and **Advanced**. Each is calibrated by a benchmark given directly to the LLM — Easy means roughly 8 out of 10 people could answer it; Advanced means only experts can. In Hard and Advanced, the human player ladders up on strong streaks while The Mirror stays fixed at the starting difficulty.

The game is fully bilingual — the interface, questions, verdicts, and The Mirror's answers all switch between **English and German** with one toggle.

---

## How It's Built

```
vola6357/
├── backend/          FastAPI server (port 8001)
│   ├── main.py             API endpoints
│   ├── game.py             Game state, rounds, scoring
│   ├── config.py           One place for all environment settings
│   ├── question_gen.py     LLM: generates each challenge
│   ├── answer_judge.py     LLM: judges free-text answers with reasoning
│   ├── mirror_answer.py    LLM: The Mirror answers its own questions
│   ├── tracker.py          Behaviour profile (pure Python, no LLM)
│   ├── leaderboard.py      Per-mode, per-difficulty high scores
│   └── difficulty/         Benchmark prompts: easy / medium / hard / advanced
└── frontend/
    └── Pop_Lexarena.html   The whole game UI — one standalone file
```

The core design rule: **Python does all the counting; the LLM never sees raw numbers.** The tracker records performance across rounds and hands the model a plain-English summary ("the player has answered the last three geography questions correctly, but hesitates on dates"). The LLM sticks to what it's actually good at: generating novel challenges, judging open-ended answers with context, and playing The Mirror's voice.

The LLM is **Qwen3.6-35B** (AWQ 4-bit), an open-weight model by Alibaba, self-hosted on the Bauhaus-Universität Weimar compute cluster via vLLM. All player data stays within Bauhaus infrastructure.

---

## Running It Yourself

You need: Python 3, the Webis VPN, and cluster access.

**1. Start the model on the cluster**

```bash
ssh <you>@ssh.webis.de
ssh gammaweb
cd <your clone of this repo>
sbatch vllm.sbatch
```

Wait for the job to start (`squeue`), then open the job log (`cat playai-<jobid>.log`) and note two things: the node's **real IP** (the `distributed_init_method=tcp://<IP>:...` line — e.g. `141.54.x.x`, *not* `172.17.0.1`) and the **port**.

**2. Point the backend at the model**

Connect to the **Webis VPN**, then edit one line in `backend/config.py`:

```python
LLM_URL = "http://<node-ip>:<port>/v1/chat/completions"
```

(or set it as an environment variable — every setting in `config.py` can be overridden that way.)

**3. Start the backend**

```bash
cd backend
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
uvicorn main:app --port 8001
```

**4. Start the frontend**

```bash
cd frontend
python3 -m http.server 8080
```

Open **http://localhost:8080/Pop_Lexarena.html** in your browser.

> ⚠️ Do **not** open the HTML file by double-clicking it. Safari blocks the Fullscreen API on `file://` pages, which breaks fullscreen and typing. Always serve it over `http://localhost:8080`.

To stop everything: `Ctrl+C` both servers, then `scancel <jobid>` on the cluster.

---

## Why LLMs Are Essential

Every challenge is generated live within the player's chosen topic — no pre-written bank, no templates. Answers are free text, judged by the LLM with contextual reasoning. The Mirror's difficulty adaptation and taunts are driven by the model reading a plain-English profile of how the player has been performing. None of this is replicable with fixed logic.

---

## Connection to Related Work

| Paper | Connection |
|---|---|
| **Generative Agents** (Park et al., 2023) | The Mirror builds a behavioural profile of the player across rounds — analogous to the memory streams in generative agents that shape future behaviour. |
| **GameGPT** (2023) | Game logic is split into specialised roles (question generation, answer judging, Mirror answering, difficulty calibration) rather than one monolithic prompt, reflecting GameGPT's multi-role decomposition principle. |
| **Voyager** (Wang et al., 2023) | The iterative difficulty ladder — player improves, Mirror pushes harder — mirrors Voyager's curriculum of increasingly complex tasks driven by agent performance. |
| **Game Generation via LLMs** (2024) | The LLM is the active generator of game content each round, not a passive NPC, consistent with the paper's framing of LLMs as generative game engines. |
| **Unbounded** (2024) | The home turf mechanic — player-defined domain, infinite variation within it — echoes Unbounded's generative infinite game principle: the challenge space expands from player input rather than a fixed content library. |

---

## After the Exhibition

Lexarena was shown at the Summaery open lab night, where visitors played all three modes and filled the leaderboards. Two things surfaced from watching people play:

- **Question paraphrasing** — over long sessions the model sometimes rewords an earlier question just enough to slip past verbatim de-duplication while asking the same underlying concept. A concept-level dedup (comparing what a question *tests*, not how it's worded) is the planned fix.
- **Serving over `http://`** — Safari's silent blocking of fullscreen on `file://` pages was discovered mid-setup and is now baked into the run instructions above.
