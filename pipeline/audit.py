"""Build the audit logs (JSONL) from the DuckDB CORE tables — so they reflect the
harmonized data (cleaned/canonical citation domains, resolved brands, sentiment
reliability, llms.txt), not the raw extracted JSON.

Writes two files for the chosen run_id (default: the run in report/summary.json):
  build/audit_log.jsonl    one line per (prompt × model): full answer + parsed
                           mentions (brand sentiment-reliability, llms flag) +
                           citations (canonical domain, source type, cited brand).
  build/brand_audit.jsonl  one line per brand: rank, visibility, SoV, mention
                           counts, sentiment split + reliability gate, llms.txt.

    python -m pipeline.audit [run_id]
"""
import json
import os
import sys
from collections import defaultdict

import duckdb

import config

AUDIT_FILE = os.path.join(config.BUILD_DIR, "audit_log.jsonl")
BRAND_AUDIT_FILE = os.path.join(config.BUILD_DIR, "brand_audit.jsonl")


def _rows(con, sql, params):
    cur = con.execute(sql, params)
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, r)) for r in cur.fetchall()]


def run(run_id=None):
    if run_id is None:
        run_id = json.load(open(config.SUMMARY_FILE, encoding="utf-8"))["meta"]["run_id"]
    con = duckdb.connect(config.DUCKDB_FILE, read_only=True)

    # group mentions / citations by answer
    ment = defaultdict(list)
    for r in _rows(con, """
        SELECT fm.answer_id, fm.brand_id, b.name, fm.sentiment,
               (s.total >= 10) AS brand_sentiment_reliable,
               COALESCE(ar.has_llms_txt, FALSE) AS brand_has_llms_txt
        FROM fact_mention fm JOIN dim_brand b USING (brand_id)
        LEFT JOIN v_sentiment_by_brand s ON s.run_id=fm.run_id AND s.brand_id=fm.brand_id
        LEFT JOIN v_ai_readiness ar ON ar.run_id=fm.run_id AND ar.brand_id=fm.brand_id
        WHERE fm.run_id=?""", [run_id]):
        ment[r["answer_id"]].append({
            "brand_id": r["brand_id"], "name": r["name"], "sentiment": r["sentiment"],
            "brand_sentiment_reliable": bool(r["brand_sentiment_reliable"]),
            "brand_has_llms_txt": bool(r["brand_has_llms_txt"])})

    cite = defaultdict(list)
    for r in _rows(con, """
        SELECT c.answer_id, c.url, c.domain, c.source_type, c.brand_id, b.name AS cited_brand
        FROM fact_citation c LEFT JOIN dim_brand b ON b.brand_id=c.brand_id
        WHERE c.run_id=?""", [run_id]):
        cite[r["answer_id"]].append({
            "url": r["url"], "domain": r["domain"], "source_type": r["source_type"],
            "cited_brand": r["cited_brand"]})

    # answer-level audit
    answers = _rows(con, """
        SELECT fa.answer_id, fa.prompt_id, p.pillar, p.attribute, p.product, p.text_vi AS prompt,
               d.label AS model_label, d.model_id AS model, fa.status, fa.answer_text
        FROM fact_answer fa JOIN dim_prompt p USING (prompt_id) JOIN dim_model d USING (model_key)
        WHERE fa.run_id=? ORDER BY fa.prompt_id, d.label""", [run_id])
    arows = []
    for a in answers:
        ms, cs = ment.get(a["answer_id"], []), cite.get(a["answer_id"], [])
        arows.append({
            "run_id": run_id, "prompt_id": a["prompt_id"], "pillar": a["pillar"],
            "attribute": a["attribute"], "product": a["product"], "prompt": a["prompt"],
            "model_label": a["model_label"], "model": a["model"], "status": a["status"],
            "n_mentions": len(ms), "mentions": ms,
            "n_citations": len(cs), "citations": cs,
            "answer": a["answer_text"]})
    _write(AUDIT_FILE, arows)
    print(f"Wrote {len(arows)} answer-audit rows (run={run_id}) -> {AUDIT_FILE}")

    # brand-level audit
    brows = _rows(con, """
        SELECT v.rank, v.brand_id, v.name, v.is_own, v.segment,
               v.visibility_pct, v.sov_pct, v.mentions,
               s.positive, s.neutral, s.negative,
               s.positive_pct, COALESCE(s.sentiment_reliable, FALSE) AS sentiment_reliable,
               ar.has_llms_txt, ar.llms_url
        FROM v_brand_visibility v
        LEFT JOIN v_sentiment_by_brand s ON s.run_id=v.run_id AND s.brand_id=v.brand_id
        LEFT JOIN v_ai_readiness ar ON ar.run_id=v.run_id AND ar.brand_id=v.brand_id
        WHERE v.run_id=? ORDER BY v.rank""", [run_id])
    for b in brows:
        b["sentiment_min_mentions"] = config.SENTIMENT_MIN_MENTIONS
    _write(BRAND_AUDIT_FILE, brows)
    print(f"Wrote {len(brows)} brand-audit rows (run={run_id}) -> {BRAND_AUDIT_FILE}")
    con.close()


def _write(path, rows):
    with open(path, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


if __name__ == "__main__":
    run(sys.argv[1] if len(sys.argv) > 1 else None)
