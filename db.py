import sqlite3, time, os
from . import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS agents(id TEXT PRIMARY KEY, division TEXT, name TEXT, kind TEXT, role TEXT, instructions TEXT, active INTEGER DEFAULT 1);
CREATE TABLE IF NOT EXISTS opportunities(id INTEGER PRIMARY KEY, source TEXT, url TEXT UNIQUE, title TEXT, description TEXT,
  division TEXT, reward_usd REAL DEFAULT 0, cost_usd REAL DEFAULT 0, est_hours REAL DEFAULT 1, p_payout REAL DEFAULT 0.3,
  deadline TEXT, status TEXT DEFAULT 'new', score REAL DEFAULT 0, flags TEXT DEFAULT '', found_at REAL);
CREATE TABLE IF NOT EXISTS tasks(id INTEGER PRIMARY KEY, opp_id INTEGER, agent_id TEXT, kind TEXT, status TEXT, created REAL, updated REAL, result TEXT, evidence TEXT);
CREATE TABLE IF NOT EXISTS ledger(id INTEGER PRIMARY KEY, ts REAL, source TEXT, kind TEXT, amount REAL, currency TEXT, amount_usd REAL,
  status TEXT, proof TEXT, tx_id TEXT, idem TEXT UNIQUE);
CREATE TABLE IF NOT EXISTS actions(id INTEGER PRIMARY KEY, ts REAL, agent_id TEXT, action TEXT, detail TEXT);
CREATE TABLE IF NOT EXISTS errors(id INTEGER PRIMARY KEY, ts REAL, where_ TEXT, message TEXT);
CREATE TABLE IF NOT EXISTS approvals(id INTEGER PRIMARY KEY, ts REAL, kind TEXT, payload TEXT, status TEXT DEFAULT 'pending');
CREATE TABLE IF NOT EXISTS settings(k TEXT PRIMARY KEY, v TEXT);
CREATE TABLE IF NOT EXISTS strategies(id INTEGER PRIMARY KEY, name TEXT, version INTEGER, params TEXT, change TEXT, reason TEXT,
  sample INTEGER, tasks_ok INTEGER, confirmed_usd REAL, hours REAL, expenses REAL, errors INTEGER, net REAL, active INTEGER, ts REAL);
CREATE TABLE IF NOT EXISTS cycles(id INTEGER PRIMARY KEY, ts REAL, found INTEGER, tasks INTEGER, drafts INTEGER, errors INTEGER, skipped INTEGER, secs REAL);
CREATE TABLE IF NOT EXISTS drafts(id INTEGER PRIMARY KEY, task_id INTEGER, kind TEXT, content TEXT, origin TEXT, status TEXT DEFAULT 'draft', ts REAL);
CREATE TABLE IF NOT EXISTS source_health(name TEXT PRIMARY KEY, last_run REAL DEFAULT 0, last_ok REAL DEFAULT 0,
  fails INTEGER DEFAULT 0, disabled INTEGER DEFAULT 0, last_error TEXT DEFAULT '', last_count INTEGER DEFAULT 0);
"""
# колонки, добавленные после v1 (миграция старых баз без потери данных)
EXTRA = {
    "opportunities": {"risk": "INTEGER DEFAULT 0", "hourly_usd": "REAL DEFAULT 0", "geo_ok": "INTEGER DEFAULT 1",
                      "kind": "TEXT DEFAULT ''", "p_mult": "REAL DEFAULT 1"},
    "tasks": {"hours": "REAL DEFAULT 0"},
}

def _migrate(c):
    for table, cols in EXTRA.items():
        have = {r[1] for r in c.execute(f"PRAGMA table_info({table})")}
        for col, ddl in cols.items():
            if col not in have:
                c.execute(f"ALTER TABLE {table} ADD COLUMN {col} {ddl}")
    c.commit()

def connect(path=None):
    path = path or config.DB_PATH
    if path != ":memory:":
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    c = sqlite3.connect(path)
    c.row_factory = sqlite3.Row
    c.executescript(SCHEMA)
    _migrate(c)
    return c

def get(c, k, default=None):
    r = c.execute("SELECT v FROM settings WHERE k=?", (k,)).fetchone()
    return r["v"] if r else default

def put(c, k, v):
    c.execute("INSERT INTO settings(k,v) VALUES(?,?) ON CONFLICT(k) DO UPDATE SET v=excluded.v", (k, str(v)))
    c.commit()

def log(c, agent_id, action, detail=""):
    c.execute("INSERT INTO actions(ts,agent_id,action,detail) VALUES(?,?,?,?)", (time.time(), agent_id, action, str(detail)[:500]))
    c.commit()

def err(c, where, message):
    c.execute("INSERT INTO errors(ts,where_,message) VALUES(?,?,?)", (time.time(), where, str(message)[:500]))
    c.commit()
