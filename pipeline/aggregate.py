"""Step 3 — aggregate extracted answers into the report metrics.

Produces the data half of summary.json: ranking, per-model visibility (tidy
long format for small multiples), share of voice, sentiment, source mix,
domain ranking, citation coverage, prompt-level visibility, featured snippets.
"""
import json
import os
import re
import unicodedata
from collections import defaultdict

import config
from pipeline import llms_check


def strip_accents(s):
    return "".join(c for c in unicodedata.normalize("NFD", s or "")
                   if unicodedata.category(c) != "Mn")

SOCIAL = ("facebook.com", "youtube.com", "tiktok.com", "reddit.com", "linkedin.com",
          "twitter.com", "x.com", "instagram.com", "threads.net", "voz.vn", "tinhte.vn")
NEWS = ("vnexpress.net", "tuoitre.vn", "thanhnien.vn", "vietnamnet.vn", "dantri.com.vn",
        "cafef.vn", "vietnambiz.vn", "baodautu.vn", "nhandan.vn", "vneconomy.vn",
        "laodong.vn", "zingnews.vn", "kenh14.vn", "vtv.vn", "tienphong.vn")
GOV = ("sbv.gov.vn", "gov.vn", "mof.gov.vn", "chinhphu.vn")
DIRECTORY = ("topi.vn", "thebank.vn", "webtretho.com", "mogi.vn", "batdongsan.com.vn")
REFERENCE = ("wikipedia.org", "investopedia.com")
EDUCATION = (".edu", ".edu.vn", "ueh.edu.vn")


# Public suffixes (longest first) so registrable label = label before the suffix.
_SUFFIXES = sorted(["com.vn", "net.vn", "org.vn", "edu.vn", "gov.vn", "io.vn",
                    "vn", "com", "net", "org", "co", "io", "ai"], key=len, reverse=True)


def clean_domain(d):
    """Lowercase, strip www and trailing punctuation (fixes 'vib.com.vn,')."""
    d = (d or "").strip().lower().strip(".,;:!?)('\"/")
    return d[4:] if d.startswith("www.") else d


def registrable_label(d):
    """Last label before the public suffix — collapses subdomains.
    portal.vietcombank.com.vn -> 'vietcombank'; techcombank.com -> 'techcombank'."""
    parts = clean_domain(d).split(".")
    for suf in _SUFFIXES:
        sp = suf.split(".")
        if len(parts) > len(sp) and parts[-len(sp):] == sp:
            parts = parts[:-len(sp)]
            break
    return parts[-1] if parts else clean_domain(d)


def build_brand_label_map(brands):
    """label -> brand_id, from each brand's domain + normalized aliases."""
    m = {}
    for b in brands:
        labels = {registrable_label(b["domain"])}
        for a in b["aliases"]:
            labels.add(re.sub(r"[^a-z0-9]", "", strip_accents(a).lower()))
        for L in labels:
            if len(L) >= 2:
                m.setdefault(L, b["brand_id"])
    return m


def resolve_brand_id(domain, label_map):
    """Map a cited domain (incl. subdomains/alt-TLDs) to a brand_id, or None."""
    return label_map.get(registrable_label(domain))


def classify_domain(domain, own_domains, competitor_domains):
    if domain in own_domains:
        return "Own domain"
    if domain in competitor_domains:
        return "Competitor"
    if any(s in domain for s in SOCIAL):
        return "Social"
    if any(s in domain for s in NEWS):
        return "News / Media"
    if any(domain.endswith(s) or s in domain for s in GOV):
        return "Government"
    if any(s in domain for s in DIRECTORY):
        return "Directory / Review"
    if any(s in domain for s in REFERENCE):
        return "Reference"
    if any(s in domain for s in EDUCATION):
        return "Education"
    return "Other"


def pct(n, d):
    return round(100.0 * n / d, 1) if d else 0.0


def run(extracted=None):
    brands = json.load(open(config.BRANDS_FILE, encoding="utf-8"))
    if extracted is None:
        extracted = json.load(open(config.EXTRACTED_FILE, encoding="utf-8"))

    by_id = {b["brand_id"]: b for b in brands}
    own = by_id[config.OWN_BRAND_ID]
    own_domains = {own["domain"]}
    competitor_domains = {b["domain"] for b in brands if b["brand_id"] != config.OWN_BRAND_ID}
    llms = llms_check.ensure()  # AI-readiness: which domains publish llms.txt
    min_n = config.SENTIMENT_MIN_MENTIONS

    models = sorted({r["model_label"] for r in extracted}) or [m["label"] for m in config.ANSWER_MODELS]
    answers_per_model = defaultdict(int)
    for r in extracted:
        answers_per_model[r["model_label"]] += 1
    total_answers = len(extracted)

    # --- mentions / sentiment tallies ---
    seen = defaultdict(int)                       # brand_id -> answers mentioning it
    seen_by_model = defaultdict(lambda: defaultdict(int))   # (brand_id) -> model -> count
    senti = defaultdict(lambda: {"positive": 0, "neutral": 0, "negative": 0})
    total_mentions = 0
    for r in extracted:
        for m in r["mentions"]:
            bid = m["brand_id"]
            seen[bid] += 1
            seen_by_model[bid][r["model_label"]] += 1
            senti[bid][m["sentiment"]] += 1
            total_mentions += 1

    # --- ranking (overall visibility + SoV + sentiment) ---
    ranking = []
    for b in brands:
        bid = b["brand_id"]
        s = senti[bid]
        smt = sum(s.values())
        # Sentiment is only trustworthy with enough mentions; below the floor we
        # keep the raw counts but null the score and flag it unreliable.
        reliable = smt >= min_n
        ranking.append({
            "brand_id": bid, "name": b["name"],
            "is_own": bid == config.OWN_BRAND_ID,
            "visibility_pct": pct(seen[bid], total_answers),
            "sov_pct": pct(seen[bid], total_mentions),
            "mentions": seen[bid],
            "sentiment": s,
            "positive_pct": pct(s["positive"], smt) if reliable else None,
            "sentiment_reliable": reliable,
            "has_llms_txt": llms.get(str(bid), {}).get("has_llms_txt", False),
        })
    ranking.sort(key=lambda x: (-x["visibility_pct"], -x["mentions"], x["name"]))
    for i, row in enumerate(ranking, 1):
        row["rank"] = i

    # --- tidy long format: visibility by brand x model (for facet small-multiples) ---
    visible_ids = [r["brand_id"] for r in ranking if r["mentions"] > 0]
    vis_long = []
    for bid in visible_ids:
        for model in models:
            vis_long.append({
                "brand": by_id[bid]["name"],
                "model": model,
                "visibility_pct": pct(seen_by_model[bid][model], answers_per_model[model] or 1),
            })

    # --- source mix + domain ranking + citation coverage ---
    dom_count = defaultdict(int)
    type_count = defaultdict(int)
    type_domains = defaultdict(set)
    total_citations = 0
    answers_with_url = defaultdict(int)
    for r in extracted:
        if r["citations"]:
            answers_with_url[r["model_label"]] += 1
        for c in r["citations"]:
            d = c["domain"]
            t = classify_domain(d, own_domains, competitor_domains)
            dom_count[d] += 1
            type_count[t] += 1
            type_domains[t].add(d)
            total_citations += 1

    source_mix = [{
        "type": t, "citations": n, "pct": pct(n, total_citations),
        "domains": len(type_domains[t]),
    } for t, n in sorted(type_count.items(), key=lambda kv: -kv[1])]

    domain_ranking = [{
        "domain": d, "citations": n,
        "type": classify_domain(d, own_domains, competitor_domains),
    } for d, n in sorted(dom_count.items(), key=lambda kv: -kv[1])[:20]]

    citation_coverage = [{
        "model": model,
        "web_pct": pct(answers_with_url[model], answers_per_model[model] or 1),
    } for model in models]

    sentiment_by_model = []
    for model in models:
        c = {"positive": 0, "neutral": 0, "negative": 0}
        for r in extracted:
            if r["model_label"] == model:
                for m in r["mentions"]:
                    c[m["sentiment"]] += 1
        tot = sum(c.values()) or 1
        sentiment_by_model.append({
            "model": model, "positive_pct": pct(c["positive"], tot),
            "neutral_pct": pct(c["neutral"], tot), "negative_pct": pct(c["negative"], tot),
        })

    # --- prompt-level gap view ---
    prompts = json.load(open(config.PROMPTS_FILE, encoding="utf-8"))
    pmap = {p["prompt_id"]: p for p in prompts}
    by_prompt = defaultdict(lambda: defaultdict(int))
    for r in extracted:
        for m in r["mentions"]:
            by_prompt[r["prompt_id"]][m["brand_id"]] += 1
    prompt_visibility = []
    for pid, p in pmap.items():
        counts = by_prompt[pid]
        own_n = counts.get(config.OWN_BRAND_ID, 0)
        comps = [(by_id[bid]["name"], n) for bid, n in counts.items()
                 if bid != config.OWN_BRAND_ID]
        comps.sort(key=lambda x: -x[1])
        prompt_visibility.append({
            "prompt_id": pid, "category": p["category"], "prompt": p["text"],
            "own_present": own_n > 0, "own_mentions": own_n,
            "competitors_count": len(comps),
            "top_competitor": comps[0][0] if comps else None,
        })

    featured = _snippets(extracted, own["name"], ranking)

    # --- AI-readiness: llms.txt coverage across the tracked set ---
    ai_readiness = [{
        "brand": r["name"], "rank": r["rank"], "is_own": r["is_own"],
        "visibility_pct": r["visibility_pct"], "has_llms_txt": r["has_llms_txt"],
        "url": llms.get(str(r["brand_id"]), {}).get("detail", {}).get("url"),
    } for r in ranking]
    llms_present = sum(1 for r in ranking if r["has_llms_txt"])

    return {
        "overview": {
            "total_prompts": len(prompts), "total_models": len(models),
            "total_answers": total_answers, "tracked_brands": len(brands),
            "own_brand_id": config.OWN_BRAND_ID, "own_brand": own["name"],
            "models": models, "total_citations": total_citations,
            "sentiment_min_mentions": min_n,
            "llms_txt_present": llms_present,
        },
        "ranking": ranking,
        "visibility_by_brand_model": vis_long,
        "share_of_voice": [{"brand": r["name"], "sov_pct": r["sov_pct"], "is_own": r["is_own"]}
                            for r in ranking if r["mentions"] > 0],
        # Only brands above the reliability floor get a sentiment row.
        "sentiment_by_brand": [{
            "brand": r["name"], "is_own": r["is_own"], "mentions": r["mentions"],
            "positive": r["sentiment"]["positive"], "neutral": r["sentiment"]["neutral"],
            "negative": r["sentiment"]["negative"], "positive_pct": r["positive_pct"],
        } for r in ranking if r["sentiment_reliable"]],
        "sentiment_by_model": sentiment_by_model,
        "source_mix": source_mix,
        "domain_ranking": domain_ranking,
        "citation_coverage": citation_coverage,
        "prompt_visibility": prompt_visibility,
        "ai_readiness": ai_readiness,
        "featured_snippets": featured,
    }


def _snippets(extracted, own_name, ranking):
    top_names = {r["name"] for r in ranking[:6]} | {own_name}
    out = []
    for r in extracted:
        for m in r["mentions"]:
            if m["name"] in top_names:
                for sent in re.split(r"(?<=[.!?\n])\s+", r["answer"]):
                    if m["name"].split()[0].lower() in sent.lower() and 40 < len(sent) < 320:
                        out.append({"model": r["model_label"], "brand": m["name"],
                                    "sentiment": m["sentiment"], "quote": sent.strip()})
                        break
            if len(out) >= 8:
                return out
    return out[:8]


if __name__ == "__main__":
    print(json.dumps(run()["overview"], ensure_ascii=False, indent=2))
