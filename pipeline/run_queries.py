"""Step 1 — ask all 30 prompts on every available model (30 x 4 = 120 answers).

System prompt asks the model to answer as a Vietnamese banking consumer would
expect, naming specific banks and citing source URLs where possible — so the
downstream parser has both brand mentions and citations to work with.
"""
import json
import os

import config
from pipeline import providers

SYSTEM = (
    "Bạn là trợ lý tài chính am hiểu thị trường ngân hàng Việt Nam. "
    "Trả lời ngắn gọn, thực tế, nêu tên cụ thể các ngân hàng phù hợp và lý do. "
    "Nếu có thể, dẫn nguồn bằng URL đầy đủ (ví dụ trang chính thức hoặc bài báo). "
    "Answer in Vietnamese."
)


def run():
    prompts = json.load(open(config.PROMPTS_FILE, encoding="utf-8"))
    models = config.available_models()
    if not models:
        raise SystemExit("No API keys set. Export at least one of: "
                         + ", ".join(m["env"] for m in config.ANSWER_MODELS))
    print(f"Running {len(prompts)} prompts x {len(models)} models "
          f"= {len(prompts) * len(models)} answers")

    answers = []
    for p in prompts:
        for m in models:
            usage = {"input": 0, "output": 0, "reasoning": 0, "total": 0}
            try:
                text, usage = providers.ask_usage(m["key"], m["model"], SYSTEM, p["text"], m["env"],
                                     thinking=m.get("thinking", False), search=m.get("search", False))
                status = "ok"
            except Exception as e:  # noqa: BLE001
                text, status = "", f"error: {e}"
                print(f"  ! {m['label']} / prompt {p['prompt_id']}: {status}")
            answers.append({
                "prompt_id": p["prompt_id"], "category": p["category"], "prompt": p["text"],
                "model_key": m["key"], "model_label": m["label"], "model": m["model"],
                "answer": text, "status": status, "usage": usage,
            })
        print(f"  prompt {p['prompt_id']}/{len(prompts)} done")

    os.makedirs(config.BUILD_DIR, exist_ok=True)
    json.dump(answers, open(config.RAW_ANSWERS_FILE, "w", encoding="utf-8"),
              ensure_ascii=False, indent=2)
    print(f"Wrote {len(answers)} answers -> {config.RAW_ANSWERS_FILE}")
    return answers


if __name__ == "__main__":
    run()
