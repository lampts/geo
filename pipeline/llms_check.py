"""Check each brand domain for an `llms.txt` file — the emerging convention
(llmstxt.org) where a site publishes guidance for AI agents at /llms.txt.
Presence is an "AI-readiness" signal: a brand that ships llms.txt is actively
steering how models read it, which feeds AI visibility.

For each domain we probe https://<domain>/llms.txt (and /llms-full.txt),
following redirects, and record whether a real text file came back.

    python -m pipeline.llms_check            # writes build/llms_txt.json
"""
import json
import os
import urllib.request
import urllib.error

import config

TIMEOUT = 12
UA = "Mozilla/5.0 (compatible; brandllm-ai-readiness/1.0)"
PATHS = ("llms.txt", "llms-full.txt")


def _probe(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA}, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            ctype = resp.headers.get("Content-Type", "").lower()
            body = resp.read(200_000)
            text = body.decode("utf-8", "replace")
            final = resp.geturl()
            # A real llms.txt is plain text/markdown, not an HTML page or a soft-404.
            looks_html = "<html" in text[:500].lower() or "text/html" in ctype
            ok = (resp.status == 200 and len(body) >= 20 and not looks_html)
            return {"status": resp.status, "bytes": len(body), "final_url": final,
                    "content_type": ctype, "ok": ok}
    except urllib.error.HTTPError as e:
        return {"status": e.code, "bytes": 0, "ok": False}
    except Exception as e:  # noqa: BLE001 - DNS/timeout/TLS
        return {"status": None, "error": str(e)[:120], "ok": False}


def run():
    brands = json.load(open(config.BRANDS_FILE, encoding="utf-8"))
    results = {}
    print(f"Checking llms.txt on {len(brands)} domains")
    for b in brands:
        dom = b["domain"]
        found = None
        for path in PATHS:
            r = _probe(f"https://{dom}/{path}")
            if r.get("ok"):
                found = {**r, "path": path, "url": f"https://{dom}/{path}"}
                break
        results[str(b["brand_id"])] = {
            "brand_id": b["brand_id"], "name": b["name"], "domain": dom,
            "has_llms_txt": bool(found),
            "detail": found or {"ok": False},
        }
        print(f"  {'YES' if found else ' no'}  {dom}")

    os.makedirs(config.BUILD_DIR, exist_ok=True)
    json.dump(results, open(config.LLMS_TXT_FILE, "w", encoding="utf-8"),
              ensure_ascii=False, indent=2)
    n = sum(1 for v in results.values() if v["has_llms_txt"])
    print(f"{n}/{len(brands)} domains publish llms.txt -> {config.LLMS_TXT_FILE}")
    return results


def ensure():
    """Load cached results, fetching once if absent."""
    if os.path.exists(config.LLMS_TXT_FILE):
        return json.load(open(config.LLMS_TXT_FILE, encoding="utf-8"))
    return run()


if __name__ == "__main__":
    run()
