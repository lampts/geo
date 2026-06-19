# AI Visibility Report — Vietnamese Banking

A from-scratch reimplementation of a brand AI-visibility report. Asks 30 prompts
about Vietnamese banking products/services across 4 LLMs, parses every answer for
brand mentions / citations / sentiment, ranks the 40 tracked brands, has **Opus
4.8** write the insights, and renders a static dashboard in the style of
**Kieran Healy's** data-visualization grammar (Cleveland dot plots, small
multiples, direct labelling, quiet palette).

## Pipeline

```
data/brands.json  (40 brands: 39 from the source report + Cake by VPBank)
data/prompts.json (30 VN prompts about products/services)
        │
  run_queries  →  30 prompts × 4 models = 120 answers        (build/raw_answers.json)
        │
  extract      →  mentions (alias match) + citations (URL) + sentiment (LLM)
        │
  llms_check   →  probe /llms.txt on every brand domain (AI-readiness signal)
        │
  aggregate    →  visibility %, share of voice, sentiment, source mix, ranking
        │
  insights     →  Opus 4.8 writes the narrative (Vietnamese)
        │
  build        →  report/summary.json
        │
  report/index.html  →  Observable-Plot dashboard, Healy style
```

## DuckDB store (v2, reproducible — see design.md)

Raw answers are harmonized into an analysis-ready DuckDB (`brandllm.duckdb`) modeled
on [paulgp/ipeds-database](https://github.com/paulgp/ipeds-database): immutable RAW
keyed by `run_id`, a dimensional CORE, and `v_*` analysis views that ARE the metric
definitions (`analysis/views.sql`). The dashboard exports from these views.

```bash
uv sync                                   # install deps (duckdb)
uv run python build_db.py --run-id baseline   # ingest cached answers → build → export
duckdb brandllm.duckdb < analysis/q_market.sql   # top-42 research queries
duckdb brandllm.duckdb < analysis/q_cake.sql     # own-brand (Cake) research queries
```

Stages (`--stage ingest|harmonize|analyze|export|all`): ingest RAW → harmonize CORE
→ analyze MARTS → export `report/summary.json`. Column/metric reference: `DICTIONARY.md`.

The 4 answer models (configurable in `config.py`), all run with **thinking +
web-search** where the provider supports it:
OpenAI `gpt-5.5` · Anthropic `claude-opus-4-6` · Gemini `gemini-3.5-flash` · DeepSeek `deepseek-v4-flash`.
Sentiment parser: `gemini-3.5-flash` (kept off the OpenAI key). Insights model: `claude-opus-4-8`.
Own brand: **Cake by VPBank** (`OWN_BRAND_ID = 40`).

Data-quality guards:
- **Sentiment reliability gate** — brands with fewer than `SENTIMENT_MIN_MENTIONS`
  (10) mentions get `positive_pct: null` / `sentiment_reliable: false`, are dropped
  from the sentiment chart, and show "n/a" — low-N noise never becomes a fake score.
- **llms.txt AI-readiness** — `pipeline/llms_check.py` probes `/llms.txt` (and
  `/llms-full.txt`) on each brand domain, cached in `build/llms_txt.json`. Force a
  re-fetch with `python -m pipeline.build --refresh-llms`.

Provider caveats: DeepSeek has no server-side web-search tool (degrades to none);
gpt-5.x reject `temperature` and use the Responses API for search; newer Opus
deprecates `temperature`.

## Run

```bash
# 1. keys — only the providers you set will be queried
export OPENAI_API_KEY=...
export ANTHROPIC_API_KEY=...      # also used for Opus 4.8 insights
export GEMINI_API_KEY=...
export DEEPSEEK_API_KEY=...

# 2. full pipeline (real answers → report/summary.json)
python -m pipeline.build
#   re-parse cached answers (parser only, no answer re-querying):
python -m pipeline.build --re-extract
#   re-aggregate only, from build/extracted.json:
python -m pipeline.build --from-cache

# 3. view (any static server)
cd report && python -m http.server 8765   # → http://localhost:8765
```

No real keys yet? Generate clearly-labelled placeholder data so the dashboard
renders immediately (no API spend, exercises the real aggregation code):

```bash
python -m pipeline.demo
```

## Notes
- Stdlib only — no `pip install` needed. The dashboard pulls Observable Plot from a CDN.
- **Own brand** is VIB (`OWN_BRAND_ID = 13` in `config.py`); change it to refocus the report.
- Citations come from URLs the models write in their answers (plain chat APIs aren't
  search engines), so `web_pct` reflects citing behaviour, not a live index. Wire up
  each provider's web-search/grounding tool in `providers.py` for true coverage.
