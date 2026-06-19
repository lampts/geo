# Design: AI Brand-Visibility Pipeline → DuckDB (reproducible)

Status: **proposal / design** — nothing here is built yet. This document covers
(1) the customer-centric prompt redesign, (2) a DuckDB-backed data pipeline modeled
on [`paulgp/ipeds-database`](https://github.com/paulgp/ipeds-database), and (3) the
research questions we will answer for the top-42 Vietnamese banks and for our own
brand, **Cake by VPBank**.

---

## 0. Why this redesign

The current pipeline (v1) works but stores everything as ad-hoc JSON
(`raw_answers.json`, `extracted.json`, `summary.json`) and computes metrics in
Python. That is fine for one report but weak for *reproducibility* and *analysis*:

- metrics are locked inside `aggregate.py` — you can't re-slice without editing code;
- no snapshots/versioning — a re-run silently overwrites the last;
- prompts are **product-centric**, not aligned to how customers actually decide.

The redesign fixes all three: a **customer-centric prompt set**, an **immutable raw
layer**, and an **analysis-ready DuckDB** where every metric is a SQL view that
anyone can run, audit, and extend.

### Borrowed principles from `ipeds-database`

| ipeds principle | How we apply it |
|---|---|
| Cached raw downloads (`data/raw/`, gitignored) prevent remote drift | Cache every LLM answer + llms.txt probe as immutable raw rows keyed by `run_id` |
| One build script does fetch → harmonize → load | `build_db.py` orchestrates all stages into one `.duckdb` |
| Harmonization handled explicitly in code, documented | Brand-alias resolution, sentiment normalization, domain classification all in one harmonize module + `DICTIONARY.md` |
| Single analysis-ready DuckDB file, built-in views | `brandllm.duckdb` with `dim_*`, `fact_*` tables and `v_*` analysis views |
| Idempotent rebuilds, subset rebuilds | `python build_db.py` (full) / `--stage harmonize` / `--run-id <id>` |
| `examples/` with ready SQL + viz | `analysis/*.sql` reproducible queries; dashboard reads from DuckDB exports |
| Reproducible with `uv` lockfile | `pyproject.toml` + `uv.lock`; pinned model IDs + temperature=0/seed where possible |

---

## 1. Prompt design (customer-centric)

### 1.1 Framework

We replace product-category prompts with **customer-decision prompts** mapped to the
Home Credit brand-attribute model (Q4'24 "From product centricity to customer
centricity"). Attributes are grouped into four priority pillars:

- **Motivators** — drive choice (needs fit, transparency, repayment, trust, service, disbursement)
- **Differentiators** — set brands apart (feel-good, collection, application speed, app, competitive rates, digital, approval rate)
- **Hygienic** — table stakes (tenure options, easy to understand, branches, promos)
- **Low priority** — nice-to-have (financial wellbeing, social responsibility)

Each prompt asks from the **customer's lived need** ("Tôi sợ phí ẩn khi dùng thẻ
tín dụng…") rather than a product spec, but stays anchored to a banking
product/service so brands still surface. This makes *AI visibility* measurable
**per customer-need pillar** — far more strategic than per product category.

### 1.2 Prompt schema (new fields)

```jsonc
{
  "prompt_id": 13,
  "pillar":    "Differentiator",        // Motivator | Differentiator | Hygienic | Low priority
  "attribute": "Has fast and easy application process",  // exact slide attribute
  "product":   "loan",                  // savings | loan | cards | digital | account | general | SME
  "text":      "Tôi cần vay tiền gấp với thủ tục đăng ký nhanh và đơn giản, nên chọn ngân hàng nào ở Việt Nam?",
  "en":        "Fastest, simplest loan application?"
}
```

`pillar` replaces the old `category`; `attribute` + `product` are new. All 19 slide
attributes are covered; priority pillars get more prompts (Motivators 10,
Differentiators 11, Hygienic 6, Low 3 = 30). Full list in
[§1.3](#13-the-30-prompts) (already reviewed and approved separately).

### 1.3 The 30 prompts

| # | Pillar | Attribute | Product |
|---|---|---|---|
| 1 | Motivator | Meets my needs | savings |
| 2 | Motivator | Meets my needs | general |
| 3 | Motivator | Transparent rates/fees | cards |
| 4 | Motivator | Transparent rates/fees | loan |
| 5 | Motivator | Easy & convenient repayment | loan |
| 6 | Motivator | Trustworthy & honest | general |
| 7 | Motivator | Great servicing | general |
| 8 | Motivator | Fast disbursement | loan |
| 9 | Motivator | Meets my needs | SME |
| 10 | Motivator | Trustworthy (safety) | general |
| 11 | Differentiator | Makes me feel good | general |
| 12 | Differentiator | Polite, professional collection | loan |
| 13 | Differentiator | Fast & easy application | loan |
| 14 | Differentiator | Fast & easy application | account |
| 15 | Differentiator | Great app/website experience | digital |
| 16 | Differentiator | Competitive rate & fees | savings |
| 17 | Differentiator | Competitive rate & fees | loan |
| 18 | Differentiator | Is a digital finance company | digital |
| 19 | Differentiator | High approval rate | cards |
| 20 | Differentiator | High approval rate | loan |
| 21 | Differentiator | Makes me feel good (premium) | general |
| 22 | Hygienic | Many tenure options | loan |
| 23 | Hygienic | Many tenure options | savings |
| 24 | Hygienic | Easy to find & understand | general |
| 25 | Hygienic | Convenient branches | general |
| 26 | Hygienic | Deals & promotions | cards |
| 27 | Hygienic | Deals & promotions | general |
| 28 | Low priority | Cares about financial wellbeing | general |
| 29 | Low priority | Social/financial responsibility | general |
| 30 | Low priority | Cares (financial education) | general |

(Vietnamese + English text stored in `data/prompts.json`.)

---

## 2. Pipeline design

### 2.1 Layered architecture

```
            ┌─────────── RAW (immutable, cached, gitignored) ───────────┐
 fetch  →   │ raw_answers (LLM answers)   raw_llms_probes (llms.txt)     │
            │ one row per (run_id, prompt_id, model_key)                 │
            └───────────────────────────────┬───────────────────────────┘
                                             │ ingest (load as-is into DuckDB)
            ┌──────────────── CORE (harmonized, dimensional) ───────────┐
 harmonize →│ dim_brand  dim_prompt  dim_model  dim_domain               │
            │ fact_answer  fact_mention  fact_citation  fact_llms_probe  │
            └───────────────────────────────┬───────────────────────────┘
                                             │ analysis (SQL views)
            ┌──────────────── MARTS (analysis-ready views) ─────────────┐
 analyze  → │ v_brand_visibility  v_visibility_by_pillar  v_by_model     │
            │ v_sentiment  v_source_mix  v_ai_readiness  v_prompt_gap    │
            └───────────────────────────────┬───────────────────────────┘
                                             │ export
                                   report/summary.json → dashboard
```

Unlike ipeds (which skips staging), we keep a thin **CORE** dimensional layer because
our raw text needs harmonization (alias matching, sentiment, domain typing) before it
is analyzable. RAW stays immutable so any metric change is a pure re-query, never a
re-fetch.

### 2.2 Stages

| Stage | Module | Input → Output | Spends API? |
|---|---|---|---|
| **fetch** | `pipeline/fetch.py` | prompts × models → `raw_answers` rows | yes (answer models) |
| **probe** | `pipeline/llms_check.py` | brand domains → `raw_llms_probes` | no (HTTP) |
| **ingest** | `pipeline/ingest.py` | raw JSON/rows → DuckDB RAW tables | no |
| **harmonize** | `pipeline/harmonize.py` | RAW → CORE (`dim_*`, `fact_*`) | parser model only (sentiment) |
| **analyze** | `analysis/views.sql` | CORE → MARTS (`v_*`) | no |
| **export** | `pipeline/export.py` | MARTS → `report/summary.json` | no (insights: Opus once) |

A single `build_db.py` runs them in order; `--stage` runs one; `--run-id` pins a snapshot.

### 2.3 DuckDB schema

```sql
-- ===== RAW (immutable landing) =====
CREATE TABLE raw_answers (
  run_id      VARCHAR,        -- e.g. '2026-06-17T...' snapshot id
  prompt_id   INTEGER,
  model_key   VARCHAR,        -- openai | anthropic | gemini | deepseek
  model_id    VARCHAR,        -- gpt-5.5, claude-opus-4-6, ...
  thinking    BOOLEAN,
  search      BOOLEAN,
  status      VARCHAR,        -- ok | error: ...
  answer_text VARCHAR,
  fetched_at  TIMESTAMP
);
CREATE TABLE raw_llms_probes (
  run_id VARCHAR, brand_id INTEGER, domain VARCHAR, path VARCHAR,
  http_status INTEGER, bytes INTEGER, ok BOOLEAN, final_url VARCHAR, probed_at TIMESTAMP
);

-- ===== CORE (harmonized, dimensional) =====
CREATE TABLE dim_brand (
  brand_id INTEGER PRIMARY KEY, name VARCHAR, domain VARCHAR,
  aliases VARCHAR[], is_own BOOLEAN, parent VARCHAR, segment VARCHAR  -- incumbent | digital | foreign
);
CREATE TABLE dim_prompt (
  prompt_id INTEGER PRIMARY KEY, pillar VARCHAR, attribute VARCHAR,
  product VARCHAR, text_vi VARCHAR, text_en VARCHAR
);
CREATE TABLE dim_model (
  model_key VARCHAR PRIMARY KEY, label VARCHAR, model_id VARCHAR,
  provider VARCHAR, thinking BOOLEAN, search BOOLEAN
);
CREATE TABLE dim_domain (
  domain VARCHAR PRIMARY KEY, source_type VARCHAR,  -- Own|Competitor|Social|News|Gov|Directory|Reference|Education|Other
  brand_id INTEGER, has_llms_txt BOOLEAN, llms_url VARCHAR
);
CREATE TABLE fact_answer (
  answer_id BIGINT PRIMARY KEY, run_id VARCHAR, prompt_id INTEGER,
  model_key VARCHAR, status VARCHAR, answer_text VARCHAR
);
CREATE TABLE fact_mention (   -- tidy/long: one row per (answer, brand)
  answer_id BIGINT, run_id VARCHAR, prompt_id INTEGER, model_key VARCHAR,
  brand_id INTEGER, sentiment VARCHAR                     -- positive|neutral|negative
);
CREATE TABLE fact_citation (
  answer_id BIGINT, run_id VARCHAR, url VARCHAR, domain VARCHAR, source_type VARCHAR, brand_id INTEGER
);
CREATE TABLE fact_llms_probe (
  run_id VARCHAR, brand_id INTEGER, domain VARCHAR, has_llms_txt BOOLEAN, llms_url VARCHAR
);
```

### 2.4 Harmonization rules (explicit, documented in `DICTIONARY.md`)

Analogous to ipeds' cross-year harmonization, we resolve our messy-text issues in code:

1. **Brand resolution** — diacritic-insensitive, word-boundary alias matching
   (`Cake by VPBank` ⊃ `Cake`, `Cake Digital Bank`). Parent/child kept distinct
   (Cake ≠ VPBank, Timo ≠ VPBank, TNEX ≠ MSB) but linked via `dim_brand.parent`.
2. **Sentiment normalization + reliability gate** — map parser output to
   {positive, neutral, negative}; `positive_pct` is `NULL` when a brand has
   `< SENTIMENT_MIN_MENTIONS` (10) mentions. Encoded as a view, not baked into facts.
3. **Domain classification** — `dim_domain.source_type` via the brand-domain set +
   curated keyword lists (social/news/gov/directory/reference/education).
4. **Model param divergence** — `gpt-5.x` reject `temperature` (Responses API +
   reasoning); newer Opus deprecate `temperature`; DeepSeek has no web-search tool.
   Recorded per `dim_model` so coverage caveats are queryable, not hidden.
5. **Citation extraction** — URLs parsed from answer text (chat APIs aren't search
   engines); `web_pct` therefore measures citing behavior, flagged as such.
6. **Missing/204** — failed answers kept with `status='error'` (never dropped), so
   denominators are honest and per-model coverage is auditable.

### 2.5 Reproducibility

- **Immutable RAW + `run_id`**: every fetch is a snapshot; rebuilds never mutate past
  runs. `WHERE run_id = (SELECT max(run_id) FROM ...)` selects "latest".
- **Determinism where possible**: pinned model IDs in `config.py`; `temperature=0`
  / fixed seed for parser; prompts/brands version-controlled. (Answer models with
  thinking+search aren't fully deterministic — this is logged, not hidden.)
- **One command**: `uv run python build_db.py` rebuilds `brandllm.duckdb` end-to-end
  from cached RAW without re-spending; `--refetch` re-queries models.
- **Cached RAW** in `data/raw/run_<id>/` (gitignored) → fast rebuilds, no drift.
- **`DICTIONARY.md`** documents every column, code, and harmonization decision.
- **`analysis/*.sql`** are the canonical metric definitions — the dashboard and any
  ad-hoc analysis read the *same* views, so numbers can't diverge.

### 2.6 Proposed file layout

```
brandllm/
├── build_db.py                # orchestrator: fetch→ingest→harmonize→analyze→export
├── pyproject.toml  uv.lock     # pinned deps (duckdb, requests, ...)
├── config.py                   # models, own brand, thresholds, paths
├── data/
│   ├── brands.json  prompts.json
│   └── raw/run_<id>/           # cached answers + probes (gitignored)
├── pipeline/
│   ├── fetch.py  llms_check.py  ingest.py  harmonize.py  export.py  providers.py
├── analysis/
│   ├── views.sql               # all v_* analysis views (canonical metrics)
│   ├── q_market.sql            # top-42 research queries (§3)
│   └── q_cake.sql              # own-brand research queries (§4)
├── brandllm.duckdb             # analysis-ready DB (gitignored)
├── report/                     # Healy-style dashboard (reads exported summary.json)
├── DICTIONARY.md  design.md  README.md
```

### 2.7 Migration from v1 (JSON) → v2 (DuckDB)

1. Keep `providers.py`, `llms_check.py`, prompt/brand data.
2. Wrap existing `raw_answers.json` as the first `run_id` (no re-spend): load into
   `raw_answers`.
3. Port `extract.py`/`aggregate.py` logic into `harmonize.py` (writes facts) +
   `analysis/views.sql` (computes metrics). Metrics become SQL, not Python.
4. `export.py` renders `summary.json` from the `v_*` views → existing dashboard works
   unchanged.

---

## 3. Research questions — top 42 banks (market level)

Each is answerable by a SQL view/query over CORE; listed with the driving metric.

**Visibility & structure**
1. Who are the AI-visibility leaders overall, and how steep is the drop-off? *(v_brand_visibility)*
2. How concentrated is the market in AI answers (share-of-voice HHI)? Oligopoly or long tail? *(SoV + Herfindahl)*
3. Which banks over-/under-index on visibility vs their real-world market share? *(needs external AUM/branch join — optional)*

**Customer-need pillars (the new lens)**
4. Which banks own each **pillar** (Motivator / Differentiator / Hygienic / Low)? *(v_visibility_by_pillar)*
5. Which **attributes** are winner-take-all vs contested (visibility dispersion per attribute)?
6. Where are incumbents strong (trust, branches) vs where do challengers win (app, digital, approval)? *(segment × pillar)*

**Model behavior**
7. How much do the 4 models disagree on the leaderboard (rank correlation across models)? *(v_by_model)*
8. Does any model systematically favor incumbents vs digital banks? *(segment share per model)*
9. Citation coverage by model — who grounds answers in web sources? *(web_pct)*

**Sentiment & sources**
10. Where do sentiment leaders differ from visibility leaders (loved-but-invisible / visible-but-meh)? *(reliable sentiment only)*
11. What domains drive the brand conversation (competitor sites vs news vs social vs directories)? *(v_source_mix, dim_domain)*

**AI-readiness**
12. What is llms.txt adoption across the 42, and does having it correlate with higher visibility/citation? *(v_ai_readiness)*
13. Digital-only banks (Cake, Timo, TNEX, Vikki, MBV) vs incumbents — visibility & AI-readiness gap? *(segment cut)*

---

## 4. Research questions — own bank (Cake by VPBank)

Actionable, brand-strategy framed; each maps to a `q_cake.sql` query.

**Position**
1. Cake's overall rank and visibility, and its rank **within digital banks** (vs Timo, TNEX, Vikki, MBV)?
2. Per **pillar/attribute**, where does Cake appear vs where is it absent? → the **gap list** of customer needs AI doesn't associate with Cake.
3. On which specific **prompts** is Cake absent while a competitor is cited? → prioritized content/SEO targets. *(v_prompt_gap filtered to own)*

**Perception**
4. Cake's sentiment (only if ≥10 mentions) and any negative mentions — what drives them? *(fact_mention join answers)*
5. Which **products** (savings/loan/cards/digital) does Cake win or lose on?

**Model & source footprint**
6. Which models surface Cake most/least? Is Cake invisible on any model? *(by model)*
7. What sources cite Cake, and is **cake.vn** itself cited (own-domain citation share)? *(fact_citation where brand_id=own)*

**AI-readiness (Cake is the only one of 42 with llms.txt)**
8. Does Cake's llms.txt presence translate into higher citation of cake.vn vs peers without it?
9. What should `cake.vn/llms.txt` contain to steer models toward Cake's strong attributes (digital, feel-good, approval)? *(qualitative, informed by gap list)*

**Trend (enabled by run_id snapshots)**
10. How does Cake's visibility / pillar coverage / sentiment move across runs over time? *(group by run_id)*

---

## 5. Decisions (signed off 2026-06-17)

1. **Store: DuckDB.** ✅ Confirmed.
2. **Deps: `uv` + lockfile.** ✅ `pyproject.toml` + `uv.lock`, deps = duckdb (+ existing).
3. **Snapshots: keep all `run_id`s.** ✅ Enables §4 Q10 trend analysis.
4. **External joins (market share/AUM): later.** Q3 deferred to a future run.
5. **Build order: plumbing first.** ✅ Build the DuckDB layers against the EXISTING
   cached answers (loaded as `run_id` #1, no API spend), validate schema/views/
   dashboard, then re-query with the new customer-centric prompts as `run_id` #2.
```
