# Data dictionary — brandllm.duckdb

Documents every table/column and the harmonization decisions, in the spirit of
ipeds-database's `DICTIONARY.md`. Metrics are defined in `analysis/views.sql`.

## Layers
- **RAW** (`raw_*`) — immutable landing, keyed by `run_id`. Never mutated; a metric
  change is a SQL re-query, not a re-fetch.
- **CORE** (`dim_*`, `fact_*`) — harmonized dimensional model.
- **MARTS** (`v_*`) — analysis views = canonical metric definitions.

## RAW
| Table | Columns |
|---|---|
| `raw_answers` | run_id, prompt_id, model_key, model_id, status, answer_text, fetched_at |
| `raw_extracted` | run_id, prompt_id, model_key, mentions (JSON), citations (JSON) |
| `raw_llms_probes` | run_id, brand_id, domain, has_llms_txt, llms_url, http_status, bytes |

## CORE — dimensions
| Table | Key columns | Notes |
|---|---|---|
| `dim_brand` | brand_id, name, domain, aliases (JSON), is_own, parent, segment | `segment` ∈ {incumbent, digital, foreign}. `parent` only set where confident (Cake→VPBank, TNEX→MSB, Vikki→HDBank). |
| `dim_prompt` | prompt_id, pillar, attribute, product, text_vi, text_en | `pillar` falls back to legacy `category` until customer-centric prompts land. |
| `dim_model` | model_key, label, model_id, provider, thinking, search | Records per-model capabilities (DeepSeek search=false: no API tool). |
| `dim_domain` | domain, source_type, brand_id, has_llms_txt, llms_url | `source_type` ∈ {Own, Competitor, Social, News/Media, Government, Directory/Review, Reference, Education, Other}. |

## CORE — facts
| Table | Grain | Columns |
|---|---|---|
| `fact_answer` | one per (run, prompt, model) | answer_id, run_id, prompt_id, model_key, status, answer_text |
| `fact_mention` | one per (answer, brand) — tidy/long | answer_id, run_id, prompt_id, model_key, brand_id, sentiment |
| `fact_citation` | one per cited URL | answer_id, run_id, url, domain, source_type, brand_id |
| `fact_llms_probe` | one per (run, brand) | run_id, brand_id, domain, has_llms_txt, llms_url |

`answer_id` = `"{run_id}|{prompt_id}|{model_key}"`.

## Harmonization decisions
1. **Brand resolution** — diacritic-insensitive, word-boundary alias matching. Parent
   and child are distinct brands (Cake ≠ VPBank) but linked via `dim_brand.parent`.
2. **Sentiment** ∈ {positive, neutral, negative}, LLM-scored. **Reliability gate:**
   `v_sentiment_by_brand.positive_pct` is `NULL` and `sentiment_reliable=false` when a
   brand has `< 10` mentions (`SENTIMENT_MIN_MENTIONS`). Low-N noise never becomes a score.
3. **Domain classification** — brand-domain set + curated keyword lists.
4. **Model param divergence** — gpt-5.x reject `temperature` (Responses API + reasoning);
   newer Opus deprecate `temperature`; DeepSeek lacks a web-search tool. Captured in
   `dim_model`, so coverage caveats are queryable.
5. **Citations** — URLs parsed from answer text; chat APIs aren't search engines, so
   `v_citation_coverage.web_pct` measures *citing behavior*, not a live index.
6. **Failed answers** kept with `status='error'` (never dropped) → honest denominators.

## Key metric definitions (see `analysis/views.sql`)
| Metric | Definition |
|---|---|
| Visibility % | brand mentions ÷ ok answers in the run × 100 |
| Share of voice % | brand mentions ÷ all mentions in the run × 100 |
| Visibility by model | brand mentions on a model ÷ that model's ok answers × 100 |
| Positive sentiment % | positive ÷ total mentions × 100, only if total ≥ 10 |
| Web coverage % | answers with ≥1 URL ÷ ok answers, per model |
| AI-readiness | does `dim_domain.has_llms_txt` for the brand's domain |
| **AEI (AI-Equity Index)** | `v_ai_equity`. raw = (visibility/100) × (0.5+0.5·sentiment) × (0.5+0.5·model-breadth) × (1+0.10·llms_txt); **AEI = raw ÷ category-average raw** (brands ≥1 mention) so 1.0 = average. Bands (brand-equity-index style): **>3 Strong · 1–3 Moderate · <1 Weak**. Unknown sentiment shrinks to the category mean. The AI-channel analog of a survey brand-equity index. |

## Reproducibility
- `run_id` snapshots are retained (all runs kept) → trend analysis via `GROUP BY run_id`.
- Rebuild: `uv run python build_db.py` (idempotent; deletes+reloads the run, rebuilds views).
- Cached RAW lives in JSON (`build/*.json`) and is loaded verbatim; `brandllm.duckdb` is derived and gitignored.
