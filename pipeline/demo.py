"""Generate a clearly-labeled DEMO summary.json so the dashboard renders without
spending any API calls. It synthesizes 120 plausible extracted answers (30
prompts x 4 models) using rough popularity priors, then runs them through the
REAL aggregate + insights(fallback) code — so this also exercises the pipeline.

    python -m pipeline.demo

The result has meta.demo = true and a banner shows in the dashboard.
"""
import json
import random

import config
from pipeline import aggregate, insights, build

# Rough prior "visibility weight" per brand (0..1) — leaders high, niche low.
WEIGHTS = {
    "Techcombank": .82, "VPBank": .77, "Vietcombank": .74, "MB Bank": .65, "BIDV": .57,
    "VietinBank": .51, "ACB": .47, "TPBank": .44, "Sacombank": .40, "HDBank": .38,
    "VIB": .34, "MSB": .30, "SHB": .29, "Agribank": .33, "OCB": .26, "Cake by VPBank": .31,
    "Timo": .28, "SeABank": .22, "Eximbank": .21, "LPBank": .20, "Nam A Bank": .16,
    "HSBC Vietnam": .24, "Shinhan Bank Vietnam": .20, "Standard Chartered Vietnam": .17,
    "UOB Vietnam": .14, "ABBank": .13, "PVcomBank": .11, "BVBank": .12, "VietABank": .09,
    "NCB": .08, "PGBank": .07, "BAC A BANK": .08, "KienlongBank": .07, "Vietbank": .07,
    "CIMB Vietnam": .08, "Woori Bank Vietnam": .07, "Hong Leong Bank Vietnam": .06,
    "OceanBank": .05, "MBV": .05, "KBank Vietnam": .06,
}
EXTRA_DOMAINS = ["vnexpress.net", "cafef.vn", "thebank.vn", "topi.vn", "vietnambiz.vn",
                 "facebook.com", "tinhte.vn", "voz.vn", "sbv.gov.vn", "tuoitre.vn"]


def run():
    rng = random.Random(42)
    brands = json.load(open(config.BRANDS_FILE, encoding="utf-8"))
    prompts = json.load(open(config.PROMPTS_FILE, encoding="utf-8"))
    models = [m["label"] for m in config.ANSWER_MODELS]

    extracted = []
    for p in prompts:
        for model in models:
            mentions = []
            for b in brands:
                w = WEIGHTS.get(b["name"], 0.05)
                # Claude/Gemini amplify leaders a touch; DeepSeek flatter.
                bump = 1.15 if (model in ("Anthropic", "Gemini") and w > .5) else 1.0
                if rng.random() < min(0.95, w * bump):
                    s = rng.choices(["positive", "neutral", "negative"], [0.6, 0.34, 0.06])[0]
                    mentions.append({"brand_id": b["brand_id"], "name": b["name"], "sentiment": s})
            mentions = mentions[:7] or [{"brand_id": 7, "name": "Techcombank", "sentiment": "positive"}]
            cites = []
            for mtn in mentions[:4]:
                bd = next(x["domain"] for x in brands if x["brand_id"] == mtn["brand_id"])
                cites.append({"url": f"https://{bd}/", "domain": bd})
            for _ in range(rng.randint(1, 3)):
                d = rng.choice(EXTRA_DOMAINS)
                cites.append({"url": f"https://{d}/bai-viet", "domain": d})
            extracted.append({
                "prompt_id": p["prompt_id"], "category": p["category"],
                "model_key": model.lower(), "model_label": model,
                "mentions": mentions, "citations": cites,
                "answer": f"[DEMO] Với câu hỏi '{p['text']}', các ngân hàng phù hợp gồm "
                          + ", ".join(m["name"] for m in mentions) + ".",
            })

    agg = aggregate.run(extracted)
    ins = insights._fallback(agg)  # no API spend for the demo
    build.write(build.assemble(agg, ins, demo=True))
    print(f"DEMO report written with {len(extracted)} synthetic answers.")


if __name__ == "__main__":
    run()
