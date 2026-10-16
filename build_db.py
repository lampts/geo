"""Reproducible build of brandllm.duckdb — modeled on paulgp/ipeds-database.

One command rebuilds the analysis-ready DuckDB from cached raw answers:

    uv run python build_db.py                 # ingest latest cached run + (re)build
    uv run python build_db.py --run-id baseline
    uv run python build_db.py --stage analyze # just rebuild views
    uv run python build_db.py --export        # re-export summary.json from views

Stages: ingest (RAW) -> harmonize (CORE dims/facts) -> analyze (MARTS views)
        -> export (report/summary.json for the dashboard).

RAW is immutable and keyed by run_id; metrics live in analysis/views.sql, never
in Python — so re-slicing is a pure SQL re-query, never a re-fetch.
"""
import argparse
import datetime
import json
import os

import duckdb

import config
from pipeline import aggregate  # reuse domain classification (SOCIAL/NEWS/... + classify_domain)

DB_FILE = os.path.join(config.ROOT, "brandllm.duckdb")
VIEWS_SQL = os.path.join(config.ROOT, "analysis", "views.sql")

# Brand segmentation (incumbent | digital | foreign) and parent links.
DIGITAL_IDS = {35, 40, 41, 42, 43}                   # Timo, Cake, Vikki, TNEX, Liobank
FOREIGN_IDS = {21, 30, 31, 32, 33, 34, 36, 39}       # HSBC, Shinhan, UOB, CIMB, Woori, StanChart, HongLeong, KBank
PARENT = {40: "VPBank", 42: "MSB", 41: "HDBank", 43: "OCB"}  # confident parent relationships only


def segment(bid):
    return "digital" if bid in DIGITAL_IDS else "foreign" if bid in FOREIGN_IDS else "incumbent"


# --------------------------------------------------------------------------- #
# schema
# --------------------------------------------------------------------------- #
def ensure_schema(con):
    con.execute("""
    CREATE TABLE IF NOT EXISTS raw_answers (
      run_id VARCHAR, prompt_id INTEGER, model_key VARCHAR, model_id VARCHAR,
      status VARCHAR, answer_text VARCHAR, fetched_at TIMESTAMP);
    CREATE TABLE IF NOT EXISTS raw_extracted (
      run_id VARCHAR, prompt_id INTEGER, model_key VARCHAR, mentions JSON, citations JSON);
    CREATE TABLE IF NOT EXISTS raw_llms_probes (
      run_id VARCHAR, brand_id INTEGER, domain VARCHAR, has_llms_txt BOOLEAN,
      llms_url VARCHAR, http_status INTEGER, bytes INTEGER);

    CREATE TABLE IF NOT EXISTS dim_brand (
      brand_id INTEGER PRIMARY KEY, name VARCHAR, domain VARCHAR, aliases JSON,
      is_own BOOLEAN, parent VARCHAR, segment VARCHAR);
    CREATE TABLE IF NOT EXISTS dim_prompt (
      prompt_id INTEGER PRIMARY KEY, pillar VARCHAR, attribute VARCHAR,
      product VARCHAR, text_vi VARCHAR, text_en VARCHAR);
    CREATE TABLE IF NOT EXISTS dim_model (
      model_key VARCHAR PRIMARY KEY, label VARCHAR, model_id VARCHAR,
      provider VARCHAR, thinking BOOLEAN, search BOOLEAN);
    CREATE TABLE IF NOT EXISTS dim_domain (
      domain VARCHAR PRIMARY KEY, source_type VARCHAR, brand_id INTEGER,
      has_llms_txt BOOLEAN, llms_url VARCHAR);

    CREATE TABLE IF NOT EXISTS fact_answer (
      answer_id VARCHAR, run_id VARCHAR, prompt_id INTEGER, model_key VARCHAR,
      status VARCHAR, answer_text VARCHAR);
    CREATE TABLE IF NOT EXISTS fact_mention (
      answer_id VARCHAR, run_id VARCHAR, prompt_id INTEGER, model_key VARCHAR,
      brand_id INTEGER, sentiment VARCHAR);
    CREATE TABLE IF NOT EXISTS fact_citation (
      answer_id VARCHAR, run_id VARCHAR, url VARCHAR, domain VARCHAR,
      source_type VARCHAR, brand_id INTEGER);
    CREATE TABLE IF NOT EXISTS fact_llms_probe (
      run_id VARCHAR, brand_id INTEGER, domain VARCHAR, has_llms_txt BOOLEAN, llms_url VARCHAR);
    CREATE TABLE IF NOT EXISTS fact_token_usage (
      run_id VARCHAR, prompt_id INTEGER, model_key VARCHAR, status VARCHAR,
      input_tokens INTEGER, output_tokens INTEGER, reasoning_tokens INTEGER, total_tokens INTEGER);
    CREATE TABLE IF NOT EXISTS dim_pricing (
      model_id VARCHAR PRIMARY KEY, input_per_m DOUBLE, output_per_m DOUBLE, search_per_call DOUBLE);
    """)


# --------------------------------------------------------------------------- #
# dims (global current snapshot)
# --------------------------------------------------------------------------- #
def load_dims(con):
    brands = json.load(open(config.BRANDS_FILE, encoding="utf-8"))
    prompts = json.load(open(config.PROMPTS_FILE, encoding="utf-8"))

    con.execute("DELETE FROM dim_brand")
    con.executemany(
        "INSERT INTO dim_brand VALUES (?,?,?,?,?,?,?)",
        [(b["brand_id"], b["name"], b["domain"], json.dumps(b["aliases"], ensure_ascii=False),
          b["brand_id"] == config.OWN_BRAND_ID, PARENT.get(b["brand_id"]), segment(b["brand_id"]))
         for b in brands])

    con.execute("DELETE FROM dim_prompt")
    con.executemany(
        "INSERT INTO dim_prompt VALUES (?,?,?,?,?,?)",
        [(p["prompt_id"], p.get("pillar") or p.get("category"), p.get("attribute", ""),
          p.get("product") or p.get("category"), p.get("text"), p.get("en"))
         for p in prompts])

    con.execute("DELETE FROM dim_model")
    con.executemany(
        "INSERT INTO dim_model VALUES (?,?,?,?,?,?)",
        [(m["key"], m["label"], m["model"], m["key"], m.get("thinking", False), m.get("search", False))
         for m in config.ANSWER_MODELS])

    pricing_file = os.path.join(config.DATA_DIR, "pricing.json")
    if os.path.exists(pricing_file):
        con.execute("DELETE FROM dim_pricing")
        con.executemany("INSERT INTO dim_pricing VALUES (?,?,?,?)",
            [(p["model_id"], p["input_per_m"], p["output_per_m"], p.get("search_per_call", 0.0))
             for p in json.load(open(pricing_file, encoding="utf-8"))["models"]])


def load_domain_dim(con):
    """Built after facts: union of cited domains + brand domains, classified."""
    brands = json.load(open(config.BRANDS_FILE, encoding="utf-8"))
    by_domain = {b["domain"]: b["brand_id"] for b in brands}
    own_domains = {b["domain"] for b in brands if b["brand_id"] == config.OWN_BRAND_ID}
    comp_domains = {b["domain"] for b in brands if b["brand_id"] != config.OWN_BRAND_ID}

    label_map = aggregate.build_brand_label_map(brands)
    cited = [r[0] for r in con.execute("SELECT DISTINCT domain FROM fact_citation").fetchall()]
    llms = {}
    if os.path.exists(config.LLMS_TXT_FILE):
        for v in json.load(open(config.LLMS_TXT_FILE, encoding="utf-8")).values():
            llms[v["domain"]] = v

    con.execute("DELETE FROM dim_domain")
    rows = []
    for dom in sorted(set(cited) | set(by_domain)):
        bid = aggregate.resolve_brand_id(dom, label_map)
        stype = ("Own domain" if bid == config.OWN_BRAND_ID else "Competitor") if bid is not None \
            else aggregate.classify_domain(dom, own_domains, comp_domains)
        det = llms.get(dom, {})
        rows.append((dom, stype, bid,
                     bool(det.get("has_llms_txt")), (det.get("detail") or {}).get("url")))
    con.executemany("INSERT INTO dim_domain VALUES (?,?,?,?,?)", rows)


# --------------------------------------------------------------------------- #
# ingest one run from cached JSON (RAW + facts)
# --------------------------------------------------------------------------- #
def ingest_run(con, run_id):
    answers = json.load(open(config.RAW_ANSWERS_FILE, encoding="utf-8"))
    extracted = json.load(open(config.EXTRACTED_FILE, encoding="utf-8"))
    brands = json.load(open(config.BRANDS_FILE, encoding="utf-8"))
    by_domain = {b["domain"]: b["brand_id"] for b in brands}
    own_domains = {b["domain"] for b in brands if b["brand_id"] == config.OWN_BRAND_ID}
    comp_domains = {b["domain"] for b in brands if b["brand_id"] != config.OWN_BRAND_ID}
    now = datetime.datetime.utcnow()
    aid = lambda a: f"{run_id}|{a['prompt_id']}|{a['model_key']}"

    for t in ("raw_answers", "raw_extracted", "raw_llms_probes",
              "fact_answer", "fact_mention", "fact_citation", "fact_llms_probe", "fact_token_usage"):
        con.execute(f"DELETE FROM {t} WHERE run_id = ?", [run_id])

    # token usage (only present in answers fetched after usage-capture was added)
    tu = []
    for a in answers:
        u = a.get("usage") or {}
        if u:
            tu.append((run_id, a["prompt_id"], a["model_key"], a["status"],
                       u.get("input", 0), u.get("output", 0), u.get("reasoning", 0), u.get("total", 0)))
    if tu:
        con.executemany("INSERT INTO fact_token_usage VALUES (?,?,?,?,?,?,?,?)", tu)

    # RAW + fact_answer
    con.executemany("INSERT INTO raw_answers VALUES (?,?,?,?,?,?,?)",
        [(run_id, a["prompt_id"], a["model_key"], a.get("model"), a["status"], a["answer"], now) for a in answers])
    con.executemany("INSERT INTO fact_answer VALUES (?,?,?,?,?,?)",
        [(aid(a), run_id, a["prompt_id"], a["model_key"], a["status"], a["answer"]) for a in answers])

    # extracted -> raw_extracted + fact_mention + fact_citation
    con.executemany("INSERT INTO raw_extracted VALUES (?,?,?,?,?)",
        [(run_id, e["prompt_id"], e["model_key"],
          json.dumps(e["mentions"], ensure_ascii=False), json.dumps(e["citations"], ensure_ascii=False))
         for e in extracted])

    # registrable-label resolver: maps alt-domains/subdomains to the right brand,
    # collapses them to the brand's canonical domain, fixes trailing punctuation.
    label_map = aggregate.build_brand_label_map(brands)
    canon = {b["brand_id"]: b["domain"] for b in brands}

    ment, cite = [], []
    for e in extracted:
        a_id = f"{run_id}|{e['prompt_id']}|{e['model_key']}"
        for m in e["mentions"]:
            ment.append((a_id, run_id, e["prompt_id"], e["model_key"], m["brand_id"], m["sentiment"]))
        for c in e["citations"]:
            bid = aggregate.resolve_brand_id(c["domain"], label_map)
            if bid is not None:                       # a tracked bank's own site (any variant)
                dom = canon[bid]
                stype = "Own domain" if bid == config.OWN_BRAND_ID else "Competitor"
            else:                                     # third-party source
                dom = aggregate.clean_domain(c["domain"])
                stype = aggregate.classify_domain(dom, own_domains, comp_domains)
            cite.append((a_id, run_id, c["url"], dom, stype, bid))
    con.executemany("INSERT INTO fact_mention VALUES (?,?,?,?,?,?)", ment)
    con.executemany("INSERT INTO fact_citation VALUES (?,?,?,?,?,?)", cite)

    # llms probes
    if os.path.exists(config.LLMS_TXT_FILE):
        probes = json.load(open(config.LLMS_TXT_FILE, encoding="utf-8"))
        rows = [(run_id, v["brand_id"], v["domain"], bool(v["has_llms_txt"]),
                 (v.get("detail") or {}).get("url")) for v in probes.values()]
        con.executemany("INSERT INTO fact_llms_probe VALUES (?,?,?,?,?)", rows)
        praw = [(run_id, v["brand_id"], v["domain"], bool(v["has_llms_txt"]),
                 (v.get("detail") or {}).get("url"), (v.get("detail") or {}).get("status"),
                 (v.get("detail") or {}).get("bytes")) for v in probes.values()]
        con.executemany("INSERT INTO raw_llms_probes VALUES (?,?,?,?,?,?,?)", praw)

    print(f"  ingested run '{run_id}': {len(answers)} answers, {len(ment)} mentions, {len(cite)} citations")


def analyze(con):
    con.execute(open(VIEWS_SQL, encoding="utf-8").read())
    print("  views rebuilt from analysis/views.sql")


# --------------------------------------------------------------------------- #
# export -> report/summary.json (dashboard-compatible)
# --------------------------------------------------------------------------- #
def rows(con, sql, params=None):
    cur = con.execute(sql, params or [])
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, r)) for r in cur.fetchall()]


def export(con, run_id, fresh=False):
    tot = rows(con, "SELECT * FROM v_run_totals WHERE run_id=?", [run_id])[0]
    rk = rows(con, "SELECT * FROM v_brand_visibility WHERE run_id=? ORDER BY rank", [run_id])
    sent = {r["brand_id"]: r for r in rows(con, "SELECT * FROM v_sentiment_by_brand WHERE run_id=?", [run_id])}
    ar = {r["brand_id"]: r for r in rows(con, "SELECT * FROM v_ai_readiness WHERE run_id=?", [run_id])}
    aei = {r["brand_id"]: r for r in rows(con, "SELECT * FROM v_ai_equity WHERE run_id=?", [run_id])}
    models = [r["label"] for r in rows(con, "SELECT label FROM dim_model ORDER BY label")]

    ranking = []
    for r in rk:
        s = sent.get(r["brand_id"], {})
        ranking.append({
            "brand_id": r["brand_id"], "name": r["name"], "is_own": r["is_own"],
            "rank": r["rank"], "visibility_pct": r["visibility_pct"], "sov_pct": r["sov_pct"],
            "mentions": r["mentions"],
            "sentiment": {"positive": s.get("positive", 0), "neutral": s.get("neutral", 0),
                          "negative": s.get("negative", 0)},
            "positive_pct": s.get("positive_pct"),
            "sentiment_reliable": bool(s.get("sentiment_reliable", False)),
            "has_llms_txt": ar.get(r["brand_id"], {}).get("has_llms_txt", False),
            "aei": aei.get(r["brand_id"], {}).get("aei"),
            "aei_band": aei.get(r["brand_id"], {}).get("aei_band"),
        })

    # visibility_by_brand_model: zero-filled for visible brands x models
    visible = [r["name"] for r in ranking if r["mentions"] > 0]
    vbm_rows = rows(con, "SELECT brand, model, visibility_pct FROM v_visibility_by_model WHERE run_id=?", [run_id])
    vbm_map = {(r["brand"], r["model"]): r["visibility_pct"] for r in vbm_rows}
    vbm = [{"brand": b, "model": m, "visibility_pct": vbm_map.get((b, m), 0.0)}
           for b in visible for m in models]

    llms_present = sum(1 for r in ranking if r["has_llms_txt"])
    summary = {
        "meta": {
            "title": config.REPORT_TITLE, "client": config.CLIENT, "topic": config.TOPIC,
            "generated_at": datetime.datetime.utcnow().isoformat() + "Z",
            "answer_models": models, "demo": False, "run_id": run_id, "store": "duckdb",
            "insights_model": None,
        },
        "overview": {
            "total_prompts": con.execute("SELECT count(*) FROM dim_prompt").fetchone()[0],
            "total_models": tot["total_models"], "total_answers": tot["ok_answers"],
            "tracked_brands": con.execute("SELECT count(*) FROM dim_brand").fetchone()[0],
            "own_brand_id": config.OWN_BRAND_ID,
            "own_brand": next(r["name"] for r in ranking if r["is_own"]),
            "models": models,
            "total_citations": con.execute("SELECT count(*) FROM fact_citation WHERE run_id=?", [run_id]).fetchone()[0],
            "sentiment_min_mentions": config.SENTIMENT_MIN_MENTIONS,
            "llms_txt_present": llms_present,
        },
        "ranking": ranking,
        "visibility_by_brand_model": vbm,
        "share_of_voice": [{"brand": r["name"], "sov_pct": r["sov_pct"], "is_own": r["is_own"]}
                            for r in ranking if r["mentions"] > 0],
        "sentiment_by_brand": [{
            "brand": r["name"], "is_own": r["is_own"], "mentions": r["mentions"],
            "positive": r["sentiment"]["positive"], "neutral": r["sentiment"]["neutral"],
            "negative": r["sentiment"]["negative"], "positive_pct": r["positive_pct"],
        } for r in ranking if r["sentiment_reliable"]],
        "sentiment_by_model": rows(con, "SELECT model, positive_pct, neutral_pct, negative_pct FROM v_sentiment_by_model WHERE run_id=? ORDER BY model", [run_id]),
        "source_mix": rows(con, "SELECT type, citations, pct, domains FROM v_source_mix WHERE run_id=? ORDER BY citations DESC", [run_id]),
        "domain_ranking": rows(con, "SELECT domain, citations, type FROM v_domain_ranking WHERE run_id=? ORDER BY citations DESC LIMIT 20", [run_id]),
        "citation_coverage": rows(con, "SELECT model, web_pct FROM v_citation_coverage WHERE run_id=? ORDER BY model", [run_id]),
        "prompt_visibility": [{
            "prompt_id": r["prompt_id"], "category": r["pillar"], "attribute": r["attribute"],
            "product": r["product"], "prompt": r["text_vi"], "own_present": r["own_present"],
            "own_mentions": r["own_mentions"], "competitors_count": r["competitors_count"],
            "top_competitor": r["top_competitor"],
        } for r in rows(con, "SELECT * FROM v_prompt_gap WHERE run_id=? ORDER BY prompt_id", [run_id])],
        "ai_readiness": [{
            "brand": r["name"], "rank": r["rank"], "is_own": r["is_own"],
            "visibility_pct": r["visibility_pct"], "has_llms_txt": r["has_llms_txt"], "url": r["llms_url"],
        } for r in rows(con, "SELECT * FROM v_ai_readiness WHERE run_id=? ORDER BY rank", [run_id])],
        "visibility_by_pillar": [{
            "brand": r["name"], "pillar": r["pillar"], "is_own": r["is_own"],
            "mentions": r["mentions"], "pillar_pct": r["pillar_pct"],
        } for r in rows(con, "SELECT * FROM v_pillar_visibility WHERE run_id=? ORDER BY pillar, mentions DESC", [run_id])],
        "ai_equity": [{
            "brand": r["name"], "is_own": r["is_own"], "segment": r["segment"],
            "aei": r["aei"], "band": r["aei_band"], "rank": r["aei_rank"],
        } for r in rows(con, "SELECT * FROM v_ai_equity WHERE run_id=? AND mentions>0 ORDER BY aei_rank", [run_id])],
    }

    # carry insights + featured snippets from the previous summary.json (no API spend) —
    # only when it is the same run; a new run must not inherit another run's narrative.
    prev = json.load(open(config.SUMMARY_FILE, encoding="utf-8")) if os.path.exists(config.SUMMARY_FILE) else {}
    if not fresh and prev.get("meta", {}).get("run_id") == run_id:
        summary["insights"] = prev.get("insights", {"analysis": [], "at_a_glance": [], "generated_by": "carried-over"})
        summary["meta"]["insights_model"] = prev.get("meta", {}).get("insights_model")
        summary["featured_snippets"] = prev.get("featured_snippets", [])
    else:
        summary["insights"] = {"analysis": [], "at_a_glance": [], "generated_by": "none"}
        summary["featured_snippets"] = aggregate.run()["featured_snippets"]  # from build/extracted.json

    json.dump(summary, open(config.SUMMARY_FILE, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print(f"  exported -> {config.SUMMARY_FILE} (run_id={run_id})")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-id", default="baseline")
    ap.add_argument("--stage", choices=["ingest", "harmonize", "analyze", "export", "all"], default="all")
    ap.add_argument("--export", action="store_true", help="shortcut for --stage export")
    ap.add_argument("--fresh", action="store_true",
                    help="don't carry insights/snippets from the existing summary.json (answers changed)")
    args = ap.parse_args()
    stage = "export" if args.export else args.stage

    con = duckdb.connect(DB_FILE)
    ensure_schema(con)
    if stage in ("ingest", "harmonize", "all"):
        load_dims(con)
        ingest_run(con, args.run_id)
        load_domain_dim(con)
    if stage in ("analyze", "all"):
        analyze(con)
    if stage in ("export", "all"):
        analyze(con)  # ensure views exist
        export(con, args.run_id, fresh=args.fresh)
    con.close()
    print("done.")


if __name__ == "__main__":
    main()
