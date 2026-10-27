"""AI CEO: найти -> отсеять -> оценить -> назначить агента -> подготовить задачу и черновик -> зафиксировать."""
import time, json, re
from . import config, agents, safety, improve, drafts, sources as src_mod
from .db import get, log, err

GIG = re.compile(r"\b(freelance|contract(or)?|part[- ]time|translat\w+|transcri\w+|copywrit\w+|technical writer|content writer|proofread\w*|"
                 r"subtitl\w+|data (labeling|annotation)|bounty|one[- ]off|gig)\b", re.I)
ROUTES = [(r"translat|перевод", "B02"), (r"transcri", "B03"), (r"subtitl", "B04"), (r"label|annotat", "B05"),
          (r"copywrit|content writ|article|blog|writer|writing", "B01"), (r"documentation|technical writ|\bdocs\b", "A10"),
          (r"bug bounty|vulnerab|security", "A04"), (r"\bqa\b|tester|testing", "B11"), (r"research|survey|user test", "B13"),
          (r"affiliate|referral", "D01"), (r"hackathon", "E06"), (r"\bgrant", "E08"), (r"contest|prize", "E05"), (r"bounty", "A04")]
GIG_HOURS, BOUNTY_HOURS, STALE_DAYS = 8, 4, 14

def is_gig(it):
    return (it.get("job_type") or "").lower() in ("contract", "freelance", "part_time", "part-time") or \
           bool(GIG.search((it.get("title") or "") + " " + (it.get("description") or "")[:400]))

def route(c, opp):
    text = f'{opp["title"]} {(opp["description"] or "")[:500]}'.lower()
    for pat, aid in ROUTES:
        if re.search(pat, text) and c.execute("SELECT 1 FROM agents WHERE id=? AND active=1", (aid,)).fetchone():
            return aid
    return agents.pick(c, opp["division"])

def score(reward, p, cost, hours, hourly=None):
    return reward * p - cost - hours * (config.HOURLY_USD if hourly is None else hourly)

def ingest(c, items):
    """-> (новых, отфильтровано)."""
    new = filtered = 0
    for it in items:
        if it.get("only_gigs") and not is_gig(it):
            filtered += 1
            continue
        text = f'{it["title"]} {it["description"]}'
        risk, reasons = safety.assess(text, it["url"])
        geo_ok, geo_note = safety.geo(text, it.get("location", ""))
        pay_mult, pay_note = safety.payout(text)
        if it.get("reward_kind") == "bounty":
            raw = safety.reward(text)
            if raw > 5000:
                risk = min(100, risk + 20); reasons.append("нереально высокая награда")
            reward, hourly, hours = (raw if raw <= 5000 else 0.0), 0.0, BOUNTY_HOURS
        else:
            hourly = safety.hourly_usd(text) or (it.get("annual_usd", 0) / 2000)
            hours, reward = GIG_HOURS, hourly * GIG_HOURS
        p_mult = max(0.0, 1 - risk / 100) * (1.0 if geo_ok else 0.3) * pay_mult
        p_base = improve.p_payout(c, it["source"])
        flags = "; ".join(x for x in [*reasons, geo_note, pay_note] if x)
        status = "rejected" if risk >= 60 else "scored"
        try:
            c.execute("""INSERT INTO opportunities(source,url,title,description,division,reward_usd,est_hours,p_payout,status,score,flags,found_at,
                         risk,hourly_usd,geo_ok,kind,p_mult) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                      (it["source"], it["url"], it["title"][:200], it["description"], it["division"], reward, hours, p_base, status,
                       score(reward, p_base * p_mult, 0, hours) if status == "scored" else 0, flags, time.time(),
                       risk, hourly, int(geo_ok), it.get("reward_kind", "gig"), p_mult))
            new += 1
        except Exception as e:
            if "UNIQUE" not in str(e):
                err(c, "ingest", e)
    c.commit()
    return new, filtered

def rescore(c):
    for o in c.execute("SELECT * FROM opportunities WHERE status='scored'").fetchall():
        p = improve.p_payout(c, o["source"])
        c.execute("UPDATE opportunities SET p_payout=?, score=? WHERE id=?",
                  (p, score(o["reward_usd"], p * o["p_mult"], o["cost_usd"], o["est_hours"]), o["id"]))
    c.execute("UPDATE opportunities SET status='expired' WHERE status='scored' AND found_at<?", (time.time() - STALE_DAYS * 86400,))
    c.commit()

def triage(opp):
    d = (opp["description"] or "").lower()
    notes = [n for kw, n in [("kyc", "нужна верификация личности (KYC)"), ("wallet", "нужен кошелёк"), ("deadline", "есть дедлайн"),
                             ("fee", "упомянуты комиссии — проверить вручную"), ("apply", "нужна заявка")] if kw in d]
    if opp["flags"]:
        notes.append("⚠ " + opp["flags"])
    return "; ".join(notes) or "требований не найдено, проверить условия вручную"

def run_cycle(c, notify=lambda m: None, sources=None):
    t0 = time.time()
    st = dict(found=0, filtered=0, tasks=0, drafts=0, errors=0, skipped=False, disabled=[], new_tasks=[])
    agents.seed(c)
    if get(c, "paused") == "1":
        st["skipped"] = True
        log(c, "CEO", "cycle_skipped", "пауза")
        c.execute("INSERT INTO cycles(ts,found,tasks,drafts,errors,skipped,secs) VALUES(?,?,?,?,?,?,?)", (t0, 0, 0, 0, 0, 1, 0)); c.commit()
        return st
    for s in (sources if sources is not None else src_mod.default_sources()):
        if not improve.due(c, s):
            continue
        try:
            items = s.fetch()
            improve.ok(c, s.name, len(items))
            n, f = ingest(c, items)
            st["found"] += n; st["filtered"] += f
        except Exception as e:
            st["errors"] += 1
            err(c, f"source:{getattr(s, 'name', '?')}", e)
            if improve.fail(c, s.name, e):
                st["disabled"].append(s.name)
    rescore(c)
    top = c.execute("SELECT * FROM opportunities WHERE status='scored' AND score>0 ORDER BY score DESC LIMIT ?", (config.MAX_NEW_TASKS,)).fetchall()
    for o in top:
        aid, now = route(c, o), time.time()
        cur = c.execute("INSERT INTO tasks(opp_id,agent_id,kind,status,created,updated,result,evidence) VALUES(?,?,?,?,?,?,?,?)",
                        (o["id"], aid, "triage", "needs_owner", now, now, triage(o), o["url"]))
        c.execute("UPDATE opportunities SET status='needs_owner' WHERE id=?", (o["id"],))
        c.commit()
        log(c, aid, "task_created", f'#{cur.lastrowid} {o["title"][:70]} score={o["score"]:.1f}')
        st["tasks"] += 1
        st["new_tasks"].append(dict(id=cur.lastrowid, agent=aid, title=o["title"], score=o["score"], url=o["url"]))
        if o["score"] >= config.HIGH_SCORE:
            notify(f'🔥 Высокий приоритет #{cur.lastrowid}: {o["title"][:100]}\nОценка чистой выгоды ≈ ${o["score"]:.0f} (прогноз, не деньги)\n{o["url"]}')
    for t in st["new_tasks"][:config.MAX_DRAFTS]:
        try:
            drafts.make(c, t["id"], "proposal")
            st["drafts"] += 1
        except Exception as e:
            err(c, "draft", e)
    try:
        improve.maybe_snapshot(c)
    except Exception as e:
        err(c, "snapshot", e)
    c.execute("INSERT INTO cycles(ts,found,tasks,drafts,errors,skipped,secs) VALUES(?,?,?,?,?,?,?)",
              (t0, st["found"], st["tasks"], st["drafts"], st["errors"], 0, time.time() - t0))
    c.commit()
    log(c, "CEO", "cycle_done", json.dumps({k: v for k, v in st.items() if k != "new_tasks"}))
    return st
