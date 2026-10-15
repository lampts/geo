"""Step 1 — ask all 30 prompts on every available model (30 x 4 = 120 answers).

System prompt asks the model to answer as a Vietnamese banking consumer would
expect, naming specific banks and citing source URLs where possible — so the
downstream parser has both brand mentions and citations to work with.
"""
import json
import os
import sys

import config
from pipeline import providers

SYSTEM = (
    "Bạn là trợ lý tài chính am hiểu thị trường ngân hàng Việt Nam. "
    "Trả lời ngắn gọn, thực tế, nêu tên cụ thể các ngân hàng phù hợp và lý do. "
    "Nếu có thể, dẫn nguồn bằng URL đầy đủ (ví dụ trang chính thức hoặc bài báo). "
    "Answer in Vietnamese."
)


def _ask(m, p):
    """Ask one prompt; on an unknown-model error retry once with `fallback_model`."""
    try:
        return m["model"], providers.ask_usage(m["key"], m["model"], SYSTEM, p["text"], m["env"],
                                               thinking=m.get("thinking", False), search=m.get("search", False))
    except Exception as e:  # noqa: BLE001
        fb = m.get("fallback_model")
        if not fb or not any(s in str(e) for s in ("404", "model_not_found", "does not exist", "invalid model")):
            raise
        print(f"  ~ {m['label']}: {m['model']} rejected, falling back to {fb}")
        m["model"] = fb  # stick with the fallback for the rest of the run
        return fb, providers.ask_usage(m["key"], fb, SYSTEM, p["text"], m["env"],
                                       thinking=m.get("thinking", False), search=m.get("search", False))


def load_in_session(prompts):
    """Answers produced inside a Claude Code session (see pipeline/in_session.py)."""
    if not os.path.exists(config.IN_SESSION_FILE):
        return []
    rows = json.load(open(config.IN_SESSION_FILE, encoding="utf-8"))
    by_id = {p["prompt_id"]: p for p in prompts}
    return [r for r in rows if r["prompt_id"] in by_id]


def run(only=None):
    """only: optional set of model keys to (re)query; others keep their cached answers."""
    prompts = json.load(open(config.PROMPTS_FILE, encoding="utf-8"))
    models = [m for m in config.available_models() if not only or m["key"] in only]
    in_session = [m for m in config.ANSWER_MODELS if m.get("in_session")]
    if not models and not in_session:
        raise SystemExit("No API keys set. Export at least one of: "
                         + ", ".join(m["env"] for m in config.ANSWER_MODELS if m["env"]))
    missing = [m["label"] for m in config.ANSWER_MODELS
               if not m.get("in_session") and not config.api_key(m["env"])]
    if missing:
        print(f"  (skipping, no key: {', '.join(missing)})")
    print(f"Running {len(prompts)} prompts x {len(models)} API models "
          f"= {len(prompts) * len(models)} answers")

    answers = []
    for p in prompts:
        for m in models:
            usage = {"input": 0, "output": 0, "reasoning": 0, "total": 0}
            model_id = m["model"]
            try:
                model_id, (text, usage) = _ask(m, p)
                status = "ok"
            except Exception as e:  # noqa: BLE001
                text, status = "", f"error: {e}"
                print(f"  ! {m['label']} / prompt {p['prompt_id']}: {status}")
            answers.append({
                "prompt_id": p["prompt_id"], "category": p["category"], "prompt": p["text"],
                "model_key": m["key"], "model_label": m["label"], "model": model_id,
                "answer": text, "status": status, "usage": usage,
            })
        print(f"  prompt {p['prompt_id']}/{len(prompts)} done")

    sess = load_in_session(prompts)
    print(f"  + {len(sess)} in-session answers ({', '.join(m['label'] for m in in_session)})")
    answers += sess

    if only and os.path.exists(config.RAW_ANSWERS_FILE):
        # keep cached answers for current-config models we didn't re-query this time
        # (labels guard against carrying over answers from a previous model generation)
        queried = {m["key"] for m in models} | {m["key"] for m in in_session}
        current = {m["label"] for m in config.ANSWER_MODELS}
        keep = [a for a in json.load(open(config.RAW_ANSWERS_FILE, encoding="utf-8"))
                if a["model_key"] not in queried and a["model_label"] in current]
        answers = keep + answers

    os.makedirs(config.BUILD_DIR, exist_ok=True)
    json.dump(answers, open(config.RAW_ANSWERS_FILE, "w", encoding="utf-8"),
              ensure_ascii=False, indent=2)
    print(f"Wrote {len(answers)} answers -> {config.RAW_ANSWERS_FILE}")
    return answers


if __name__ == "__main__":
    # python -m pipeline.run_queries [--only gemini,openai]
    only = None
    if "--only" in sys.argv:
        only = set(sys.argv[sys.argv.index("--only") + 1].split(","))
    run(only)
