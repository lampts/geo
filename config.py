"""Central configuration for the Vietnamese-banking AI-visibility pipeline.

Everything tunable lives here: which models answer the prompts, which model
parses sentiment, and which model writes the insights. All keys are read from
environment variables at runtime — nothing secret is stored in the repo.
"""
import os

# ---------------------------------------------------------------------------
# Answer models — the 4 LLMs we ask each prompt (30 prompts x 4 = 120 answers).
# Previous run (baseline, Jun 2026): GPT-5.5, Opus 4.6, Gemini 3.5 Flash, DeepSeek V4 Flash.
# `model` ids are easy to bump; `env` is the env-var holding that provider's key.
# ---------------------------------------------------------------------------
ANSWER_MODELS = [
    {"key": "anthropic", "label": "Sonnet 5.5",    "model": "claude-sonnet-5-5", "env": "ANTHROPIC_API_KEY", "thinking": True, "search": True},
    # An Opus 5.5 in-session run was discarded: written in a session that knew the client brand, it was biased.
    {"key": "gemini",    "label": "Gemini 4 Argon", "model": "gemini-4-argon", "env": "GEMINI_API_KEY",   "thinking": True, "search": True},
    # Argon accepts thinkingConfig but reports no thoughtsTokenCount — reasoning tokens show as 0.
    # Gemini 3.6 Flash answers for this run are archived in build/runs/2026-10-gen2/gemini-3.6_answers.json.
    {"key": "openai",    "label": "Luna 6",        "model": "gpt-6-luna",       "env": "OPENAI_API_KEY",   "thinking": True, "search": True},
    # gpt-6.1-luna was requested but the API rejects it (model not found, 2026-10-15); bump when it ships.
    {"key": "deepseek",  "label": "DeepSeek V4.1", "model": "deepseek-flash",   "env": "DEEPSEEK_API_KEY", "thinking": True, "search": True},
]

# Identifies this set of answers in the DuckDB store / build/runs/<RUN_ID>/.
RUN_ID = "2026-10-gen2"

# Model used to extract per-brand sentiment from each answer (cheap + structured).
# Kept off the OpenAI key so a GPT quota cap doesn't silently null out sentiment.
PARSER = {"key": "gemini", "model": "gemini-4-argon", "env": "GEMINI_API_KEY"}

# Opus 4.8 writes the narrative insights, per the brief.
INSIGHTS = {"key": "anthropic", "model": "claude-opus-4-8", "env": "ANTHROPIC_API_KEY"}

# The brand the report is "for" (own brand). 40 = Cake by VPBank.
OWN_BRAND_ID = 40

# Sentiment from too few mentions is noise — suppress the score below this.
SENTIMENT_MIN_MENTIONS = 10

REPORT_TITLE = "AI Visibility Report — Vietnamese Banking"
CLIENT = "VIB"
TOPIC = "Vietnamese banking products & services"

# Paths
ROOT = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(ROOT, "data")
REPORT_DIR = os.path.join(ROOT, "report")
BUILD_DIR = os.path.join(ROOT, "build")
BRANDS_FILE = os.path.join(DATA_DIR, "brands.json")
PROMPTS_FILE = os.path.join(DATA_DIR, "prompts.json")
RAW_ANSWERS_FILE = os.path.join(BUILD_DIR, "raw_answers.json")
IN_SESSION_FILE = os.path.join(BUILD_DIR, "in_session_answers.json")
EXTRACTED_FILE = os.path.join(BUILD_DIR, "extracted.json")
LLMS_TXT_FILE = os.path.join(BUILD_DIR, "llms_txt.json")
SUMMARY_FILE = os.path.join(REPORT_DIR, "summary.json")
DUCKDB_FILE = os.path.join(ROOT, "brandllm.duckdb")


def _load_dotenv(path=os.path.join(ROOT, ".env")):
    """Minimal .env loader (stdlib only). .env wins over stale shell exports."""
    if not os.path.exists(path):
        return
    for line in open(path, encoding="utf-8"):
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        k, v = k.strip().removeprefix("export ").strip(), v.strip().strip("'\"")
        if v:
            os.environ[k] = v


_load_dotenv()


def api_key(env_name):
    return os.environ.get(env_name, "").strip() if env_name else ""


def available_models():
    """Answer models whose API key is actually present in the environment."""
    return [m for m in ANSWER_MODELS if not m.get("in_session") and api_key(m["env"])]
