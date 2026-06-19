"""Step 4 — Opus 4.8 writes the narrative insights from the aggregated metrics.

Feeds a compact JSON digest of the numbers to claude-opus-4-8 and asks for
Vietnamese analysis sections + an at-a-glance bullet list, matching the source
report's voice. Falls back to a deterministic write-up if ANTHROPIC_API_KEY
is absent, so the pipeline always produces a complete report.
"""
import json

import config
from pipeline import providers

SYSTEM = (
    "Bạn là nhà phân tích thương hiệu chuyên về mức độ hiển thị trên các công cụ AI. "
    "Viết bằng tiếng Việt, súc tích, dựa hoàn toàn trên số liệu được cung cấp, không bịa. "
    "Trả về JSON đúng schema yêu cầu."
)

SCHEMA_HINT = (
    'Trả về JSON: {"analysis":[{"heading":"...","body":"..."}],'
    '"at_a_glance":["...","..."]}. '
    "analysis gồm 4-5 mục (tổng quan cạnh tranh, khác biệt theo mô hình AI, "
    "cảm xúc thương hiệu, nguồn & ảnh hưởng, vị thế thương hiệu own). "
    "at_a_glance gồm 5-6 gạch đầu dòng ngắn, mỗi dòng một con số cụ thể. "
    "Thêm một mục phân tích về 'AI-readiness (llms.txt)' dựa trên dữ liệu ai_readiness."
)


def _digest(agg):
    top = agg["ranking"][:8]
    own = next((r for r in agg["ranking"] if r["is_own"]), None)
    return {
        "own_brand": agg["overview"]["own_brand"],
        "totals": agg["overview"],
        "sentiment_note": (f"positive_pct is null when a brand has fewer than "
                           f"{agg['overview']['sentiment_min_mentions']} mentions "
                           f"(too few to be reliable) — do not invent a score for those."),
        "top_brands": [{"name": r["name"], "visibility_pct": r["visibility_pct"],
                        "sov_pct": r["sov_pct"], "positive_pct": r["positive_pct"],
                        "has_llms_txt": r["has_llms_txt"]} for r in top],
        "own_brand_stats": own,
        "sentiment_by_model": agg["sentiment_by_model"],
        "citation_coverage": agg["citation_coverage"],
        "source_mix": agg["source_mix"][:5],
        "top_domains": agg["domain_ranking"][:6],
        "ai_readiness": {
            "llms_txt_present": agg["overview"]["llms_txt_present"],
            "tracked_brands": agg["overview"]["tracked_brands"],
            "own_has_llms_txt": own["has_llms_txt"] if own else False,
        },
    }


def run(agg):
    digest = _digest(agg)
    if config.api_key(config.INSIGHTS["env"]):
        try:
            user = ("Số liệu báo cáo (JSON):\n"
                    + json.dumps(digest, ensure_ascii=False) + "\n\n" + SCHEMA_HINT)
            raw = providers.ask(config.INSIGHTS["key"], config.INSIGHTS["model"],
                                SYSTEM, user, config.INSIGHTS["env"])
            raw = raw.strip()
            if raw.startswith("```"):  # strip ```json ... ``` fences
                raw = raw.split("```")[1]
                raw = raw[4:] if raw.lower().startswith("json") else raw
            start, end = raw.find("{"), raw.rfind("}")
            data = json.loads(raw[start:end + 1])
            data["generated_by"] = config.INSIGHTS["model"]
            return data
        except Exception as e:  # noqa: BLE001
            print(f"  ! insights model failed ({e}); using deterministic fallback")
    return _fallback(agg)


def _fallback(agg):
    r = agg["ranking"]
    own = next((x for x in r if x["is_own"]), r[-1])
    leader = r[0]
    top5 = ", ".join(f"{x['name']} ({x['visibility_pct']}%)" for x in r[:5])
    cov = agg["citation_coverage"]
    avg_web = round(sum(c["web_pct"] for c in cov) / max(len(cov), 1), 1)
    src = agg["source_mix"][0] if agg["source_mix"] else {"type": "—", "pct": 0}
    own_pos = (f"{own['positive_pct']}% đề cập tích cực" if own["positive_pct"] is not None
               else f"cảm xúc chưa đủ dữ liệu (chỉ {own['mentions']} đề cập, "
                     f"ngưỡng {agg['overview']['sentiment_min_mentions']})")
    n_llms = agg["overview"]["llms_txt_present"]
    n_brands = agg["overview"]["tracked_brands"]
    own_llms = "có" if own["has_llms_txt"] else "chưa có"
    return {
        "analysis": [
            {"heading": "Bức tranh cạnh tranh tổng thể",
             "body": f"Trong {agg['overview']['total_answers']} phản hồi AI cho các truy vấn về "
                     f"sản phẩm/dịch vụ ngân hàng tại Việt Nam, {leader['name']} dẫn đầu với "
                     f"{leader['visibility_pct']}% hiển thị và {leader['sov_pct']}% share of voice. "
                     f"Nhóm dẫn đầu gồm: {top5}."},
            {"heading": f"Vị thế thương hiệu {own['name']}",
             "body": f"{own['name']} đạt {own['visibility_pct']}% hiển thị (hạng #{own['rank']}/"
                     f"{n_brands}), {own['sov_pct']}% share of voice và {own_pos}."},
            {"heading": "Nguồn và ảnh hưởng",
             "body": f"Tổng cộng {agg['overview']['total_citations']} trích dẫn được phân loại; "
                     f"nhóm nguồn lớn nhất là '{src['type']}' chiếm {src['pct']}%. "
                     f"Tỷ lệ phản hồi có dẫn nguồn web trung bình {avg_web}%."},
            {"heading": "AI-readiness (llms.txt)",
             "body": f"Chỉ {n_llms}/{n_brands} domain ngân hàng công bố tệp llms.txt để hướng dẫn "
                     f"AI agent. {own['name']} hiện {own_llms} llms.txt — đây là đòn bẩy "
                     f"chi phí thấp để cải thiện cách AI đọc và trích dẫn thương hiệu."},
        ],
        "at_a_glance": [
            f"{leader['name']} dẫn đầu với {leader['visibility_pct']}% hiển thị.",
            f"{own['name']} xếp hạng #{own['rank']} với {own['visibility_pct']}% hiển thị.",
            f"Tổng {agg['overview']['total_citations']} trích dẫn từ {len(agg['domain_ranking'])}+ domain.",
            f"Nguồn '{src['type']}' chiếm {src['pct']}% tổng trích dẫn.",
            f"Chỉ {n_llms}/{n_brands} domain có llms.txt.",
        ],
        "generated_by": "deterministic-fallback",
    }


# --------------------------------------------------------------------------- #
# Refresh insights from an exported summary.json (AEI + pillar + quadrant aware)
# --------------------------------------------------------------------------- #
REFRESH_SYSTEM = (
    "Bạn là nhà phân tích thương hiệu cho kênh AI (AI visibility). Viết bằng tiếng Việt, "
    "súc tích, chỉ dựa trên số liệu được cung cấp, không bịa số. Trả về JSON đúng schema."
)
REFRESH_HINT = (
    'Trả về JSON: {"analysis":[{"heading":"...","body":"..."}],"at_a_glance":["..."]}. '
    "analysis gồm đúng 5 mục theo thứ tự: "
    "(1) Chỉ số AEI tổng thể (nêu AEI, band, hạng tổng và hạng trong nhóm ngân hàng số); "
    "(2) Theo trụ cột nhu cầu khách hàng — nêu trụ cột mạnh nhất và yếu nhất của thương hiệu, "
    "nhấn mạnh khoảng trống ở nhóm Motivator (nhóm quyết định lựa chọn); "
    "(3) Ma trận điểm mạnh vs cần cải thiện — liệt kê 3-4 'điểm cần cải thiện' (IMPROVE: prompt cạnh tranh cao "
    "nhưng thương hiệu vắng mặt) và 2-3 'điểm mạnh' (DEFEND); "
    "(4) Vị thế trong nhóm ngân hàng số (so với các đối thủ digital); "
    "(5) Nguồn & AI-readiness (llms.txt, mức độ được trích dẫn). "
    "at_a_glance gồm 5-6 gạch đầu dòng ngắn, mỗi dòng một con số cụ thể."
)


def _digest_from_summary(s):
    rk = s["ranking"]
    own = next(r for r in rk if r["is_own"])
    ae = s.get("ai_equity", [])
    digital = [a for a in ae if a["segment"] == "digital"]
    own_digital_rank = next((i + 1 for i, a in enumerate(digital) if a["is_own"]), None)
    pil = {p["pillar"]: p["pillar_pct"] for p in s.get("visibility_by_pillar", []) if p["is_own"]}
    pv = s.get("prompt_visibility", [])
    xs = sorted(p["competitors_count"] for p in pv)
    medx = xs[len(xs) // 2] if xs else 0

    def quad(p):
        strong, contested = p["own_mentions"] >= 2, p["competitors_count"] >= medx
        return ("DEFEND" if strong and contested else "IMPROVE" if contested
                else "NICHE" if strong else "LOW")
    improve = [f"{p['attribute']} ({p['product']})" for p in pv if quad(p) == "IMPROVE"]
    defend = [f"{p['attribute']} ({p['product']})" for p in pv if quad(p) == "DEFEND"]
    return {
        "own_brand": own["name"],
        "own": {"rank": own["rank"], "visibility_pct": own["visibility_pct"],
                "sov_pct": own["sov_pct"], "positive_pct": own["positive_pct"],
                "aei": own.get("aei"), "aei_band": own.get("aei_band"),
                "has_llms_txt": own.get("has_llms_txt"), "mentions": own["mentions"]},
        "own_digital_rank": own_digital_rank, "digital_cohort": digital[:6],
        "top_brands_aei": ae[:6],
        "own_pillar_visibility_pct": pil,
        "improve_prompts": improve, "defend_prompts": defend,
        "totals": s["overview"],
    }


def refresh_summary():
    s = json.load(open(config.SUMMARY_FILE, encoding="utf-8"))
    digest = _digest_from_summary(s)
    if not config.api_key(config.INSIGHTS["env"]):
        raise SystemExit("ANTHROPIC key not set; cannot refresh insights.")
    user = "Số liệu báo cáo (JSON):\n" + json.dumps(digest, ensure_ascii=False) + "\n\n" + REFRESH_HINT
    raw = providers.ask(config.INSIGHTS["key"], config.INSIGHTS["model"], REFRESH_SYSTEM, user, config.INSIGHTS["env"])
    raw = raw.strip()
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        raw = raw[4:] if raw.lower().startswith("json") else raw
    data = json.loads(raw[raw.find("{"):raw.rfind("}") + 1])
    data["generated_by"] = config.INSIGHTS["model"]
    s["insights"] = data
    s["meta"]["insights_model"] = data["generated_by"]
    json.dump(s, open(config.SUMMARY_FILE, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print(f"Refreshed insights via {data['generated_by']} -> {config.SUMMARY_FILE}")
    for a in data["analysis"]:
        print("  -", a["heading"])


if __name__ == "__main__":
    import sys
    if "--refresh" in sys.argv:
        refresh_summary()
    else:
        from pipeline import aggregate
        print(json.dumps(run(aggregate.run()), ensure_ascii=False, indent=2))
