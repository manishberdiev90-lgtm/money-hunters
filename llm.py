"""ИИ для черновиков. Бесплатные варианты:
 1) GitHub Models (в Actions, через GITHUB_TOKEN, нужен permissions: models: read) — включается автоматически;
 2) любой OpenAI-совместимый API (Groq, OpenRouter, Gemini OpenAI-compat и т.д.): LLM_BASE_URL + LLM_API_KEY + LLM_MODEL.
Если ничего не доступно — drafts.py использует шаблоны."""
import os, json, urllib.request, urllib.error

class LLMError(Exception):
    pass

def settings():
    base, key, model = (os.environ.get(k, "").strip() for k in ("LLM_BASE_URL", "LLM_API_KEY", "LLM_MODEL"))
    if base and key and model:
        return base.rstrip("/"), key, model, {}
    tok = os.environ.get("GITHUB_TOKEN", "").strip()
    if tok and os.environ.get("GITHUB_ACTIONS"):
        return ("https://models.github.ai/inference", tok, model or "openai/gpt-4.1-mini",
                {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"})
    return None

def available():
    return settings() is not None

def complete(system, user, max_tokens=800, timeout=60):
    s = settings()
    if not s:
        return None
    base, key, model, extra = s
    body = json.dumps({"model": model, "max_tokens": max_tokens, "temperature": 0.4,
                       "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]}).encode()
    req = urllib.request.Request(base + "/chat/completions", body,
                                 {"Authorization": f"Bearer {key}", "Content-Type": "application/json", **extra})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            data = json.loads(r.read())
        return (data["choices"][0]["message"]["content"] or "").strip() or None
    except urllib.error.HTTPError as e:
        raise LLMError(f"HTTP {e.code}: {e.read()[:200]!r}")
    except Exception as e:
        raise LLMError(str(e))
