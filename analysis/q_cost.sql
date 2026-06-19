-- Token usage & cost audit. duckdb brandllm.duckdb < analysis/q_cost.sql
-- Requires runs fetched AFTER usage-capture was added (fact_token_usage populated).

-- Per-model token breakdown (input / output / reasoning) per run.
SELECT * FROM v_token_usage ORDER BY run_id, model;

-- Per-model cost (uses data/pricing.json — replace placeholders with real prices).
SELECT * FROM v_cost ORDER BY run_id, total_cost_usd DESC;

-- Total cost per run.
SELECT run_id, round(sum(total_cost_usd), 2) AS run_cost_usd
FROM v_cost GROUP BY run_id ORDER BY run_id;

-- GPT-5.5 only: average tokens per call (incl. reasoning) to sanity-check spend.
SELECT run_id, ok_calls,
       round(input_tokens * 1.0 / ok_calls)     AS avg_input,
       round(output_tokens * 1.0 / ok_calls)    AS avg_output,
       round(reasoning_tokens * 1.0 / ok_calls) AS avg_reasoning
FROM v_token_usage WHERE model_id = 'gpt-5.5' GROUP BY ALL;
