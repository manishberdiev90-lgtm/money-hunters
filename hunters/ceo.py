"""AI CEO: замкнутый цикл найти -> проверить -> оценить -> назначить -> выполнить доступное -> зафиксировать."""
import time, json
from . import config, agents, safety, sources as src_mod
from .db import get, log, err

def p_payout(c, source):
    """Вероятность выплаты из фактической истории источника (сглаживание, априор 0.3)."""
    ok = c.execute("SELECT COUNT(*) FROM ledger WHERE source=? AND kind='received'", (source,)).fetchone()[0]
    n = c.execute("SELECT COUNT(*) FROM opportunities WHERE source=? AND status IN ('needs_owner','done')", (source,)).fetchone()[0]
    return min(1.0, (ok + 0.9) / (n + 3))

def score(opp, hourly=None):
    hourly = config.HOURLY_USD if hourly is None else hourly
    return opp["reward_usd"] * opp["p_payout"] - opp["cost_usd"] - opp["est_hours"] * hourly

def ingest(c, items):
    new = 0
    for it in items:
        text = f'{it["title"]} {it["description"]}'
        flags = safety.scan(text)
        status = "rejected" if flags else "new"
        try:
            c.execute("""INSERT INTO opportunities(source,url,title,description,division,reward_usd,p_payout,status,flags,found_at)
                         VALUES(?,?,?,?,?,?,?,?,?,?)""",
                      (it["source"], it["url"], it["title"][:200], it["description"], it["division"], safety.reward(text),
                       p_payout(c, it["source"]), status, ",".join(flags), time.time()))
            new += 1
        except Exception as e:
            if "UNIQUE" not in str(e):
                err(c, "ingest", e)
    c.commit()
    return new

def triage(opp):
    """Что система делает сама: отсев скама, оценка, заметки о требованиях. Регистрации и отправку работ от вашего имени НЕ выполняет."""
    d = (opp["description"] or "").lower()
    notes = [n for kw, n in [("kyc", "нужна верификация личности (KYC)"), ("wallet", "нужен кошелёк"),
                             ("deadline", "есть дедлайн"), ("fee", "упомянуты комиссии — проверить вручную"),
                             ("apply", "нужна заявка")] if kw in d]
    return "; ".join(notes) or "требований не найдено, проверить условия вручную"

def run_cycle(c, notify=lambda m: None, sources=None):
    st = dict(found=0, tasks=0, errors=0, skipped=False)
    agents.seed(c)
    if get(c, "paused") == "1":
        st["skipped"] = True
        log(c, "CEO", "cycle_skipped", "пауза")
        return st
    for s in (sources if sources is not None else src_mod.default_sources()):
        try:
            st["found"] += ingest(c, s.fetch())
        except Exception as e:
            st["errors"] += 1
            err(c, f"source:{getattr(s, 'name', '?')}", e)
    for o in c.execute("SELECT * FROM opportunities WHERE status='new'").fetchall():
        c.execute("UPDATE opportunities SET score=?, status='scored' WHERE id=?", (score(o), o["id"]))
    c.commit()
    top = c.execute("SELECT * FROM opportunities WHERE status='scored' AND score>0 ORDER BY score DESC LIMIT ?", (config.MAX_NEW_TASKS,)).fetchall()
    for o in top:
        aid = agents.pick(c, o["division"])
        note = triage(o)
        now = time.time()
        c.execute("INSERT INTO tasks(opp_id,agent_id,kind,status,created,updated,result,evidence) VALUES(?,?,?,?,?,?,?,?)",
                  (o["id"], aid, "triage", "needs_owner", now, now, note, o["url"]))
        c.execute("UPDATE opportunities SET status='needs_owner' WHERE id=?", (o["id"],))
        c.commit()
        log(c, aid, "task_created", f'{o["title"][:80]} score={o["score"]:.1f}')
        st["tasks"] += 1
        if o["score"] >= config.HIGH_SCORE:
            notify(f'🔥 {o["title"][:100]}\nОценка чистой выгоды: ${o["score"]:.0f} (награда до ${o["reward_usd"]:.0f}, p={o["p_payout"]:.2f})\n{o["url"]}\n{note}')
    log(c, "CEO", "cycle_done", json.dumps(st))
    return st
