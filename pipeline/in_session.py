"""Load answers produced inside a Claude Code session (no API call).

Used for models flagged `in_session: True` in config.ANSWER_MODELS — e.g. Opus 5.5
answering the 30 prompts directly in a Claude Code session with the same SYSTEM
prompt as run_queries, grounded by the session's own WebSearch tool.

    python -m pipeline.in_session answers.json   # {prompt_id: answer_text}

Writes config.IN_SESSION_FILE; run_queries merges it into raw_answers.json.
Usage is zero (session tokens aren't metered per answer) — cost views will show $0.
"""
import json
import sys

import config


def write(answer_map):
    prompts = json.load(open(config.PROMPTS_FILE, encoding="utf-8"))
    m = next(x for x in config.ANSWER_MODELS if x.get("in_session"))
    rows = []
    for p in prompts:
        text = answer_map.get(str(p["prompt_id"]), "").strip()
        rows.append({
            "prompt_id": p["prompt_id"], "category": p["category"], "prompt": p["text"],
            "model_key": m["key"], "model_label": m["label"], "model": m["model"],
            "answer": text, "status": "ok" if text else "error: missing in-session answer",
            "usage": {"input": 0, "output": 0, "reasoning": 0, "total": 0},
            "source": "claude-code-session",
        })
    json.dump(rows, open(config.IN_SESSION_FILE, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    ok = sum(r["status"] == "ok" for r in rows)
    print(f"Wrote {ok}/{len(rows)} {m['label']} in-session answers -> {config.IN_SESSION_FILE}")
    return rows


if __name__ == "__main__":
    write(json.load(open(sys.argv[1], encoding="utf-8")))
