"""Точка входа для GitHub Actions / cron: обработка команд Telegram + один цикл CEO."""
from hunters import db, ceo, bot, config

def main():
    c = db.connect()
    notify = bot.send if config.TOKEN and config.OWNER else (lambda m: print("NOTIFY:", m))
    def poll():
        try:
            if config.TOKEN:
                bot.process_updates(c)
        except Exception as e:
            db.err(c, "telegram", e)
    poll()
    print("cycle:", ceo.run_cycle(c, notify))
    poll()

if __name__ == "__main__":
    main()
