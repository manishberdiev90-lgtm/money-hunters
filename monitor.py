import time
from . import config
from .db import get, put

def cycle_message(st):
    lines = [f"🔄 Цикл: новых {st['found']}, отсеяно {st['filtered']}, задач {st['tasks']}, черновиков {st['drafts']}, ошибок {st['errors']}"]
    for t in st["new_tasks"][:5]:
        lines.append(f"• #{t['id']} [{t['agent']}] {t['title'][:70]} (≈${t['score']:.0f})")
    if st["disabled"]:
        lines.append("⚠️ Отключены из-за ошибок: " + ", ".join(st["disabled"]) + " (вернуть: /source_on <имя>)")
    if st["tasks"]:
        lines.append("Подробности: /tasks, черновики: /drafts")
    return "\n".join(lines)

def should_send(c, st):
    if st.get("skipped"):
        return False
    mode = get(c, "notify_mode", "events")
    if mode == "quiet":
        return False
    return mode == "all" or bool(st["tasks"] or st["drafts"] or st["errors"] or st["disabled"])

def digest_due(c, now=None):
    local = time.gmtime((now or time.time()) + config.TZ_OFFSET * 3600)
    today = time.strftime("%Y-%m-%d", local)
    if local.tm_hour >= config.DIGEST_HOUR and get(c, "last_digest") != today:
        put(c, "last_digest", today)
        return True
    return False
