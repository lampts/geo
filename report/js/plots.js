// Renders the report with Observable Plot — the grammar-of-graphics library that
// is the JS counterpart to Kieran Healy's ggplot2 work. Design choices follow
// his book: Cleveland dot plots instead of bars, small multiples, direct
// labelling, faint gridlines, sorted by value, the own brand picked out in one
// warm colour against a quiet grey field.
import * as Plot from "https://cdn.jsdelivr.net/npm/@observablehq/plot@0.6/+esm";

const OWN = "#c44536", GREY = "#b9b6ad", ACCENT = "#2a6f8e", INK = "#1a1a1a";
const POS = "#4c956c", NEU = "#cbb994", NEG = "#bc4749";
const FONT = "'Source Sans Pro', -apple-system, Segoe UI, Helvetica, Arial, sans-serif";
const base = { style: { background: "transparent", color: INK, fontFamily: FONT, fontSize: "13px" } };

const $ = (id) => document.getElementById(id);
const esc = (s) => String(s).replace(/[&<>]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;" }[c]));

function figure(host, num, title, sub, plot, caption) {
  const f = document.createElement("figure");
  if (host.dataset.narrow) f.className = "narrow";
  f.innerHTML = `<div class="fig-head"><div class="fig-num">Figure ${num}</div>` +
    `<div class="fig-title">${esc(title)}</div><p class="fig-sub">${esc(sub)}</p></div>` +
    `<div class="plot"></div>` + (caption ? `<figcaption>${esc(caption)}</figcaption>` : "");
  f.querySelector(".plot").append(plot);
  host.append(f);
}

export function render(d) {
  // masthead
  $("title").textContent = d.meta.title;
  $("dek").textContent = `${d.meta.topic} · ${d.overview.total_prompts} prompts × ${d.overview.total_models} models = ${d.overview.total_answers} AI answers · ${d.overview.tracked_brands} brands tracked`;
  $("byline").innerHTML = `Answer models: ${d.meta.answer_models.join(", ")} · Insights by <code>${esc(d.meta.insights_model)}</code> · Generated ${d.meta.generated_at.slice(0, 10)}`;
  if (d.meta.demo) $("demoBanner").style.display = "block";

  // own-brand stat strip
  const own = d.ranking.find((r) => r.is_own) || d.ranking[d.ranking.length - 1];
  const ownPos = own.positive_pct == null
    ? [`n/a`, `positive (n<${d.overview.sentiment_min_mentions})`]
    : [`${own.positive_pct}%`, "positive sentiment"];
  $("stats").innerHTML = [
    [own.aei != null ? own.aei : "—", `AEI · ${own.aei_band || "—"}`, true],
    [`#${own.rank}`, `${own.name} rank of ${d.overview.tracked_brands}`, true],
    [`${own.visibility_pct}%`, "AI visibility", false],
    [ownPos[0], ownPos[1], false],
    [own.has_llms_txt ? "yes" : "no", "publishes llms.txt", false],
  ].map(([k, l, o]) => `<div class="stat"><div class="k${o ? " own" : ""}">${k}</div><div class="l">${l}</div></div>`).join("");

  const figs = $("figures");
  const visible = d.ranking.filter((r) => r.mentions > 0);

  // Fig 0 — AI-Equity Index (brand-equity-index-style banded composite), the headline metric
  if (d.ai_equity && d.ai_equity.length) {
    const ae = d.ai_equity.slice(0, 20);
    const maxA = Math.max(...ae.map((r) => r.aei));
    figure(figs, "AEI", "AI-Equity Index (AEI)",
      "A banded composite — reach × sentiment × cross-model consistency × AI-readiness — indexed so 1.0 = category average. Mirrors a brand-health equity index. Bands: >3 Strong · 1–3 Moderate · <1 Weak. Own brand in red.",
      Plot.plot({
        ...base, width: 920, height: 360, marginLeft: 44, marginBottom: 92,
        x: { domain: ae.map((r) => r.brand), label: null, tickRotate: -40 },
        y: { grid: true, label: "AEI (1.0 = category average) ↑", domain: [0, Math.ceil(maxA) + 0.3] },
        marks: [
          Plot.ruleY([1], { stroke: "#b9b6ad", strokeDasharray: "3,3" }),
          Plot.ruleY([3], { stroke: "#b9b6ad", strokeDasharray: "3,3" }),
          Plot.barY(ae, { x: "brand", y: "aei", fill: (r) => r.is_own ? OWN : ACCENT, fillOpacity: 0.9 }),
          Plot.text(ae, { x: "brand", y: "aei", text: (r) => r.aei.toFixed(1), dy: -7, fontSize: 10, fill: INK }),
          Plot.text([{ x: ae[ae.length - 1].brand, y: 3 }], { x: "x", y: "y", text: () => "Strong >3", dy: -5, dx: -4, textAnchor: "end", fontSize: 10, fill: "#8a8a8a" }),
          Plot.text([{ x: ae[ae.length - 1].brand, y: 1 }], { x: "x", y: "y", text: () => "Moderate >1", dy: -5, dx: -4, textAnchor: "end", fontSize: 10, fill: "#8a8a8a" }),
        ],
      }),
      "Composite equity in the AI channel — the analog of a survey Brand-Equity Index. Top 20 shown.");
  }

  // Fig 1 — Cleveland dot plot of overall visibility (the headline ranking)
  figure(figs, 1, "AI Visibility by brand",
    "How often each brand surfaces when AI is asked a relevant banking question. One row per brand, sorted; the own brand is picked out in red.",
    Plot.plot({
      ...base, width: 900, height: 26 * visible.length + 60, marginLeft: 170, marginRight: 40,
      x: { domain: [0, Math.max(...visible.map((r) => r.visibility_pct)) * 1.05], grid: true, label: "Visibility (% of answers) →", tickFormat: (t) => t + "%" },
      y: { domain: visible.map((r) => r.name), label: null },
      marks: [
        Plot.ruleY(visible, { y: "name", x1: 0, x2: "visibility_pct", stroke: (r) => r.is_own ? OWN : "#e0ddd5", strokeWidth: 1.5 }),
        Plot.dot(visible, { y: "name", x: "visibility_pct", fill: (r) => r.is_own ? OWN : ACCENT, r: 4.5 }),
        Plot.text(visible, { y: "name", x: "visibility_pct", text: (r) => r.visibility_pct + "%", dx: 12, fontSize: 11, fill: (r) => r.is_own ? OWN : "#777", textAnchor: "start" }),
      ],
    }),
    "Cleveland dot plot. Length is redundant with position to aid reading; bars are avoided to reduce ink.");

  // Fig 2 — small multiples: visibility of the top brands faceted by model
  const top = visible.slice(0, 12).map((r) => r.name);
  const facetData = d.visibility_by_brand_model.filter((r) => top.includes(r.brand));
  figure(figs, 2, "Visibility across the four models",
    "Small multiples — the same top brands, one panel per model. Reading down a column shows which models amplify or flatten the leaders.",
    Plot.plot({
      ...base, width: 900, height: 30 * top.length + 70, marginLeft: 150, marginRight: 20,
      fx: { label: null }, x: { grid: true, label: null, tickFormat: (t) => t + "%", ticks: 3 },
      y: { domain: top, label: null },
      color: { legend: false },
      marks: [
        Plot.ruleY(facetData, { fx: "model", y: "brand", x1: 0, x2: "visibility_pct", stroke: "#e6e3db" }),
        Plot.dot(facetData, { fx: "model", y: "brand", x: "visibility_pct", fill: (r) => r.brand === own.name ? OWN : ACCENT, r: 3.6 }),
      ],
    }),
    "Faceting holds the scales fixed across panels so cross-model comparison is honest.");

  // Fig 2b — visibility by customer-need pillar (the Home Credit framework lens)
  if (d.visibility_by_pillar && d.visibility_by_pillar.length) {
    const PILLARS = ["Motivator", "Differentiator", "Hygienic", "Low priority"];
    const topP = visible.slice(0, 12).map((r) => r.name);
    const pdata = d.visibility_by_pillar.filter((r) => topP.includes(r.brand));
    figure(figs, "2b", "Visibility by customer-need pillar",
      "Small multiples on the Home Credit attribute pillars — Motivators drive choice, Differentiators set brands apart, Hygienic are table stakes. Normalized within each pillar (pillars hold different numbers of prompts).",
      Plot.plot({
        ...base, width: 920, height: 30 * topP.length + 80, marginLeft: 150, marginRight: 20,
        fx: { label: null, domain: PILLARS }, x: { grid: true, label: null, tickFormat: (t) => t + "%", ticks: 3 },
        y: { domain: topP, label: null },
        marks: [
          Plot.ruleY(pdata, { fx: "pillar", y: "brand", x1: 0, x2: "pillar_pct", stroke: "#e6e3db" }),
          Plot.dot(pdata, { fx: "pillar", y: "brand", x: "pillar_pct", fill: (r) => r.is_own ? OWN : ACCENT, r: 3.6 }),
        ],
      }),
      "Where a brand wins the customer's decision, not just a product category. Own brand in red.");
  }

  // Fig 2c — Cake quadrant: performance (Cake mentions) × competitiveness (rivals)
  if (d.prompt_visibility && d.prompt_visibility.length) {
    const SHORT = {
      "Provides products/services that meet my needs": "meets needs",
      "Has clear and transparent interest rates and fees": "transparent fees",
      "Has easy and convenient repayment": "easy repayment",
      "Is a trustworthy and honest brand": "trustworthy",
      "Has great servicing of customers": "great service",
      "Has fast and easy disbursement/claiming": "fast disbursement",
      "Makes me feel good": "feel good",
      "Has a polite and professional payment collection process": "polite collection",
      "Has fast and easy application process": "fast application",
      "Has great website/mobile/app experience": "great app",
      "Has competitive interest rate and fees": "competitive rate",
      "Is a digital finance company": "digital finance co",
      "Has high approval rate": "high approval",
      "Offers many tenure options": "tenure options",
      "Has products that are easy to find and understand": "easy to understand",
      "Has enough branches in convenient locations": "branches",
      "Offers enticing deals and promotions": "deals/promos",
      "Cares about me and my financial wellbeing": "financial wellbeing",
      "Has many social and financial responsibility activities": "social responsibility",
    };
    const PILL = { Motivator: "#3b6ea5", Differentiator: "#8a5a9e", Hygienic: "#c79a3a", "Low priority": "#9aa0a6" };
    const jit = (n, seed) => n + (((seed * 9301 + 49297) % 233) / 233 - 0.5) * 0.5;
    const q = d.prompt_visibility.map((p) => ({
      ...p,
      label: `${SHORT[p.attribute] || p.attribute} (${p.product})`,
      jx: jit(p.competitors_count, p.prompt_id),
      jy: jit(p.own_mentions, p.prompt_id * 7),
      status: (p.own_mentions === 0 && p.competitors_count > 0) ? "gap"
        : (p.own_mentions >= 2) ? "best" : "mid",
    }));
    const xs = q.map((p) => p.competitors_count).sort((a, b) => a - b);
    const medX = xs[Math.floor(xs.length / 2)];
    const maxX = Math.max(...xs);
    figure(figs, "2c", "Cake's prompt quadrant — strengths vs gaps",
      `Each of the 30 prompts placed by Cake's presence (mentions across 4 models, Y) vs how contested it is (competitor brands AI surfaces, X). Fill = pillar; ring = Cake status: green = strength, red = gap (Cake absent while rivals appear). Split at the median (${medX} competitors) and 2 mentions.`,
      Plot.plot({
        ...base, width: 920, height: 560, marginLeft: 70, marginBottom: 48, marginRight: 30, marginTop: 28,
        x: { domain: [-0.6, maxX + 1], label: "Competitiveness — rival brands AI surfaces →", grid: true },
        y: { domain: [-0.6, 4.6], label: "↑ Cake strength (mentions, of 4 models)", ticks: [0, 1, 2, 3, 4], grid: true },
        color: { domain: Object.keys(PILL), range: Object.values(PILL), legend: true },
        marks: [
          Plot.ruleX([medX + 0.5], { stroke: "#cfcabd", strokeDasharray: "4,4" }),
          Plot.ruleY([1.5], { stroke: "#cfcabd", strokeDasharray: "4,4" }),
          Plot.text([
            { x: maxX + 0.8, y: 4.5, t: "DEFEND ★" }, { x: maxX + 0.8, y: -0.5, t: "IMPROVE ⚠" },
            { x: -0.5, y: 4.5, t: "NICHE WIN" }, { x: -0.5, y: -0.5, t: "LOW PRIORITY" },
          ], { x: "x", y: "y", text: "t", textAnchor: (d) => d.x < 1 ? "start" : "end", fontSize: 11, fontWeight: 700, fill: "#8a8a8a" }),
          Plot.dot(q, { x: "jx", y: "jy", fill: "category", r: 6, fillOpacity: 0.9,
            stroke: (p) => p.status === "gap" ? "#c0392b" : p.status === "best" ? "#2e7d32" : "#ffffff",
            strokeWidth: (p) => p.status === "mid" ? 1 : 2.6 }),
          Plot.text(q, { x: "jx", y: "jy", text: "label", dy: -10, fontSize: 8.5,
            fill: "#444", textAnchor: "middle" }),
        ],
      }),
      "Bottom-right (IMPROVE) = contested prompts where Cake is absent — the priority gaps. Top-right (DEFEND) = contested prompts Cake already wins.");
  }

  // Fig 3 — share of voice lollipop
  const sov = d.share_of_voice.slice(0, 18);
  figure(figs, 3, "Share of voice",
    "Each brand's slice of all tracked mentions — always sums to 100% across the full set.",
    Plot.plot({
      ...base, width: 900, height: 24 * sov.length + 50, marginLeft: 170, marginRight: 40,
      x: { grid: true, label: "Share of mentions (%) →", tickFormat: (t) => t + "%" },
      y: { domain: sov.map((r) => r.brand), label: null },
      marks: [
        Plot.ruleY(sov, { y: "brand", x1: 0, x2: "sov_pct", stroke: "#e0ddd5" }),
        Plot.dot(sov, { y: "brand", x: "sov_pct", fill: (r) => r.is_own ? OWN : ACCENT, r: 4 }),
      ],
    }), "");

  // Fig 4 — sentiment composition (stacked proportions, sorted by positive)
  const senti = d.sentiment_by_brand.slice(0, 18);
  const long = [];
  senti.forEach((r) => {
    const tot = r.positive + r.neutral + r.negative || 1;
    long.push({ brand: r.brand, k: "positive", v: r.positive / tot, is_own: r.is_own });
    long.push({ brand: r.brand, k: "neutral", v: r.neutral / tot });
    long.push({ brand: r.brand, k: "negative", v: r.negative / tot });
  });
  figure(figs, 4, "Sentiment mix by brand",
    `Positive / neutral / negative split of each brand's mentions, ordered by share positive. Brands with fewer than ${d.overview.sentiment_min_mentions} mentions are excluded — too few to score reliably.`,
    Plot.plot({
      ...base, width: 900, height: 24 * senti.length + 60, marginLeft: 170, marginRight: 20,
      x: { label: "Share of mentions →", percent: true, grid: true },
      y: { domain: senti.map((r) => r.brand), label: null },
      color: { domain: ["positive", "neutral", "negative"], range: [POS, NEU, NEG], legend: true },
      marks: [Plot.barX(long, { y: "brand", x: "v", fill: "k", order: ["positive", "neutral", "negative"] })],
    }), "");

  // Fig 5 — source mix
  figure(figs, 5, "Where the answers got their sources",
    "Every cited URL classified by domain type, across all brands.",
    Plot.plot({
      ...base, width: 900, height: 24 * d.source_mix.length + 50, marginLeft: 150, marginRight: 50,
      x: { grid: true, label: "Share of citations (%) →" },
      y: { domain: d.source_mix.map((s) => s.type), label: null },
      marks: [
        Plot.ruleY(d.source_mix, { y: "type", x1: 0, x2: "pct", stroke: "#e0ddd5" }),
        Plot.dot(d.source_mix, { y: "type", x: "pct", fill: ACCENT, r: 4 }),
        Plot.text(d.source_mix, { y: "type", x: "pct", text: (s) => `${s.pct}% · ${s.domains} domains`, dx: 12, textAnchor: "start", fontSize: 11, fill: "#777" }),
      ],
    }), "");

  // Fig 6 — domain ranking
  const dom = d.domain_ranking.slice(0, 15);
  figure(figs, 6, "Most-cited domains",
    "The domains AI leaned on most when answering, coloured by source type.",
    Plot.plot({
      ...base, width: 900, height: 24 * dom.length + 50, marginLeft: 200, marginRight: 40,
      x: { grid: true, label: "Citations →" },
      y: { domain: dom.map((r) => r.domain), label: null },
      color: { legend: true },
      marks: [
        Plot.ruleY(dom, { y: "domain", x1: 0, x2: "citations", stroke: "#e6e3db" }),
        Plot.dot(dom, { y: "domain", x: "citations", fill: "type", r: 4.5 }),
      ],
    }), "");

  // Fig 7 — citation coverage by model
  figure(figs, 7, "Web-backed answers by model",
    "Share of each model's answers that included at least one source URL.",
    Plot.plot({
      ...base, width: 900, height: 200, marginLeft: 110, marginBottom: 40,
      y: { grid: true, label: "% answers with a URL", domain: [0, 100] },
      x: { label: null },
      marks: [
        Plot.barY(d.citation_coverage, { x: "model", y: "web_pct", fill: ACCENT, fillOpacity: 0.85 }),
        Plot.text(d.citation_coverage, { x: "model", y: "web_pct", text: (r) => r.web_pct + "%", dy: -8, fontSize: 12, fill: INK }),
      ],
    }), "Plain chat APIs aren't search engines — coverage reflects URLs the model chose to write, not a live index.");

  // Fig 8 — prompt-level gap map
  const pv = d.prompt_visibility.map((p) => ({ ...p, label: `P${p.prompt_id} · ${p.category}` }));
  figure(figs, 8, "Prompt-level gap map",
    `Each prompt asked on every model. Red marks prompts where the own brand (${own.name}) is absent while competitors are cited.`,
    Plot.plot({
      ...base, width: 900, height: 22 * pv.length + 60, marginLeft: 130, marginRight: 160,
      x: { grid: true, label: "Competitors cited in this prompt →" },
      y: { domain: pv.map((p) => p.label), label: null },
      marks: [
        Plot.ruleY(pv, { y: "label", x1: 0, x2: "competitors_count", stroke: "#e6e3db" }),
        Plot.dot(pv, { y: "label", x: "competitors_count", fill: (p) => p.own_present ? POS : OWN, r: 4 }),
        Plot.text(pv, { y: "label", x: "competitors_count", text: (p) => p.own_present ? `own ✓ (${p.own_mentions})` : `own absent · top: ${p.top_competitor || "—"}`, dx: 12, textAnchor: "start", fontSize: 10.5, fill: (p) => p.own_present ? "#5a7a66" : OWN }),
      ],
    }),
    "Green = own brand present; red = a gap to close. Sorted by prompt id, not value, to keep categories scannable.");

  // Fig 9 — AI-readiness: llms.txt presence vs visibility
  const ar = d.ai_readiness.filter((r) => r.visibility_pct > 0);
  const nLlms = d.overview.llms_txt_present, nBrands = d.overview.tracked_brands;
  figure(figs, 9, "AI-readiness: llms.txt vs visibility",
    `Does each brand's domain publish an llms.txt file — explicit guidance for AI agents (llmstxt.org)? Filled = yes, hollow = no. Only ${nLlms} of ${nBrands} tracked domains do.`,
    Plot.plot({
      ...base, width: 900, height: 24 * ar.length + 60, marginLeft: 170, marginRight: 130,
      x: { grid: true, label: "AI visibility (%) →", tickFormat: (t) => t + "%" },
      y: { domain: ar.map((r) => r.brand), label: null },
      color: { domain: ["Has llms.txt", "No llms.txt"], range: [POS, "#a7a290"], legend: true },
      marks: [
        Plot.ruleY(ar, { y: "brand", x1: 0, x2: "visibility_pct", stroke: "#ececdf" }),
        Plot.dot(ar, { y: "brand", x: "visibility_pct", r: 5,
          fill: (r) => r.has_llms_txt ? "Has llms.txt" : "No llms.txt",
          stroke: (r) => r.is_own ? OWN : null, strokeWidth: 2 }),
        Plot.text(ar.filter((r) => r.has_llms_txt), { y: "brand", x: "visibility_pct", text: () => "llms.txt", dx: 12, textAnchor: "start", fontSize: 10, fill: "#5a7a66" }),
      ],
    }),
    "Publishing llms.txt is a low-cost lever to steer how models read a brand; the own brand is ringed in red.");

  // insights (Opus)
  const ins = d.insights;
  $("insightsSrc").innerHTML = `Generated by <code>${esc(ins.generated_by)}</code> from this report's numbers`;
  $("analysis").innerHTML = (ins.analysis || []).map((a) => `<div class="analysis-item"><h3>${esc(a.heading)}</h3><p>${esc(a.body)}</p></div>`).join("");
  $("glance").innerHTML = `<p class="l">At a glance</p><ul>${(ins.at_a_glance || []).map((b) => `<li>${esc(b)}</li>`).join("")}</ul>`;

  // snippets
  $("snippets").innerHTML = (d.featured_snippets || []).map((s) =>
    `<div class="snippet ${s.sentiment}"><q>${esc(s.quote)}</q><div class="meta"><b>${esc(s.brand)}</b> · ${esc(s.model)} · ${esc(s.sentiment)}</div></div>`).join("");
}
