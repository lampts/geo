"""Uniform access to the four answer providers + the parser/insights models.

Stdlib-only (urllib). Each call returns BOTH the text and a normalized token
`usage` dict {input, output, reasoning, total} so spend is auditable per call:

    ask(provider, model, system, user, env, thinking, search)     -> text
    ask_usage(provider, model, system, user, env, thinking, search) -> (text, usage)

`usage` is normalized across providers (OpenAI/DeepSeek prompt/completion,
Anthropic input/output, Gemini *TokenCount, plus reasoning/thinking where the
API reports it). Missing fields are 0.
"""
import json
import time
import urllib.request
import urllib.error

import config

TIMEOUT = 180
RETRIES = 3


def _post(url, headers, payload):
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")
    last_err = None
    for attempt in range(RETRIES):
        try:
            with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", "replace")
            last_err = f"HTTP {e.code}: {body[:300]}"
            if e.code in (429, 500, 502, 503, 529):
                time.sleep(2 * (attempt + 1))
                continue
            break
        except Exception as e:  # noqa: BLE001
            last_err = str(e)
            time.sleep(2 * (attempt + 1))
    raise RuntimeError(f"request failed: {last_err}")


def _u(inp=0, out=0, reasoning=0):
    return {"input": int(inp or 0), "output": int(out or 0),
            "reasoning": int(reasoning or 0), "total": int((inp or 0) + (out or 0))}


# --- OpenAI (Responses API for reasoning/search; chat otherwise) -------------
def _openai(model, system, user, key, thinking, search, base="https://api.openai.com/v1"):
    reasoning_model = model.startswith(("gpt-5", "o1", "o3", "o4"))
    if thinking or search or reasoning_model:
        body = {"model": model, "instructions": system, "input": user, "max_output_tokens": 4000}
        if search:
            body["tools"] = [{"type": "web_search"}]
        if thinking:
            body["reasoning"] = {"effort": "medium"}
        out = _post(f"{base}/responses",
                    {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}, body)
        u = out.get("usage", {}) or {}
        rt = (u.get("output_tokens_details") or {}).get("reasoning_tokens", 0)
        return _openai_text(out), _u(u.get("input_tokens"), u.get("output_tokens"), rt)
    out = _post(f"{base}/chat/completions",
                {"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
                {"model": model, "temperature": 0.4, "messages": [
                    {"role": "system", "content": system}, {"role": "user", "content": user}]})
    u = out.get("usage", {}) or {}
    return out["choices"][0]["message"]["content"], _u(u.get("prompt_tokens"), u.get("completion_tokens"))


def _openai_text(out):
    if isinstance(out.get("output_text"), str):
        return out["output_text"]
    chunks = []
    for item in out.get("output", []):
        if item.get("type") == "message":
            for c in item.get("content", []):
                if c.get("type") in ("output_text", "text"):
                    chunks.append(c.get("text", ""))
    return "".join(chunks)


def _deepseek(model, system, user, key, thinking, search):
    out = _post("https://api.deepseek.com/chat/completions",
                {"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
                {"model": model, "temperature": 0.4, "messages": [
                    {"role": "system", "content": system}, {"role": "user", "content": user}]})
    u = out.get("usage", {}) or {}
    rt = (u.get("completion_tokens_details") or {}).get("reasoning_tokens", 0)
    return out["choices"][0]["message"]["content"], _u(u.get("prompt_tokens"), u.get("completion_tokens"), rt)


# Models that predate adaptive thinking / dynamic-filtering web search keep the old shapes.
_ANTHROPIC_LEGACY = ("claude-3", "claude-haiku-4-5", "claude-sonnet-4-5", "claude-opus-4-5",
                     "claude-opus-4-1", "claude-opus-4-0", "claude-sonnet-4-0")


def _anthropic(model, system, user, key, thinking, search):
    legacy = model.startswith(_ANTHROPIC_LEGACY)
    body = {"model": model, "max_tokens": 16000, "system": system,
            "messages": [{"role": "user", "content": user}]}
    headers = {"x-api-key": key, "anthropic-version": "2023-06-01", "Content-Type": "application/json"}
    if thinking:
        # 4.6+ use adaptive thinking; budget_tokens is a 400 on Sonnet 5.5 / Opus 5.x.
        body["thinking"] = ({"type": "enabled", "budget_tokens": 4000} if legacy
                            else {"type": "adaptive"})
    if search:
        body["tools"] = [{"type": "web_search_20250305" if legacy else "web_search_20260209",
                          "name": "web_search", "max_uses": 4}]
    if model.startswith("claude-sonnet-5-5"):
        # server-side refusal fallback (routes by refusal category)
        headers["anthropic-beta"] = "server-side-fallback-2026-07-01"
        body["fallbacks"] = "default"
    inp = out_tok = 0
    for _ in range(4):  # server tools may return pause_turn; resend to let the turn finish
        out = _post("https://api.anthropic.com/v1/messages", headers, body)
        u = out.get("usage", {}) or {}
        inp += u.get("input_tokens", 0) or 0
        out_tok += u.get("output_tokens", 0) or 0
        if out.get("stop_reason") != "pause_turn":
            break
        body["messages"] = [body["messages"][0], {"role": "assistant", "content": out["content"]}]
    if out.get("stop_reason") == "refusal":
        cat = (out.get("stop_details") or {}).get("category")
        raise RuntimeError(f"refusal (category={cat})")
    text = "".join(b.get("text", "") for b in out.get("content", []) if b.get("type") == "text")
    # Anthropic counts thinking inside output_tokens.
    return text, _u(inp, out_tok)


def _gemini(model, system, user, key, thinking, search):
    gen = {"temperature": 0.4, "maxOutputTokens": 4000}
    if thinking:
        gen["thinkingConfig"] = {"thinkingBudget": 4000}
    body = {"systemInstruction": {"parts": [{"text": system}]},
            "contents": [{"role": "user", "parts": [{"text": user}]}],
            "generationConfig": gen}
    if search:
        body["tools"] = [{"google_search": {}}]
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={key}"
    out = _post(url, {"Content-Type": "application/json"}, body)
    parts = out["candidates"][0].get("content", {}).get("parts", [])
    text = "".join(p.get("text", "") for p in parts)
    m = out.get("usageMetadata", {}) or {}
    return text, _u(m.get("promptTokenCount"), m.get("candidatesTokenCount"), m.get("thoughtsTokenCount"))


_DISPATCH = {"openai": _openai, "deepseek": _deepseek, "anthropic": _anthropic, "gemini": _gemini}


def ask_usage(provider_key, model, system, user, env_name, thinking=False, search=False):
    key = config.api_key(env_name)
    if not key:
        raise RuntimeError(f"{env_name} not set")
    return _DISPATCH[provider_key](model, system, user, key, thinking, search)


def ask(provider_key, model, system, user, env_name, thinking=False, search=False):
    return ask_usage(provider_key, model, system, user, env_name, thinking, search)[0]
