-- Research questions — OWN BRAND: Cake by VPBank (brand_id 40). See design.md §4.
-- duckdb brandllm.duckdb < analysis/q_cake.sql

-- Q1. Cake's overall rank, and its rank within digital banks.
SELECT rank, name, visibility_pct, sov_pct, mentions FROM v_brand_visibility
WHERE run_id='baseline' AND is_own;

SELECT name, visibility_pct,
       rank() OVER (ORDER BY visibility_pct DESC) AS rank_among_digital
FROM v_brand_visibility WHERE run_id='baseline' AND segment='digital'
ORDER BY visibility_pct DESC;

-- Q2. Per-pillar coverage: where Cake appears vs where it's ABSENT (the gap list).
WITH pillars AS (SELECT DISTINCT pillar FROM dim_prompt)
SELECT pl.pillar, COALESCE(v.mentions, 0) AS cake_mentions
FROM pillars pl
LEFT JOIN v_visibility_by_pillar v
  ON v.pillar = pl.pillar AND v.run_id='baseline' AND v.brand_id = 40
ORDER BY cake_mentions;

-- Q3. Prompts where Cake is ABSENT while competitors are cited (prioritized targets).
SELECT prompt_id, pillar, attribute, product, competitors_count, top_competitor, text_vi
FROM v_prompt_gap
WHERE run_id='baseline' AND NOT own_present AND competitors_count > 0
ORDER BY competitors_count DESC;

-- Q4. Cake sentiment (only meaningful with >=10 mentions) + any negative mentions.
SELECT * FROM v_sentiment_by_brand WHERE run_id='baseline' AND brand_id = 40;

SELECT fm.prompt_id, dm.label AS model, p.attribute
FROM fact_mention fm JOIN dim_model dm USING (model_key) JOIN dim_prompt p USING (prompt_id)
WHERE fm.run_id='baseline' AND fm.brand_id = 40 AND fm.sentiment='negative';

-- Q5. Which products Cake wins/loses on (mentions by product).
SELECT p.product, count(*) AS cake_mentions
FROM fact_mention fm JOIN dim_prompt p USING (prompt_id)
WHERE fm.run_id='baseline' AND fm.brand_id = 40
GROUP BY 1 ORDER BY cake_mentions DESC;

-- Q6. Which models surface Cake most/least (is it invisible on any model?).
SELECT model, mentions, answers, visibility_pct
FROM v_visibility_by_model WHERE run_id='baseline' AND brand_id = 40
ORDER BY visibility_pct DESC;

-- Q7. Sources that cite Cake, and own-domain (cake.vn) citation share.
SELECT domain, source_type, count(*) AS cites
FROM fact_citation WHERE run_id='baseline' AND brand_id = 40
GROUP BY 1, 2 ORDER BY cites DESC;

-- Q8. AI-readiness: does Cake's llms.txt presence coincide with own-domain citations?
SELECT (SELECT has_llms_txt FROM v_ai_readiness WHERE run_id='baseline' AND brand_id=40) AS cake_has_llms_txt,
       count(*) FILTER (WHERE domain='cake.vn') AS cake_vn_citations,
       count(*) AS all_citations_in_run
FROM fact_citation WHERE run_id='baseline';

-- Q10. Trend across runs (once >1 snapshot exists).
SELECT run_id, rank, visibility_pct, sov_pct, mentions
FROM v_brand_visibility WHERE brand_id = 40 ORDER BY run_id;
