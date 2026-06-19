"""Central configuration for the Vietnamese-banking AI-visibility pipeline.

Everything tunable lives here: which models answer the prompts, which model
parses sentiment, and which model writes the insights. All keys are read from
environment variables at runtime — nothing secret is stored in the repo.
"""
import os

# ---------------------------------------------------------------------------
# Answer models — the 4 LLMs we ask each prompt (30 prompts x 4 = 120 answers).
# `model` ids are easy to bump; `env` is the env-var holding that provider's key.
# ---------------------------------------------------------------------------
ANSWER_MODELS = [
    {"key": "openai",    "label": "GPT-5.5",     "model": "gpt-5.5",          "env": "OPENAI_API_KEY",    "thinking": True, "search": True},
    {"key": "anthropic", "label": "Opus 4.6",    "model": "claude-opus-4-6",  "env": "ANTHROPIC_API_KEY", "thinking": True, "search": True},
    {"key": "gemini",    "label": "Gemini 3.5",  "model": "gemini-3.5-flash", "env": "GEMINI_API_KEY",    "thinking": True, "search": True},
    {"key": "deepseek",  "label": "DeepSeek V4", "model": "deepseek-v4-flash","env": "DEEPSEEK_API_KEY",  "thinking": True, "search": True},
]

# Model used to extract per-brand sentiment from each answer (cheap + structured).
# Kept off the OpenAI key so a GPT quota cap doesn't silently null out sentiment.
PARSER = {"key": "gemini", "model": "gemini-3.5-flash", "env": "GEMINI_API_KEY"}

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
EXTRACTED_FILE = os.path.join(BUILD_DIR, "extracted.json")
LLMS_TXT_FILE = os.path.join(BUILD_DIR, "llms_txt.json")
SUMMARY_FILE = os.path.join(REPORT_DIR, "summary.json")
DUCKDB_FILE = os.path.join(ROOT, "brandllm.duckdb")


def api_key(env_name):
    return os.environ.get(env_name, "").strip()


def available_models():
    """Answer models whose API key is actually present in the environment."""
    return [m for m in ANSWER_MODELS if api_key(m["env"])]
