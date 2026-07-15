"""
config.py
---------
All the settings that depend on YOUR environment live here, in one place.
When something about your setup changes - which node the cluster job landed on,
which port it serves on, which model vllm.sbatch loaded - you change it HERE and
nowhere else. No hunting through code.

HOW YOU REACH THE MODEL (no SSH tunnel needed):
The model runs on the cluster (gammaweb) and serves an OpenAI-compatible
chat-completions API. Because it binds to 0.0.0.0, it is reachable directly
from your laptop AS LONG AS YOU ARE ON THE WEBIS VPN. So you just point
LLM_URL straight at the node's real address - no tunnelling.

    your code  ->  (Webis VPN)  ->  http://<node-ip>:<port>/v1/chat/completions

IMPORTANT - the address changes every session:
When you run `sbatch vllm.sbatch`, the job lands on some node (e.g. gammaweb07)
with some real IP. Find that IP and port from the job log:
    cat playai-<jobid>.log
Look for the node's real IP (the `distributed_init_method=tcp://<IP>:...` line)
and the Port line. Then update LLM_URL below. The cluster-internal 172.17.0.1
address does NOT work from your laptop - use the real IP (e.g. 141.54.x.x).

Each setting can also be overridden by an environment variable of the same
name, so you can change them without editing this file at all if you prefer.
"""

import os


# --- The model endpoint (what the LLM modules call) -----------------------

# The FULL URL your backend POSTs to. This is the node's real IP + port, with
# /v1/chat/completions on the end. UPDATE THE IP AND PORT each session to match
# what your current vllm.sbatch job is serving (see the notes at the top).
#
# You must be connected to the Webis VPN for this address to be reachable.
LLM_URL = os.getenv(
    "LLM_URL",
    "http://141.54.132.236:8004/v1/chat/completions",
)

# The model name, EXACTLY as the cluster serves it. This must match the MODEL
# line in vllm.sbatch. Right now that is the AWQ 4-bit build below.
MODEL_NAME = os.getenv("MODEL_NAME", "cyankiwi/Qwen3.6-35B-A3B-AWQ-4bit")


# --- Model call tuning -----------------------------------------------------

# How long to wait for the model before giving up (seconds). This Qwen model
# "thinks out loud" before answering, which can make the first calls slow, so
# we give it generous headroom.
REQUEST_TIMEOUT = float(os.getenv("REQUEST_TIMEOUT", "90"))

# Creativity. Higher = more varied/surprising challenges; lower = safer.
TEMPERATURE = float(os.getenv("TEMPERATURE", "0.8"))


# --- Backend server --------------------------------------------------------

# The port YOUR FastAPI backend runs on. Run the server with:
#     uvicorn main:app --reload --port 8001
BACKEND_PORT = int(os.getenv("BACKEND_PORT", "8001"))


# --- Game rules ------------------------------------------------------------

MAX_ROUNDS = int(os.getenv("MAX_ROUNDS", "7"))


# --- The Mirror as a player (Mode 2) --------------------------------------
# In "vs Mirror" mode the Mirror ANSWERS its own questions. If it used the full
# model it would always win, so we deliberately weaken it. Two ways:
#
#   "prompt"  (default) - same Qwen model, but mirror_answer.py gives it a
#                         handicapping prompt ("answer fast, don't overthink,
#                         you sometimes slip, especially on hard questions").
#                         This is what the shared cluster supports today.
#
#   "model"            - point the Mirror-as-player at a SEPARATE, smaller model
#                         (set MIRROR_MODEL_NAME + MIRROR_LLM_URL below). Only
#                         use this if the cluster actually serves a second model.
#
# Switching is one setting - no code changes elsewhere.
MIRROR_MODE = os.getenv("MIRROR_MODE", "prompt")   # "prompt" or "model"

# Only used when MIRROR_MODE == "model":
MIRROR_MODEL_NAME = os.getenv("MIRROR_MODEL_NAME", MODEL_NAME)
MIRROR_LLM_URL = os.getenv("MIRROR_LLM_URL", LLM_URL)

# The Mirror-as-player's creativity. A touch higher = looser, more fallible.
MIRROR_TEMPERATURE = float(os.getenv("MIRROR_TEMPERATURE", "0.9"))