"""Telegram-панель. Отвечает только владельцу (TELEGRAM_OWNER_ID). Через getUpdates: подходит для запуска по расписанию."""
import json, time, urllib.request, urllib.parse, urllib.error
from . import config, finance, agents, improve, drafts, sources as src_mod
from .db import get, put, err, log

def api(method, **params):
    if not config.TOKEN:
        raise RuntimeError("TELEGRAM_BOT_TOKEN не задан")
    data = urllib.parse.urlencode(params).encode()
    try:
        with urllib.request.urlopen(f"https://api.telegram.org/bot{config.TOKEN}/{method}", data, timeout=30) as r:
            d = json.loads(r.read())
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"Telegram HTTP {e.code}: {e.read()[:200]!r}")
    if not d.get("ok"):
        raise RuntimeError(f"Telegram: {str(d)[:200]}")
    return d

def send(text, chat_id=None):
    chat_id = chat_id or config.OWNER
    if not (config.TOKEN and chat_id):
        return
    text = text or "(пусто)"
    for i in range(0, len(text), 3800):
        api("sendMessage", chat_id=chat_id, text=text[i:i + 3800], disable_web_page_preview="true")

def usd(x): return f"${x:,.2f}"
def _n(c, q, *a): return c.execute(q, a).fetchone()[0]
def _ago(ts): return "никогда" if not ts else f"{int((time.time() - ts) / 60)} мин назад"

# ---------- команды ----------
def cmd_status(c, a):
    f = finance.summary(c)
    cyc = c.execute("SELECT * FROM cycles ORDER BY id DESC LIMIT 1").fetchone()
    off = _n(c, "SELECT COUNT(*) FROM source_health WHERE disabled=1")
    return (f"{'⏸ ПАУЗА' if get(c, 'paused') == '1' else '▶️ Работает'}\n"
            f"Агентов: {_n(c, 'SELECT COUNT(*) FROM agents')} | Источников отключено: {off}\n"
            f"Возможностей: {_n(c, 'SELECT COUNT(*) FROM opportunities')} | задач ждут вас: {_n(c, 'SELECT COUNT(*) FROM tasks WHERE status=?', 'needs_owner')}\n"
            f"Получено: {usd(f['received'])} | Расходы: {usd(f['expense'] + f['fee'])} | Чистая прибыль: {usd(f['net_profit'])}\n"
            f"Ошибок за 24ч: {_n(c, 'SELECT COUNT(*) FROM errors WHERE ts>?', time.time() - 86400)}\n"
            f"Последний цикл: {_ago(cyc['ts']) if cyc else 'ещё не было'}")

def cmd_agents(c, a):
    div = a[0].upper() if a else None
    rows = c.execute("""SELECT g.id, g.division, g.name, g.active, COALESCE(SUM(t.status='needs_owner'),0) op,
                        COALESCE(SUM(t.status='done'),0) dn, COALESCE(SUM(t.status='failed'),0) fl
                        FROM agents g LEFT JOIN tasks t ON t.agent_id=g.id GROUP BY g.id""").fetchall()
    order = "ABCDEFS"
    rows = sorted(rows, key=lambda r: (order.index(r["division"]) if r["division"] in order else 99, r["id"]))
    if div:
        rows = [r for r in rows if r["division"] == div]
        if not rows:
            return "Нет такого подразделения. Доступны: A B C D E F S"
    names = {k: v[0] for k, v in agents.D.items()}; names["S"] = "Служебные"
    out = [f"Агентов: {len(rows)} (активных {sum(r['active'] for r in rows)}) | задач: открыто {sum(r['op'] for r in rows)}, "
           f"выполнено {sum(r['dn'] for r in rows)}, провалено {sum(r['fl'] for r in rows)}"]
    cur = None
    for r in rows:
        if r["division"] != cur:
            cur = r["division"]; out.append(f"\n{cur} · {names.get(cur, cur)}")
        out.append(f"{r['id']} {r['name']}" + ("" if r["active"] else " [выкл]") + (f" — {r['op']}/{r['dn']}/{r['fl']}" if r["op"] or r["dn"] or r["fl"] else ""))
    out.append("\nФормат «откр/готово/провал». Подразделение: /agents A")
    return "\n".join(out)

def cmd_tasks(c, a):
    rows = c.execute("""SELECT t.id, t.agent_id, o.title, o.score, o.url, t.result FROM tasks t JOIN opportunities o ON o.id=t.opp_id
                        WHERE t.status='needs_owner' ORDER BY o.score DESC LIMIT 10""").fetchall()
    return "\n\n".join(f"#{r['id']} [{r['agent_id']}] {r['title'][:80]}\n≈${r['score']:.0f} — {r['result'][:200]}\n{r['url']}" for r in rows) \
        + ("\n\n/draft <id> — черновик, /done <id> [часы], /fail <id> [часы]" if rows else "") or "Очередь пуста."

def cmd_opps(c, a):
    rows = c.execute("SELECT title,score,url,flags FROM opportunities WHERE status IN ('scored','needs_owner') ORDER BY score DESC LIMIT 10").fetchall()
    return "\n\n".join(f"≈${r['score']:.0f} {r['title'][:80]}\n{r['url']}" + (f"\n⚠ {r['flags'][:120]}" if r["flags"] else "") for r in rows) or "Пока ничего."

def cmd_earnings(c, a):
    return f"Подтверждённые начисления: {usd(finance.summary(c)['confirmed'])}"

def cmd_received(c, a):
    f = finance.summary(c)
    rows = c.execute("SELECT ts,source,amount_usd,tx_id FROM ledger WHERE kind='received' ORDER BY id DESC LIMIT 5").fetchall()
    return f"Фактически получено: {usd(f['received'])}" + "".join(
        f"\n{time.strftime('%d.%m', time.localtime(r['ts']))} {r['source']} {usd(r['amount_usd'])} {str(r['tx_id'])[:14]}" for r in rows)

def cmd_pending(c, a):
    f = finance.summary(c)
    return (f"Заработано, но не выплачено: {usd(f['earned_unpaid'])}\n"
            f"Прогноз выгоды по открытым задачам (НЕ деньги): {usd(f['pipeline'])}")

def cmd_expenses(c, a):
    f = finance.summary(c)
    return f"Расходы: {usd(f['expense'])} | Комиссии: {usd(f['fee'])} | Затрачено часов: {f['hours']:.1f}"

def cmd_profit(c, a):
    f = finance.summary(c)
    ph = f"{usd(f['net_per_hour'])}/час" if f["net_per_hour"] is not None else "часы не внесены (/log_hours)"
    return f"Получено {usd(f['received'])} − расходы {usd(f['expense'])} − комиссии {usd(f['fee'])} = {usd(f['net_profit'])}\nЧистый доход: {ph}"

def cmd_top(c, a):
    rows = improve.source_stats(c)
    return "\n".join(f"{s['source']}: найдено {s['found']}, отсев {s['rejected']}, задач {s['tasks']} (✓{s['done']}/✗{s['failed']}), "
                     f"получено {usd(s['received'])}, p={s['p']:.2f}" for s in rows) or "Данных пока нет."

def cmd_report(c, a):
    f = finance.summary(c)
    return (cmd_status(c, a) + f"\n\nПотенциал (НЕ деньги): {usd(f['potential'])}\nЗаработано, не выплачено: {usd(f['earned_unpaid'])}"
            f"\nПодтверждено: {usd(f['confirmed'])}\n\n" + cmd_top(c, a))

def cmd_errors(c, a):
    rows = c.execute("SELECT ts,where_,message FROM errors ORDER BY id DESC LIMIT 10").fetchall()
    return "\n".join(f"{time.strftime('%d.%m %H:%M', time.localtime(r['ts']))} {r['where_']}: {r['message'][:140]}" for r in rows) or "Ошибок нет."

def cmd_history(c, a):
    rows = c.execute("SELECT ts,agent_id,action,detail FROM actions ORDER BY id DESC LIMIT 15").fetchall()
    return "\n".join(f"{time.strftime('%d.%m %H:%M', time.localtime(r['ts']))} {r['agent_id']} {r['action']} {r['detail'][:80]}" for r in rows) or "Журнал пуст."

def cmd_limits(c, a):
    from . import llm
    return (f"Бюджет: $0. Задач за цикл: {config.MAX_NEW_TASKS}, авточерновиков: {config.MAX_DRAFTS}. Оценка вашего часа: ${config.HOURLY_USD}.\n"
            f"ИИ для черновиков: {'подключён' if llm.available() else 'не подключён (шаблоны)'}.\n"
            "Actions: ~57 запусков/сутки ≈ 1700 из 2000 бесплатных минут приватного репо.\nАвтовыплаты выключены: любой вывод требует /approve.")

def cmd_pause(c, a): put(c, "paused", 1); return "⏸ Новые задачи приостановлены."
def cmd_resume(c, a): put(c, "paused", 0); return "▶️ Работа возобновлена."

def cmd_approve(c, a, yes=True):
    if a:
        try:
            r = finance.approve(c, int(a[0]), yes)
        except ValueError:
            return "Укажите номер: /approve 3"
        return "Готово." if r else "Не найдено или уже обработано."
    rows = c.execute("SELECT id,kind,payload FROM approvals WHERE status='pending'").fetchall()
    return ("\n".join(f"#{r['id']} {r['kind']}: {r['payload']}" for r in rows) + "\n\n/approve <id> или /reject <id>") if rows else "Нет ожидающих подтверждения."

def _num(s):
    return float(s.replace(",", "."))

def _log(kind, need_ref):
    def f(c, a):
        if len(a) < (3 if need_ref else 2):
            return f"Формат: /log_{ {'received': 'received', 'confirmed': 'confirmed', 'earned_unpaid': 'pending', 'expense': 'expense', 'fee': 'fee'}[kind]} источник сумма_USD" + (" tx_или_ссылка" if need_ref else " [заметка]")
        try:
            ref = a[2] if len(a) > 2 else ""
            i = finance.add(c, kind, _num(a[1]), a[0], proof=ref, tx_id=ref if need_ref else None)
        except (finance.FinanceError, ValueError) as e:
            return f"Отказано: {e}"
        return "Записано." if i else "Такая запись уже есть (дубль не добавлен)."
    return f

def cmd_log_hours(c, a):
    try:
        finance.log_hours(c, int(a[0]), _num(a[1]))
    except (finance.FinanceError, ValueError, IndexError) as e:
        return f"Формат: /log_hours task_id часы ({e})"
    return "Часы записаны."

def _close(status):
    def f(c, a):
        try:
            tid = int(a[0])
            if len(a) > 1: finance.log_hours(c, tid, _num(a[1]))
        except (ValueError, IndexError, finance.FinanceError):
            return f"Формат: /{'done' if status == 'done' else 'fail'} task_id [часы]"
        r = c.execute("UPDATE tasks SET status=?, updated=? WHERE id=? AND status='needs_owner'", (status, time.time(), tid))
        c.commit()
        if r.rowcount:
            log(c, "OWNER", "task_" + status, f"#{tid}")
        return "Задача закрыта: система учтёт результат." if r.rowcount else "Не найдена или уже закрыта."
    return f

def cmd_draft(c, a):
    try:
        tid = int(a[0])
    except (ValueError, IndexError):
        return "Формат: /draft task_id [proposal|translation|article|docs] [язык]"
    kind = a[1].lower() if len(a) > 1 else "proposal"
    lang = a[2] if len(a) > 2 else "English"
    try:
        did, origin, content = drafts.make(c, tid, kind, lang)
    except ValueError as e:
        return str(e)
    tag = "черновик ИИ — проверьте перед отправкой" if origin == "llm" else "шаблон (ИИ не подключён)"
    return f"Черновик #{did} ({kind}, {tag}):\n\n{content}"

def cmd_drafts(c, a):
    if a:
        r = c.execute("SELECT * FROM drafts WHERE id=?", (a[0],)).fetchone() if a[0].isdigit() else None
        return r["content"] if r else "Не найден."
    rows = c.execute("SELECT id,task_id,kind,origin FROM drafts ORDER BY id DESC LIMIT 10").fetchall()
    return "\n".join(f"#{r['id']} задача {r['task_id']} {r['kind']} ({r['origin']})" for r in rows) + "\n\n/drafts <id> — показать" if rows else "Черновиков нет."

def cmd_sources(c, a):
    H = {r["name"]: r for r in c.execute("SELECT * FROM source_health")}
    out = []
    for cfg in src_mod.load_configs():
        h = H.get(cfg["name"])
        state = "выкл (конфиг)" if not cfg.get("enabled", True) else ("ОТКЛЮЧЁН" if h and h["disabled"] else "ок")
        out.append(f"{cfg['name']} [{state}] запуск: {_ago(h['last_run']) if h else 'не было'}, найдено {h['last_count'] if h else 0}, ошибок подряд {h['fails'] if h else 0}"
                   + (f"\n  ↳ {h['last_error'][:100]}" if h and h["last_error"] else ""))
    return "\n".join(out)

def _src_toggle(on):
    def f(c, a):
        if not a: return "Укажите имя источника: /sources"
        improve.set_enabled(c, a[0], on)
        return f"Источник {a[0]} {'включён' if on else 'отключён'}."
    return f

def cmd_notify(c, a):
    if not a or a[0] not in ("events", "all", "quiet"):
        return f"Режим: {get(c, 'notify_mode', 'events')}. Варианты: /notify events | all | quiet"
    put(c, "notify_mode", a[0]); return f"Режим уведомлений: {a[0]}"

def cmd_setprofile(c, a):
    if not a: return f"Профиль: {get(c, 'profile', '(пусто)')}\nЗадать: /setprofile 1–2 предложения о вашем опыте (используется в черновиках)"
    put(c, "profile", " ".join(a)[:600]); return "Профиль сохранён."

COMMANDS = {
 "status": cmd_status, "agents": cmd_agents, "active": cmd_tasks, "tasks": cmd_tasks, "opportunities": cmd_opps,
 "earnings": cmd_earnings, "received": cmd_received, "pending": cmd_pending, "expenses": cmd_expenses, "profit": cmd_profit,
 "top": cmd_top, "report": cmd_report, "errors": cmd_errors, "limits": cmd_limits, "pause": cmd_pause, "resume": cmd_resume,
 "approve": cmd_approve, "reject": lambda c, a: cmd_approve(c, a, False), "history": cmd_history,
 "log_received": _log("received", True), "log_confirmed": _log("confirmed", True), "log_pending": _log("earned_unpaid", False),
 "log_expense": _log("expense", False), "log_hours": cmd_log_hours, "done": _close("done"), "fail": _close("failed"),
 "draft": cmd_draft, "drafts": cmd_drafts, "sources": cmd_sources, "source_on": _src_toggle(True), "source_off": _src_toggle(False),
 "notify": cmd_notify, "setprofile": cmd_setprofile,
}
HELP = "Команды: /" + " /".join(COMMANDS)

def handle(c, text, chat_id, owner=None):
    owner = config.OWNER if owner is None else owner
    parts = (text or "").strip().split()
    if not parts or not parts[0].startswith("/"):
        return None
    cmd = parts[0][1:].split("@")[0].lower()
    if not owner and cmd == "start":
        return f"Ваш chat id: {chat_id}. Добавьте его секретом TELEGRAM_OWNER_ID и снова отправьте /start."
    if str(chat_id) != str(owner):
        return None  # чужим не отвечаем
    if cmd == "start":
        return "AI Money Hunters на связи.\n" + cmd_status(c, []) + "\n\n" + HELP
    fn = COMMANDS.get(cmd)
    if not fn:
        return "Неизвестная команда.\n" + HELP
    try:
        return fn(c, parts[1:])
    except Exception as e:
        err(c, f"cmd:{cmd}", e)
        return f"Ошибка выполнения /{cmd}: {str(e)[:150]}"

def process_updates(c, send_fn=None):
    send_fn = send_fn or send
    offset = int(get(c, "tg_offset", "0"))
    n = 0
    for u in api("getUpdates", offset=offset, timeout=0, allowed_updates=json.dumps(["message"])).get("result", []):
        offset = max(offset, u["update_id"] + 1); n += 1
        try:
            m = u.get("message") or {}
            chat = (m.get("chat") or {}).get("id")
            reply = handle(c, m.get("text"), chat)
            if reply:
                send_fn(reply, chat)
        except Exception as e:
            err(c, "telegram-update", e)
    put(c, "tg_offset", offset)
    return n
