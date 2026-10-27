"""Точка входа для GitHub Actions / cron: команды Telegram -> цикл CEO -> уведомления -> команды Telegram."""
import sys
from hunters import db, ceo, bot, config, monitor

def main():
    c = db.connect()
    live = bool(config.TOKEN and config.OWNER)

    def send(text, chat=None):
        if not live:
            print("NOTIFY:", text); return
        try:
            bot.send(text, chat)
        except Exception as e:
            db.err(c, "send", e)

    def poll():
        if not config.TOKEN:
            return
        try:
            bot.process_updates(c)
        except Exception as e:
            db.err(c, "telegram", e)

    poll()
    try:
        st = ceo.run_cycle(c, send)
    except Exception as e:           # цикл не должен валить запуск: состояние всё равно сохранится
        db.err(c, "cycle", e)
        send(f"❌ Сбой цикла: {str(e)[:200]}")
        return 0
    print("cycle:", {k: v for k, v in st.items() if k != "new_tasks"})
    if monitor.should_send(c, st):
        send(monitor.cycle_message(st))
    if monitor.digest_due(c):
        send("📊 Ежедневная сводка\n" + bot.cmd_report(c, []))
    poll()
    return 0

if __name__ == "__main__":
    sys.exit(main())
