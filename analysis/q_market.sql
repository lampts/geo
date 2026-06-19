-- Research questions — TOP-42 BANKS (market level). See design.md §3.
-- Run against brandllm.duckdb, e.g.:  duckdb brandllm.duckdb < analysis/q_market.sql
-- Replace 'baseline' with the run_id you want; views already carry run_id.

-- Q1. Visibility leaders and the drop-off.
SELECT rank, name, segment, visibility_pct, sov_pct, mentions
FROM v_brand_visibility WHERE run_id='baseline' AND mentions > 0
ORDER BY rank LIMIT 15;

-- Q2. SoV concentration — Herfindahl index (0..10000). >2500 = concentrated.
SELECT run_id, round(sum(sov_pct * sov_pct), 0) AS hhi,
       round(sum(CASE WHEN rank <= 5 THEN sov_pct END), 1) AS top5_sov_pct
FROM v_brand_visibility WHERE run_id='baseline' GROUP BY run_id;

-- Q4. Who owns each customer-need pillar (top brand per pillar by mentions).
SELECT pillar, name, mentions FROM (
  SELECT pillar, name, mentions,
         rank() OVER (PARTITION BY pillar ORDER BY mentions DESC) AS rk
  FROM v_visibility_by_pillar WHERE run_id='baseline'
) WHERE rk <= 3 ORDER BY pillar, mentions DESC;

-- Q5. Most contested vs concentrated attributes (distinct brands surfaced per prompt).
SELECT p.pillar, p.attribute, count(DISTINCT fm.brand_id) AS distinct_brands,
       count(*) AS total_mentions
FROM fact_mention fm JOIN dim_prompt p USING (prompt_id)
WHERE fm.run_id='baseline'
GROUP BY 1, 2 ORDER BY distinct_brands DESC;

-- Q6. Segment strength by pillar (incumbent vs digital vs foreign).
SELECT pillar, segment, sum(mentions) AS mentions
FROM v_visibility_by_pillar v JOIN dim_brand b USING (brand_id)
WHERE run_id='baseline' GROUP BY 1, 2 ORDER BY pillar, mentions DESC;

-- Q7. Model disagreement — each brand's visibility rank within each model.
SELECT brand, model, visibility_pct,
       rank() OVER (PARTITION BY model ORDER BY visibility_pct DESC) AS rank_in_model
FROM v_visibility_by_model WHERE run_id='baseline'
ORDER BY brand, model;

-- Q8. Does any model favor a segment? Share of mentions by segment per model.
SELECT d.label AS model, b.segment,
       round(100.0 * count(*) / sum(count(*)) OVER (PARTITION BY d.label), 1) AS share_pct
FROM fact_mention fm JOIN dim_model d USING (model_key) JOIN dim_brand b USING (brand_id)
WHERE fm.run_id='baseline' GROUP BY 1, 2 ORDER BY model, share_pct DESC;

-- Q9. Citation coverage by model.
SELECT * FROM v_citation_coverage WHERE run_id='baseline' ORDER BY web_pct DESC;

-- Q10. Loved but invisible / visible but meh (sentiment vs visibility, reliable only).
SELECT v.name, v.visibility_pct, s.positive_pct, s.total AS mentions
FROM v_brand_visibility v JOIN v_sentiment_by_brand s USING (run_id, brand_id)
WHERE v.run_id='baseline' AND s.sentiment_reliable
ORDER BY s.positive_pct DESC;

-- Q11. Source ecosystem driving the conversation.
SELECT * FROM v_source_mix WHERE run_id='baseline' ORDER BY citations DESC;

-- Q12/Q13. AI-readiness (llms.txt) by segment, and adoption count.
SELECT segment, count(*) AS brands,
       sum(CASE WHEN has_llms_txt THEN 1 ELSE 0 END) AS with_llms_txt,
       round(avg(visibility_pct), 1) AS avg_visibility
FROM v_ai_readiness WHERE run_id='baseline' GROUP BY segment ORDER BY avg_visibility DESC;
