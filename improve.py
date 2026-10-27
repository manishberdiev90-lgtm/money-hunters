"""Оценка источников по ФАКТИЧЕСКИМ результатам + здоровье источников + ежедневные снимки стратегии."""
import time, json
from . import config, strategies
from .db import get, put

# ---- здоровье источников ----
def due(c, s):
    h = c.execute("SELECT * FROM source_health WHERE name=?", (s.name,)).fetchone()
    if h and h["disabled"]:
        return False
    interval = getattr(s, "interval", 0)
    return not (h and interval and time.time() < h["last_run"] + interval * 60 - 90)

def ok(c, name, n):
    now = time.time()
    c.execute("""INSERT INTO source_health(name,last_run,last_ok,fails,last_error,last_count) VALUES(?,?,?,0,'',?)
                 ON CONFLICT(name) DO UPDATE SET last_run=excluded.last_run,last_ok=excluded.last_ok,fails=0,last_error='',last_count=excluded.last_count""",
              (name, now, now, n))
    c.commit()

def fail(c, name, e):
    """-> True, если источник только что отключён из-за серии ошибок."""
    c.execute("""INSERT INTO source_health(name,last_run,fails,last_error) VALUES(?,?,1,?)
                 ON CONFLICT(name) DO UPDATE SET last_run=excluded.last_run,fails=fails+1,last_error=excluded.last_error""",
              (name, time.time(), str(e)[:200]))
    h = c.execute("SELECT fails,disabled FROM source_health WHERE name=?", (name,)).fetchone()
    newly = h["fails"] >= config.SOURCE_MAX_FAILS and not h["disabled"]
    if newly:
        c.execute("UPDATE source_health SET disabled=1 WHERE name=?", (name,))
    c.commit()
    return newly

def set_enabled(c, name, on):
    c.execute("""INSERT INTO source_health(name,disabled,fails) VALUES(?,?,0)
                 ON CONFLICT(name) DO UPDATE SET disabled=excluded.disabled,fails=0""", (name, 0 if on else 1))
    c.commit()

# ---- вероятность выплаты по факту ----
def p_payout(c, source):
    """(оплаченных+0.9)/(закрытых задач+3): растёт только от подтверждённых поступлений источника."""
    paid = c.execute("SELECT COUNT(*) FROM ledger WHERE source=? AND kind='received'", (source,)).fetchone()[0]
    closed = c.execute("""SELECT COUNT(*) FROM tasks t JOIN opportunities o ON o.id=t.opp_id
                          WHERE o.source=? AND t.status IN ('done','failed')""", (source,)).fetchone()[0]
    return min(1.0, (paid + 0.9) / (max(closed, paid) + 3))

def source_stats(c):
    S = {}
    for r in c.execute("SELECT source, COUNT(*) n, SUM(status='rejected') rej FROM opportunities GROUP BY source"):
        S[r["source"]] = dict(source=r["source"], found=r["n"], rejected=r["rej"] or 0, tasks=0, done=0, failed=0, hours=0.0, received=0.0, cost=0.0, paid=0)
    for r in c.execute("""SELECT o.source, COUNT(*) n, SUM(t.status='done') d, SUM(t.status='failed') f, COALESCE(SUM(t.hours),0) h
                          FROM tasks t JOIN opportunities o ON o.id=t.opp_id GROUP BY o.source"""):
        s = S.setdefault(r["source"], dict(source=r["source"], found=0, rejected=0, tasks=0, done=0, failed=0, hours=0.0, received=0.0, cost=0.0, paid=0))
        s.update(tasks=r["n"], done=r["d"] or 0, failed=r["f"] or 0, hours=r["h"])
    for r in c.execute("""SELECT source, SUM(CASE WHEN kind='received' THEN amount_usd ELSE 0 END) rec,
                          SUM(CASE WHEN kind IN ('expense','fee') THEN amount_usd ELSE 0 END) cost,
                          SUM(CASE WHEN kind='received' THEN 1 ELSE 0 END) paid FROM ledger GROUP BY source"""):
        s = S.setdefault(r["source"], dict(source=r["source"], found=0, rejected=0, tasks=0, done=0, failed=0, hours=0.0, received=0.0, cost=0.0, paid=0))
        s.update(received=r["rec"] or 0.0, cost=r["cost"] or 0.0, paid=r["paid"] or 0)
    for s in S.values():
        s["net"] = s["received"] - s["cost"]
        s["net_per_hour"] = s["net"] / s["hours"] if s["hours"] > 0 else None
        s["p"] = p_payout(c, s["source"])
    return sorted(S.values(), key=lambda s: (s["net"], s["p"]), reverse=True)

def maybe_snapshot(c, now=None):
    """Раз в сутки сохраняет версию стратегии 'scoring' с реальными метриками; принимает её только при улучшении."""
    today = time.strftime("%Y-%m-%d", time.gmtime(now or time.time()))
    if get(c, "last_snapshot") == today:
        return None
    put(c, "last_snapshot", today)
    st = source_stats(c)
    stats = dict(sample=sum(s["done"] + s["failed"] for s in st), ok=sum(s["paid"] for s in st), confirmed=sum(s["received"] for s in st),
                 hours=sum(s["hours"] for s in st), expenses=sum(s["cost"] for s in st),
                 errors=c.execute("SELECT COUNT(*) FROM errors").fetchone()[0], net=sum(s["net"] for s in st))
    v = strategies.record(c, "scoring", dict(hourly=config.HOURLY_USD, p={s["source"]: round(s["p"], 3) for s in st}),
                          "ежедневный снимок", "автоматическая оценка по фактическим результатам", stats)
    return v, strategies.promote_if_better(c, "scoring", v)
