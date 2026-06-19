-- Canonical analysis views (MARTS). These ARE the metric definitions — the
-- dashboard export and every ad-hoc query read the same views, so numbers can
-- never diverge. All views carry run_id so trend analysis works across snapshots.
-- Sentiment reliability floor is 10 mentions (see DICTIONARY.md).

-- ---- run-level totals ----
CREATE OR REPLACE VIEW v_run_totals AS
SELECT run_id,
       count(*)                          AS total_answers,
       count(*) FILTER (WHERE status='ok') AS ok_answers,
       count(DISTINCT model_key)         AS total_models
FROM fact_answer
GROUP BY run_id;

CREATE OR REPLACE VIEW v_mention_totals AS
SELECT run_id, count(*) AS total_mentions FROM fact_mention GROUP BY run_id;

-- ---- visibility ranking (all brands, zeros included) ----
CREATE OR REPLACE VIEW v_brand_visibility AS
WITH m AS (
  SELECT run_id, brand_id, count(*) AS mentions FROM fact_mention GROUP BY 1, 2
)
SELECT r.run_id, b.brand_id, b.name, b.is_own, b.segment,
       COALESCE(m.mentions, 0) AS mentions,
       round(100.0 * COALESCE(m.mentions, 0) / NULLIF(r.ok_answers, 0), 1)       AS visibility_pct,
       round(100.0 * COALESCE(m.mentions, 0) / NULLIF(mt.total_mentions, 0), 1)  AS sov_pct,
       rank() OVER (PARTITION BY r.run_id ORDER BY COALESCE(m.mentions, 0) DESC) AS rank
FROM v_run_totals r
CROSS JOIN dim_brand b
LEFT JOIN m  ON m.run_id = r.run_id AND m.brand_id = b.brand_id
LEFT JOIN v_mention_totals mt ON mt.run_id = r.run_id;

-- ---- sentiment with reliability gate ----
CREATE OR REPLACE VIEW v_sentiment_by_brand AS
WITH s AS (
  SELECT run_id, brand_id,
         count(*) FILTER (WHERE sentiment='positive') AS positive,
         count(*) FILTER (WHERE sentiment='neutral')  AS neutral,
         count(*) FILTER (WHERE sentiment='negative') AS negative,
         count(*)                                      AS total
  FROM fact_mention GROUP BY 1, 2
)
SELECT s.run_id, s.brand_id, b.name, b.is_own,
       s.positive, s.neutral, s.negative, s.total,
       (s.total >= 10)                                                   AS sentiment_reliable,
       CASE WHEN s.total >= 10 THEN round(100.0 * s.positive / s.total, 1) END AS positive_pct
FROM s JOIN dim_brand b USING (brand_id);

-- ---- visibility by model (tidy long, for small multiples) ----
CREATE OR REPLACE VIEW v_visibility_by_model AS
WITH am AS (  -- ok answers per model per run = denominator
  SELECT run_id, model_key, count(*) AS answers
  FROM fact_answer WHERE status='ok' GROUP BY 1, 2
), mm AS (
  SELECT run_id, model_key, brand_id, count(*) AS mentions
  FROM fact_mention GROUP BY 1, 2, 3
)
SELECT mm.run_id, mm.brand_id, b.name AS brand, d.label AS model, mm.model_key,
       mm.mentions, am.answers,
       round(100.0 * mm.mentions / NULLIF(am.answers, 0), 1) AS visibility_pct
FROM mm
JOIN dim_brand b USING (brand_id)
JOIN dim_model d USING (model_key)
JOIN am ON am.run_id = mm.run_id AND am.model_key = mm.model_key;

-- ---- visibility by customer-need pillar (the new strategic lens) ----
CREATE OR REPLACE VIEW v_visibility_by_pillar AS
SELECT fm.run_id, p.pillar, fm.brand_id, b.name, b.is_own,
       count(*) AS mentions
FROM fact_mention fm
JOIN dim_prompt p USING (prompt_id)
JOIN dim_brand  b USING (brand_id)
GROUP BY 1, 2, 3, 4, 5;

-- ---- visibility by pillar, normalized within pillar (pillars differ in size) ----
CREATE OR REPLACE VIEW v_pillar_answers AS
SELECT fa.run_id, p.pillar, count(*) AS answers
FROM fact_answer fa JOIN dim_prompt p USING (prompt_id)
WHERE fa.status='ok' GROUP BY 1, 2;

CREATE OR REPLACE VIEW v_pillar_visibility AS
SELECT v.run_id, v.pillar, v.brand_id, v.name, v.is_own, v.mentions,
       round(100.0 * v.mentions / NULLIF(pa.answers, 0), 1) AS pillar_pct
FROM v_visibility_by_pillar v
JOIN v_pillar_answers pa ON pa.run_id = v.run_id AND pa.pillar = v.pillar;

-- ---- sentiment by model ----
CREATE OR REPLACE VIEW v_sentiment_by_model AS
SELECT fm.run_id, d.label AS model,
       round(100.0 * count(*) FILTER (WHERE sentiment='positive') / NULLIF(count(*),0),1) AS positive_pct,
       round(100.0 * count(*) FILTER (WHERE sentiment='neutral')  / NULLIF(count(*),0),1) AS neutral_pct,
       round(100.0 * count(*) FILTER (WHERE sentiment='negative') / NULLIF(count(*),0),1) AS negative_pct
FROM fact_mention fm JOIN dim_model d USING (model_key)
GROUP BY 1, 2;

-- ---- source mix + domain ranking + citation coverage ----
CREATE OR REPLACE VIEW v_source_mix AS
WITH c AS (SELECT run_id, count(*) AS total FROM fact_citation GROUP BY 1)
SELECT fc.run_id, fc.source_type AS type,
       count(*) AS citations,
       round(100.0 * count(*) / NULLIF(c.total,0),1) AS pct,
       count(DISTINCT fc.domain) AS domains
FROM fact_citation fc JOIN c USING (run_id)
GROUP BY fc.run_id, fc.source_type, c.total;

CREATE OR REPLACE VIEW v_domain_ranking AS
SELECT run_id, domain, source_type AS type, count(*) AS citations
FROM fact_citation
GROUP BY 1, 2, 3;

CREATE OR REPLACE VIEW v_citation_coverage AS
WITH a AS (
  SELECT run_id, model_key, count(*) AS answers FROM fact_answer WHERE status='ok' GROUP BY 1,2
), w AS (
  SELECT a.run_id, a.model_key, count(DISTINCT c.answer_id) AS with_url
  FROM fact_citation c JOIN fact_answer a ON a.answer_id = c.answer_id
  GROUP BY 1, 2
)
SELECT a.run_id, d.label AS model, a.answers, COALESCE(w.with_url,0) AS with_url,
       round(100.0 * COALESCE(w.with_url,0) / NULLIF(a.answers,0),1) AS web_pct
FROM a JOIN dim_model d USING (model_key)
LEFT JOIN w ON w.run_id=a.run_id AND w.model_key=a.model_key;

-- ---- AI-Equity Index (AEI): brand-equity-index-style banded composite ----
-- raw equity = reach × quality × consistency × readiness:
--   reach       = visibility fraction (presence across answers)
--   quality     = 0.5 + 0.5·positive-sentiment  (gated; unknown -> category avg)
--   consistency = 0.5 + 0.5·(models that surface the brand / all models)
--   readiness   = 1 + 0.10·has_llms_txt  (small AI-optimization bonus)
-- AEI = raw / category-average raw (brands with >=1 mention) -> 1.0 == average.
-- Bands mirror BEI: >3 Strong · 1-3 Moderate · <1 Weak.
CREATE OR REPLACE VIEW v_brand_model_breadth AS
SELECT run_id, brand_id, count(DISTINCT model_key) AS models_seen
FROM fact_mention GROUP BY 1, 2;

CREATE OR REPLACE VIEW v_ai_equity AS
WITH comp AS (
  SELECT v.run_id, v.brand_id, v.name, v.is_own, v.segment, v.visibility_pct, v.mentions,
         s.positive_pct, COALESCE(s.sentiment_reliable, FALSE) AS reliable,
         COALESCE(mb.models_seen, 0) AS models_seen,
         COALESCE(ar.has_llms_txt, FALSE) AS has_llms_txt
  FROM v_brand_visibility v
  LEFT JOIN v_sentiment_by_brand s ON s.run_id = v.run_id AND s.brand_id = v.brand_id
  LEFT JOIN v_brand_model_breadth mb ON mb.run_id = v.run_id AND mb.brand_id = v.brand_id
  LEFT JOIN v_ai_readiness ar ON ar.run_id = v.run_id AND ar.brand_id = v.brand_id
),
prior AS (SELECT run_id, avg(positive_pct) AS cat_pos FROM comp WHERE reliable GROUP BY run_id),
nm AS (SELECT run_id, count(DISTINCT model_key) AS total_models FROM fact_answer WHERE status='ok' GROUP BY 1),
raw AS (
  SELECT c.run_id, c.brand_id, c.name, c.is_own, c.segment, c.visibility_pct, c.mentions,
         c.positive_pct, c.reliable, c.has_llms_txt, c.models_seen, nm.total_models,
         (c.visibility_pct / 100.0)
           * (0.5 + 0.5 * COALESCE(c.positive_pct, p.cat_pos) / 100.0)
           * (0.5 + 0.5 * c.models_seen * 1.0 / NULLIF(nm.total_models, 0))
           * (1 + 0.10 * CASE WHEN c.has_llms_txt THEN 1 ELSE 0 END) AS raw_equity
  FROM comp c JOIN prior p USING (run_id) JOIN nm USING (run_id)
)
SELECT run_id, brand_id, name, is_own, segment, visibility_pct, mentions,
       positive_pct, reliable, has_llms_txt, models_seen, total_models,
       round(raw_equity, 4) AS raw_equity,
       round(raw_equity / NULLIF(avg(CASE WHEN mentions > 0 THEN raw_equity END)
             OVER (PARTITION BY run_id), 0), 2) AS aei,
       CASE WHEN mentions = 0 THEN 'Weak'
            WHEN raw_equity / NULLIF(avg(CASE WHEN mentions > 0 THEN raw_equity END)
                 OVER (PARTITION BY run_id), 0) > 3 THEN 'Strong'
            WHEN raw_equity / NULLIF(avg(CASE WHEN mentions > 0 THEN raw_equity END)
                 OVER (PARTITION BY run_id), 0) >= 1 THEN 'Moderate'
            ELSE 'Weak' END AS aei_band,
       rank() OVER (PARTITION BY run_id ORDER BY raw_equity DESC) AS aei_rank
FROM raw;

-- ---- token usage + cost per model per run ----
CREATE OR REPLACE VIEW v_token_usage AS
SELECT tu.run_id, d.label AS model, d.model_id, d.search,
       count(*) FILTER (WHERE tu.status='ok')      AS ok_calls,
       sum(tu.input_tokens)                         AS input_tokens,
       sum(tu.output_tokens)                        AS output_tokens,
       sum(tu.reasoning_tokens)                     AS reasoning_tokens,
       sum(tu.total_tokens)                         AS total_tokens
FROM fact_token_usage tu JOIN dim_model d USING (model_key)
GROUP BY 1, 2, 3, 4;

CREATE OR REPLACE VIEW v_cost AS
SELECT u.run_id, u.model, u.model_id, u.ok_calls,
       u.input_tokens, u.output_tokens, u.reasoning_tokens,
       round(u.input_tokens / 1e6 * p.input_per_m, 4)                          AS input_cost,
       round((u.output_tokens + u.reasoning_tokens) / 1e6 * p.output_per_m, 4) AS output_cost,
       round(CASE WHEN u.search THEN u.ok_calls * p.search_per_call ELSE 0 END, 4) AS search_cost,
       round(u.input_tokens / 1e6 * p.input_per_m
           + (u.output_tokens + u.reasoning_tokens) / 1e6 * p.output_per_m
           + CASE WHEN u.search THEN u.ok_calls * p.search_per_call ELSE 0 END, 4) AS total_cost_usd
FROM v_token_usage u LEFT JOIN dim_pricing p ON p.model_id = u.model_id;

-- ---- AI-readiness: llms.txt presence vs visibility ----
CREATE OR REPLACE VIEW v_ai_readiness AS
SELECT v.run_id, v.brand_id, v.name, v.is_own, v.segment, v.rank, v.visibility_pct,
       COALESCE(lp.has_llms_txt, FALSE) AS has_llms_txt, lp.llms_url
FROM v_brand_visibility v
LEFT JOIN fact_llms_probe lp ON lp.run_id = v.run_id AND lp.brand_id = v.brand_id;

-- ---- prompt-level gap map (own brand vs competitors) ----
CREATE OR REPLACE VIEW v_prompt_gap AS
WITH per AS (
  SELECT fm.run_id, fm.prompt_id, fm.brand_id, count(*) AS n,
         bool_or(b.is_own) AS is_own
  FROM fact_mention fm JOIN dim_brand b USING (brand_id)
  GROUP BY 1, 2, 3
)
SELECT pr.run_id, pr.prompt_id, p.pillar, p.attribute, p.product, p.text_vi,
       COALESCE(SUM(per.n) FILTER (WHERE per.is_own), 0)        AS own_mentions,
       COALESCE(SUM(per.n) FILTER (WHERE per.is_own), 0) > 0    AS own_present,
       count(DISTINCT per.brand_id) FILTER (WHERE NOT per.is_own) AS competitors_count,
       arg_max(b2.name, per.n) FILTER (WHERE NOT per.is_own)    AS top_competitor
FROM (SELECT DISTINCT run_id, prompt_id FROM fact_mention) pr
JOIN dim_prompt p USING (prompt_id)
LEFT JOIN per ON per.run_id = pr.run_id AND per.prompt_id = pr.prompt_id
LEFT JOIN dim_brand b2 ON b2.brand_id = per.brand_id
GROUP BY pr.run_id, pr.prompt_id, p.pillar, p.attribute, p.product, p.text_vi;
