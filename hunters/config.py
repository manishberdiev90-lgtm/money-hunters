import os
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
DB_PATH = os.environ.get("MH_DB", str(ROOT / "data" / "mh.db"))
TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
OWNER = os.environ.get("TELEGRAM_OWNER_ID", "")
HOURLY_USD = float(os.environ.get("MH_HOURLY_USD", "3"))   # во сколько оцениваем час вашего времени
MAX_NEW_TASKS = int(os.environ.get("MH_MAX_TASKS", "5"))    # новых задач за один цикл
HIGH_SCORE = float(os.environ.get("MH_HIGH_SCORE", "20"))   # порог уведомления "высокий приоритет"
SOURCES_FILE = ROOT / "sources.json"
