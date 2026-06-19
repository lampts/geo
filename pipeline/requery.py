"""Re-query a single answer model and patch build/raw_answers.json in place,
leaving the other models' cached answers untouched.

    python -m pipeline.requery openai      # re-run all 30 prompts for GPT-5.5

Useful when one provider failed mid-run (quota/rate limit) but the others are
fine — avoids re-spending on models that already completed.
"""
import json
import sys

import config
from pipeline import providers, run_queries


def run(model_key):
    m = next((x for x in config.ANSWER_MODELS if x["key"] == model_key), None)
    if not m:
        raise SystemExit(f"unknown model key '{model_key}'. "
                         f"choices: {[x['key'] for x in config.ANSWER_MODELS]}")
    prompts = json.load(open(config.PROMPTS_FILE, encoding="utf-8"))
    answers = json.load(open(config.RAW_ANSWERS_FILE, encoding="utf-8"))
    # drop this model's old rows
    answers = [a for a in answers if a["model_key"] != m["key"]]

    print(f"Re-querying {m['label']} ({m['model']}) on {len(prompts)} prompts")
    ok = 0
    for p in prompts:
        usage = {"input": 0, "output": 0, "reasoning": 0, "total": 0}
        try:
            text, usage = providers.ask_usage(m["key"], m["model"], run_queries.SYSTEM, p["text"], m["env"],
                                 thinking=m.get("thinking", False), search=m.get("search", False))
            status = "ok"; ok += 1
        except Exception as e:  # noqa: BLE001
            text, status = "", f"error: {e}"
            print(f"  ! prompt {p['prompt_id']}: {status[:120]}")
        answers.append({
            "prompt_id": p["prompt_id"], "category": p["category"], "prompt": p["text"],
            "model_key": m["key"], "model_label": m["label"], "model": m["model"],
            "answer": text, "status": status, "usage": usage,
        })
        print(f"  prompt {p['prompt_id']}/{len(prompts)} done")

    answers.sort(key=lambda a: (a["prompt_id"], a["model_key"]))
    json.dump(answers, open(config.RAW_ANSWERS_FILE, "w", encoding="utf-8"),
              ensure_ascii=False, indent=2)
    print(f"Patched {m['label']}: {ok}/{len(prompts)} ok -> {config.RAW_ANSWERS_FILE}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        raise SystemExit("usage: python -m pipeline.requery <model_key>")
    run(sys.argv[1])
