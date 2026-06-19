"""Orchestrator: run the full pipeline and write report/summary.json.

    python -m pipeline.build               # full run (needs API keys)
    python -m pipeline.build --re-extract  # re-parse cached answers (parser only)
    python -m pipeline.build --from-cache  # re-aggregate from build/extracted.json
    python -m pipeline.build --refresh-llms  # also re-fetch llms.txt for every domain

Stages: run_queries -> extract -> llms_check -> aggregate -> insights -> summary.json
"""
import json
import os
import sys
import datetime

import config
from pipeline import run_queries, extract, aggregate, insights, llms_check


def assemble(agg, ins, demo=False):
    return {
        "meta": {
            "title": config.REPORT_TITLE, "client": config.CLIENT, "topic": config.TOPIC,
            "generated_at": datetime.datetime.utcnow().isoformat() + "Z",
            "answer_models": agg["overview"]["models"],
            "insights_model": ins.get("generated_by"),
            "demo": demo,
        },
        "overview": agg["overview"],
        "ranking": agg["ranking"],
        "visibility_by_brand_model": agg["visibility_by_brand_model"],
        "share_of_voice": agg["share_of_voice"],
        "sentiment_by_brand": agg["sentiment_by_brand"],
        "sentiment_by_model": agg["sentiment_by_model"],
        "source_mix": agg["source_mix"],
        "domain_ranking": agg["domain_ranking"],
        "citation_coverage": agg["citation_coverage"],
        "prompt_visibility": agg["prompt_visibility"],
        "ai_readiness": agg["ai_readiness"],
        "insights": ins,
        "featured_snippets": agg["featured_snippets"],
    }


def write(summary):
    os.makedirs(config.REPORT_DIR, exist_ok=True)
    json.dump(summary, open(config.SUMMARY_FILE, "w", encoding="utf-8"),
              ensure_ascii=False, indent=2)
    print(f"Wrote report -> {config.SUMMARY_FILE}")


def main():
    from_cache = "--from-cache" in sys.argv
    re_extract = "--re-extract" in sys.argv
    if not from_cache and not re_extract:
        run_queries.run()       # query the answer models
    if not from_cache:
        extract.run()           # parse cached/just-fetched answers
    if "--refresh-llms" in sys.argv:
        llms_check.run()        # force re-fetch of llms.txt (else aggregate uses cache)
    agg = aggregate.run()
    ins = insights.run(agg)
    write(assemble(agg, ins, demo=False))


if __name__ == "__main__":
    main()
