import os
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent

def _f(name, default):
    v = os.environ.get(name, "").strip()
    try:
        return float(v) if v else default
    except ValueError:
        return default

DB_PATH = os.environ.get("MH_DB") or str(ROOT / "data" / "mh.db")
TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
OWNER = os.environ.get("TELEGRAM_OWNER_ID", "").strip()
HOURLY_USD = _f("MH_HOURLY_USD", 3.0)          # во сколько вы оцениваете свой час
MAX_NEW_TASKS = int(_f("MH_MAX_TASKS", 5))     # новых задач за цикл
MAX_DRAFTS = int(_f("MH_MAX_DRAFTS", 2))       # автоматических черновиков за цикл (экономия квоты ИИ)
HIGH_SCORE = _f("MH_HIGH_SCORE", 20.0)         # порог мгновенного уведомления
SOURCE_MAX_FAILS = int(_f("MH_SOURCE_MAX_FAILS", 5))
TZ_OFFSET = int(_f("MH_TZ_OFFSET", 5))         # Таджикистан UTC+5
DIGEST_HOUR = int(_f("MH_DIGEST_HOUR", 9))     # локальный час ежедневной сводки
SOURCES_FILE = ROOT / "sources.json"
