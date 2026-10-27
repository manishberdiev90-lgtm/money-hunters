"""Telegram-панель. Отвечает только владельцу (TELEGRAM_OWNER_ID). Работает через getUpdates — подходит для запуска по расписанию."""
import json, time, urllib.request, urllib.parse
from . import config, finance
from .db import get, put

def api(method, **params):
    if not config.TOKEN:
        raise RuntimeError("TELEGRAM_BOT_TOKEN не задан")
    data = urllib.parse.urlencode(params).encode()
    with urllib.request.urlopen(f"https://api.telegram.org/bot{config.TOKEN}/{method}", data, timeout=30) as r:
        return json.loads(r.read())

def send(text, chat_id=None):
    chat_id = chat_id or config.OWNER
    if not (config.TOKEN and chat_id):
        return
    for i in range(0, len(text), 3900):
        api("sendMessage", chat_id=chat_id, text=text[i:i + 3900], disable_web_page_preview="true")

def usd(x): return f"${x:,.2f}"
def _n(c, q): return c.execute(q).fetchone()[0]

def cmd_status(c, a):
    f = finance.summary(c)
    return (f"{'⏸ ПАУЗА' if get(c, 'paused') == '1' else '▶️ Работает'}\n"
            f"Агентов: {_n(c, 'SELECT COUNT(*) FROM agents')}\n"
            f"Возможностей: {_n(c, 'SELECT COUNT(*) FROM opportunities')}, задач ждут вас: {_n(c, 'SELECT COUNT(*) FROM tasks WHERE status=\"needs_owner\"')}\n"
            f"Получено: {usd(f['received'])} | Расходы: {usd(f['expense'] + f['fee'])} | Чистая прибыль: {usd(f['net_profit'])}\n"
            f"Ошибок: {_n(c, 'SELECT COUNT(*) FROM errors')}")

def cmd_agents(c, a):
    rows = c.execute("""SELECT a.division d, COUNT(DISTINCT a.id) n, COUNT(t.id) q FROM agents a
                        LEFT JOIN tasks t ON t.agent_id=a.id AND t.status='needs_owner' GROUP BY a.division""").fetchall()
    return "Агенты по подразделениям:\n" + "\n".join(f"{r['d']}: {r['n']} агентов, задач в очереди {r['q']}" for r in rows)

def _tasks(c, a):
    rows = c.execute("""SELECT t.id, t.agent_id, o.title, o.score, o.url, t.result FROM tasks t JOIN opportunities o ON o.id=t.opp_id
                        WHERE t.status='needs_owner' ORDER BY o.score DESC LIMIT 10""").fetchall()
    return "\n\n".join(f"#{r['id']} [{r['agent_id']}] {r['title'][:80]}\nоценка ${r['score']:.0f} — {r['result']}\n{r['url']}" for r in rows) or "Пусто."

def cmd_opps(c, a):
    rows = c.execute("SELECT title,score,url FROM opportunities WHERE status IN ('scored','needs_owner') ORDER BY score DESC LIMIT 10").fetchall()
    return "\n\n".join(f"${r['score']:.0f} {r['title'][:80]}\n{r['url']}" for r in rows) or "Пока ничего."

def cmd_fin(kind, label):
    return lambda c, a: f"{label}: {usd(finance.summary(c)[kind])}"

def cmd_profit(c, a):
    f = finance.summary(c)
    return f"Получено {usd(f['received'])} − расходы {usd(f['expense'])} − комиссии {usd(f['fee'])} = {usd(f['net_profit'])}"

def cmd_top(c, a):
    rows = finance.by_source(c)
    return "\n".join(f"{r['source']}: получено {usd(r['rec'])}, затраты {usd(r['cost'])}" for r in rows) or "Данных о выплатах пока нет."

def cmd_report(c, a):
    f = finance.summary(c)
    return (cmd_status(c, a) + f"\n\nПотенциал (НЕ деньги): {usd(f['potential'])}\nЗаработано, не выплачено: {usd(f['earned_unpaid'])}"
            f"\nПодтверждено: {usd(f['confirmed'])}\n\n" + cmd_top(c, a))

def cmd_errors(c, a):
    rows = c.execute("SELECT ts,where_,message FROM errors ORDER BY id DESC LIMIT 10").fetchall()
    return "\n".join(f"{time.strftime('%d.%m %H:%M', time.localtime(r['ts']))} {r['where_']}: {r['message'][:120]}" for r in rows) or "Ошибок нет."

def cmd_history(c, a):
    rows = c.execute("SELECT ts,agent_id,action,detail FROM actions ORDER BY id DESC LIMIT 15").fetchall()
    return "\n".join(f"{time.strftime('%d.%m %H:%M', time.localtime(r['ts']))} {r['agent_id']} {r['action']} {r['detail'][:80]}" for r in rows) or "Журнал пуст."

def cmd_limits(c, a):
    return (f"Бюджет: $0. Новых задач за цикл: {config.MAX_NEW_TASKS}. Оценка вашего часа: ${config.HOURLY_USD}. "
            f"Автовыплаты выключены: любой вывод требует /approve.")

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

def cmd_log_received(c, a):
    if len(a) < 3:
        return "Формат: /log_received источник сумма_USD tx_или_ссылка"
    try:
        i = finance.add(c, "received", float(a[1]), a[0], proof=a[2], tx_id=a[2])
    except (finance.FinanceError, ValueError) as e:
        return f"Отказано: {e}"
    return "Записано." if i else "Такая запись уже есть (дубль не добавлен)."

def cmd_log_expense(c, a):
    if len(a) < 2:
        return "Формат: /log_expense источник сумма_USD"
    try:
        finance.add(c, "expense", float(a[1]), a[0], proof="manual")
    except (finance.FinanceError, ValueError) as e:
        return f"Отказано: {e}"
    return "Записано."

COMMANDS = {
 "status": cmd_status, "agents": cmd_agents, "active": _tasks, "tasks": _tasks, "opportunities": cmd_opps,
 "earnings": cmd_fin("confirmed", "Подтверждённые начисления"), "received": cmd_fin("received", "Фактически получено"),
 "pending": cmd_fin("earned_unpaid", "Ожидаемые выплаты"), "expenses": cmd_fin("expense", "Расходы"), "profit": cmd_profit,
 "top": cmd_top, "report": cmd_report, "errors": cmd_errors, "limits": cmd_limits, "pause": cmd_pause, "resume": cmd_resume,
 "approve": cmd_approve, "reject": lambda c, a: cmd_approve(c, a, False), "history": cmd_history,
 "log_received": cmd_log_received, "log_expense": cmd_log_expense,
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
    return fn(c, parts[1:]) if fn else "Неизвестная команда.\n" + HELP

def process_updates(c, send_fn=None):
    send_fn = send_fn or send
    offset = int(get(c, "tg_offset", "0"))
    res = api("getUpdates", offset=offset, timeout=0).get("result", [])
    for u in res:
        offset = u["update_id"] + 1
        m = u.get("message") or {}
        reply = handle(c, m.get("text"), (m.get("chat") or {}).get("id"))
        if reply:
            send_fn(reply, m["chat"]["id"])
    put(c, "tg_offset", offset)
    return len(res)
