"""Step 2 — parse each answer into mentions + citations + sentiment.

- Mentions: deterministic, diacritic-insensitive alias matching (reproducible).
- Citations: URL regex over the answer text.
- Sentiment: one parser-LLM call per answer, scoring each matched brand
  positive / neutral / negative. Falls back to neutral if no parser key.
"""
import json
import re
import unicodedata

import config
from pipeline import providers

URL_RE = re.compile(r"https?://[^\s)\]}>\"']+", re.I)


def strip_accents(s):
    nfkd = unicodedata.normalize("NFD", s)
    return "".join(c for c in nfkd if unicodedata.category(c) != "Mn")


def norm(s):
    return re.sub(r"\s+", " ", strip_accents(s).lower()).strip()


def build_matchers(brands):
    """For each brand, a list of compiled word-boundary regexes over normalized text."""
    matchers = {}
    for b in brands:
        pats = []
        for alias in b["aliases"]:
            a = re.escape(norm(alias))
            pats.append(re.compile(rf"(?<![a-z0-9]){a}(?![a-z0-9])"))
        matchers[b["brand_id"]] = pats
    return matchers


def find_mentions(text, brands, matchers):
    ntext = norm(text)
    hits = []
    for b in brands:
        if any(p.search(ntext) for p in matchers[b["brand_id"]]):
            hits.append(b)
    return hits


def domain_of(url):
    m = re.match(r"https?://([^/]+)", url, re.I)
    host = (m.group(1) if m else url).lower()
    return host[4:] if host.startswith("www.") else host


def sentiment_for(answer, brand_names):
    """Returns {brand_name: 'positive'|'neutral'|'negative'}; neutral on any failure."""
    default = {n: "neutral" for n in brand_names}
    if not config.api_key(config.PARSER["env"]) or not brand_names:
        return default
    sys = ("You label brand sentiment in a text. Reply ONLY with compact JSON "
           "mapping each given brand to one of: positive, neutral, negative.")
    user = (f"Brands: {json.dumps(brand_names, ensure_ascii=False)}\n\n"
            f"Text:\n{answer[:6000]}\n\n"
            'JSON like {"BrandA":"positive"}.')
    try:
        raw = providers.ask(config.PARSER["key"], config.PARSER["model"], sys, user,
                            config.PARSER["env"])
        blob = re.search(r"\{.*\}", raw, re.S)
        data = json.loads(blob.group(0)) if blob else {}
        out = {}
        for n in brand_names:
            v = str(data.get(n, "neutral")).lower()
            out[n] = v if v in ("positive", "neutral", "negative") else "neutral"
        return out
    except Exception:  # noqa: BLE001
        return default


def run():
    brands = json.load(open(config.BRANDS_FILE, encoding="utf-8"))
    answers = json.load(open(config.RAW_ANSWERS_FILE, encoding="utf-8"))
    matchers = build_matchers(brands)

    rows = []
    for i, a in enumerate(answers):
        if a.get("status") != "ok" or not a.get("answer"):
            continue
        mentioned = find_mentions(a["answer"], brands, matchers)
        names = [b["name"] for b in mentioned]
        senti = sentiment_for(a["answer"], names)
        urls = URL_RE.findall(a["answer"])
        rows.append({
            "prompt_id": a["prompt_id"], "category": a["category"],
            "model_key": a["model_key"], "model_label": a["model_label"],
            "mentions": [{"brand_id": b["brand_id"], "name": b["name"],
                          "sentiment": senti.get(b["name"], "neutral")} for b in mentioned],
            "citations": [{"url": u, "domain": domain_of(u)} for u in urls],
            "answer": a["answer"],
        })
        if (i + 1) % 10 == 0:
            print(f"  extracted {i + 1}/{len(answers)}")

    json.dump(rows, open(config.EXTRACTED_FILE, "w", encoding="utf-8"),
              ensure_ascii=False, indent=2)
    print(f"Wrote {len(rows)} extracted answers -> {config.EXTRACTED_FILE}")
    return rows


if __name__ == "__main__":
    run()
