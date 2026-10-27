import unittest, json, sys, os, time
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from hunters import db, agents, finance, ceo, bot, strategies, safety, improve, drafts, llm, monitor, sources, config

class Fake:
    interval = 0
    def __init__(self, name, items=None, exc=None): self.name, self.items, self.exc = name, items or [], exc
    def fetch(self):
        if self.exc: raise self.exc
        return self.items

def it(title, url, desc="", **kw):
    d = dict(source="fake", division="B", title=title, url=url, description=desc, reward_kind="gig", only_gigs=False); d.update(kw); return d

GOOD = it("Technical writer contract", "https://example.com/1", "Contract. $60/hr. Worldwide. Paid in USDT.", location="Worldwide")
class Base(unittest.TestCase):
    def setUp(self):
        self.c = db.connect(":memory:"); self._llm = llm.complete
    def tearDown(self): llm.complete = self._llm

class TestAgents(Base):
    def test_108(self):
        self.assertEqual(agents.seed(self.c), 108)
        self.assertEqual(agents.seed(self.c), 108)
    def test_agents_command_real_list(self):
        agents.seed(self.c)
        r = bot.cmd_agents(self.c, [])
        self.assertIn("Агентов: 108", r)
        for aid in ("A01", "A20", "B20", "C20", "D15", "E15", "F10", "QA", "WFC"): self.assertIn(aid, r)
        r2 = bot.cmd_agents(self.c, ["f"])
        self.assertIn("Агентов: 10", r2); self.assertNotIn("A01", r2)
        self.assertIn("Нет такого", bot.cmd_agents(self.c, ["Z"]))

class TestFinance(Base):
    def test_rules(self):
        F = finance
        with self.assertRaises(F.FinanceError): F.add(self.c, "received", 10, "x")
        with self.assertRaises(F.FinanceError): F.add(self.c, "received", 10, "x", proof="test", tx_id="123456")
        with self.assertRaises(F.FinanceError): F.add(self.c, "received", 100, "x", currency="ABC", amount_usd=5, proof="proofproof")
        with self.assertRaises(F.FinanceError): F.add(self.c, "received", 0, "x", tx_id="abcdef1")
        self.assertIsNotNone(F.add(self.c, "received", 10, "x", tx_id="0xabc123", proof="0xabc123"))
        self.assertIsNone(F.add(self.c, "received", 10, "x", tx_id="0xabc123", proof="0xabc123"))
        self.assertIsNone(F.add(self.c, "received", 99, "y", tx_id="0xabc123", proof="other-proof"))  # тот же tx_id
        F.add(self.c, "potential", 1000, "airdrop"); F.add(self.c, "expense", 2, "x"); F.add(self.c, "fee", 1, "x")
        s = F.summary(self.c)
        self.assertEqual((s["received"], s["potential"], s["net_profit"]), (10, 1000, 7))
        self.assertIsNone(s["net_per_hour"])
    def test_hours_and_per_hour(self):
        ceo.run_cycle(self.c, sources=[Fake("fake", [GOOD])])
        finance.add(self.c, "received", 40, "fake", tx_id="0xdeadbeef")
        finance.log_hours(self.c, 1, 2)
        self.assertEqual(finance.summary(self.c)["net_per_hour"], 20)
        with self.assertRaises(finance.FinanceError): finance.log_hours(self.c, 1, 30)
        with self.assertRaises(finance.FinanceError): finance.log_hours(self.c, 999, 1)
    def test_payout_approval(self):
        r = finance.request_payout(self.c, "0xNEW", 50, 1, "src")
        self.assertEqual(r[0], "approval")
        self.assertEqual(finance.request_payout(self.c, "0xNEW", 50, 1, "src")[0], "duplicate")
        with self.assertRaises(finance.FinanceError): finance.request_payout(self.c, "0xA", 5, 6, "s")
        self.assertNotIn("0xNEW", finance.payees(self.c)); finance.approve(self.c, r[1]); self.assertIn("0xNEW", finance.payees(self.c))

class TestSafety(Base):
    def test_scam(self):
        for t in ["Send us your seed phrase", "pay a registration fee to start", "Guaranteed income $500/day", "deposit this check and send back the difference",
                  "Connect your wallet to claim airdrop", "Оплатите комиссию для вывода", "Гарантированный доход, пишите в WhatsApp"]:
            self.assertGreaterEqual(safety.assess(t)[0], 60 if "WhatsApp" not in t else 60, t)
        self.assertLess(safety.assess("Fix bug in parser. Bounty $50 https://github.com/x/y/issues/1")[0], 30)
    def test_urls(self):
        self.assertGreater(safety.url_risk("http://paypal-secure-login.xyz/a")[0], 60)
        self.assertGreater(safety.url_risk("https://bit.ly/abc")[0], 0)
        self.assertGreater(safety.url_risk("http://185.1.2.3/x")[0], 0)
        self.assertEqual(safety.url_risk("https://github.com/a/b")[0], 0)
        self.assertEqual(safety.url_risk("https://www.paypal.com/x")[0], 0)
    def test_pay_parse(self):
        self.assertEqual(safety.hourly_usd("$25/hr"), 25); self.assertEqual(safety.hourly_usd("$20-$30 per hour"), 25)
        self.assertEqual(safety.hourly_usd("$60,000 - $80,000"), 35); self.assertEqual(safety.hourly_usd("$40k-$60k"), 25)
        self.assertEqual(safety.hourly_usd("bounty $100 - $500"), 0); self.assertEqual(safety.reward("Bounty $1,500"), 1500)
    def test_geo_payout(self):
        self.assertFalse(safety.geo("US only role")[0]); self.assertFalse(safety.geo("x", "USA")[0])
        self.assertTrue(safety.geo("x", "Worldwide")[0]); self.assertTrue(safety.geo("x", "")[0])
        self.assertLess(safety.payout("paid via Venmo")[0], 0.5); self.assertLess(safety.payout("paid via PayPal")[0], 1)
        self.assertEqual(safety.payout("USDT")[0], 1.0)

class TestCycle(Base):
    def test_full(self):
        scam = it("Easy $900", "u2", "send your seed phrase, win $900")
        low = it("Typing job", "u3", "$2/hr contract")
        usonly = it("Writer contract US only", "u4", "Contract writer. $60/hr. US only.", location="USA")
        notgig = it("Senior Accountant", "u5", "Full-time. $70,000 - $90,000", only_gigs=True)
        notes = []
        st = ceo.run_cycle(self.c, notes.append, [Fake("fake", [GOOD, scam, low, usonly, notgig]), Fake("bad", exc=RuntimeError("down"))])
        self.assertEqual((st["errors"], st["filtered"]), (1, 1))
        row = lambda u: self.c.execute("SELECT * FROM opportunities WHERE url=?", (u,)).fetchone()
        self.assertEqual(row("u2")["status"], "rejected")
        self.assertEqual(row("https://example.com/1")["status"], "needs_owner")
        self.assertEqual(row("u3")["status"], "scored")                      # убыточна: задачи нет
        self.assertLess(row("u4")["p_mult"], row("https://example.com/1")["p_mult"])
        self.assertEqual(self.c.execute("SELECT agent_id FROM tasks").fetchone()[0], "B01")  # technical writer -> тексты/документация
        self.assertEqual((st["tasks"], st["drafts"]), (2, 2))   # GOOD и US-only (со сниженной вероятностью)
        self.assertEqual(self.c.execute("SELECT origin FROM drafts").fetchone()[0], "template")
        self.assertEqual(ceo.run_cycle(self.c, notes.append, [Fake("fake", [GOOD, scam])])["found"], 0)  # дедуп

    def test_routing(self):
        o = lambda t, d="": {"title": t, "description": d, "division": "B"}
        agents.seed(self.c)
        self.assertEqual(ceo.route(self.c, o("Translator needed")), "B02"); self.assertEqual(ceo.route(self.c, o("Fix docs", "documentation")), "A10")
        self.assertEqual(ceo.route(self.c, o("Hackathon")), "E06"); self.assertTrue(ceo.route(self.c, o("Something odd")).startswith("B"))
    def test_pause_and_disable(self):
        db.put(self.c, "paused", 1); self.assertTrue(ceo.run_cycle(self.c, sources=[Fake("fake", [GOOD])])["skipped"])
        db.put(self.c, "paused", 0)
        bad = Fake("bad", exc=RuntimeError("x")); dis = []
        for _ in range(config.SOURCE_MAX_FAILS): dis += ceo.run_cycle(self.c, sources=[bad])["disabled"]
        self.assertEqual(dis, ["bad"])
        self.assertEqual(ceo.run_cycle(self.c, sources=[bad])["errors"], 0)   # отключён, не опрашивается
        improve.set_enabled(self.c, "bad", True); self.assertEqual(ceo.run_cycle(self.c, sources=[bad])["errors"], 1)
    def test_interval(self):
        s = Fake("slow", [GOOD]); s.interval = 60
        self.assertEqual(ceo.run_cycle(self.c, sources=[s])["found"], 1)
        s.items = [it("Other contract", "u9", "$50/hr contract")]
        self.assertEqual(ceo.run_cycle(self.c, sources=[s])["found"], 0)      # ещё рано
    def test_llm_paths(self):
        llm.complete = lambda s, u, **k: "Hello from AI"
        ceo.run_cycle(self.c, sources=[Fake("fake", [GOOD])])
        self.assertEqual(self.c.execute("SELECT origin,content FROM drafts").fetchone()[:], ("llm", "Hello from AI"))
        def boom(*a, **k): raise llm.LLMError("quota")
        llm.complete = boom
        did, origin, content = drafts.make(self.c, 1, "docs")
        self.assertEqual(origin, "template"); self.assertGreater(self.c.execute("SELECT COUNT(*) FROM errors WHERE where_='llm'").fetchone()[0], 0)
        with self.assertRaises(ValueError): drafts.make(self.c, 1, "nonsense")
        with self.assertRaises(ValueError): drafts.make(self.c, 999)

class TestImprove(Base):
    def test_p_grows_with_real_payments_only(self):
        p0 = improve.p_payout(self.c, "fake")
        ceo.run_cycle(self.c, sources=[Fake("fake", [GOOD])])
        self.assertEqual(improve.p_payout(self.c, "fake"), p0)               # найденное != оплаченное
        finance.add(self.c, "received", 30, "fake", tx_id="0xabcdef1")
        self.assertGreater(improve.p_payout(self.c, "fake"), p0)
        st = improve.source_stats(self.c)[0]; self.assertEqual((st["source"], st["received"], st["paid"]), ("fake", 30, 1))
    def test_snapshot_once_per_day(self):
        self.assertIsNotNone(improve.maybe_snapshot(self.c)); self.assertIsNone(improve.maybe_snapshot(self.c))
    def test_strategies(self):
        v1 = strategies.record(self.c, "s", {}, "a", "b", dict(sample=20, net=10, errors=1)); self.assertTrue(strategies.promote_if_better(self.c, "s", v1)[0])
        v2 = strategies.record(self.c, "s", {}, "a", "b", dict(sample=20, net=5, errors=1)); self.assertFalse(strategies.promote_if_better(self.c, "s", v2)[0])
        v3 = strategies.record(self.c, "s", {}, "a", "b", dict(sample=5, net=99, errors=0)); self.assertFalse(strategies.promote_if_better(self.c, "s", v3)[0])

class TestBot(Base):
    O = "42"
    def h(self, t, chat=42): return bot.handle(self.c, t, chat, self.O)
    def test_security_and_all_commands(self):
        self.assertIsNone(self.h("/status", 7)); self.assertIsNone(self.h("hello"))
        self.assertIn("chat id: 7", bot.handle(self.c, "/start", 7, ""))
        ceo.run_cycle(self.c, sources=[Fake("fake", [GOOD])])
        for cmd in bot.COMMANDS:
            self.assertIsInstance(self.h("/" + cmd), str, cmd)
        required = "status agents active tasks opportunities earnings received pending expenses profit top report errors limits pause resume approve reject history log_received log_expense".split()
        for r in required: self.assertIn(r, bot.COMMANDS)
    def test_flows(self):
        ceo.run_cycle(self.c, sources=[Fake("fake", [GOOD])])
        self.assertIn("Отказано", self.h("/log_received fake 5 test"))
        self.assertIn("Записано", self.h("/log_received fake 40 0xfeed1234"))
        self.assertIn("уже есть", self.h("/log_received fake 40 0xfeed1234"))
        self.assertIn("Записано", self.h("/log_expense fake 5")); self.assertIn("Записано", self.h("/log_pending fake 10 inv"))
        self.assertIn("Часы записаны", self.h("/log_hours 1 2"))
        self.assertIn("$17.50/час", self.h("/profit"))
        self.assertIn("Задача закрыта", self.h("/done 1")); self.assertIn("уже закрыта", self.h("/done 1"))
        self.assertIn("Профиль сохранён", self.h("/setprofile Python dev, 5 years"))
        self.assertIn("Python dev", self.h("/draft 1") + db.get(self.c, "profile"))
        self.assertIn("шаблон", self.h("/draft 1 docs")); self.assertIn("не найдена", self.h("/draft 777")); self.assertIn("Формат", self.h("/draft x"))
        self.assertIn("quiet", self.h("/notify quiet")); self.assertEqual(db.get(self.c, "notify_mode"), "quiet")
        self.h("/pause"); self.assertEqual(db.get(self.c, "paused"), "1"); self.h("/resume"); self.assertEqual(db.get(self.c, "paused"), "0")
        r = finance.request_payout(self.c, "0xNEW", 50, 1, "s"); self.assertIn("0xNEW", self.h("/approve"))
        self.assertEqual(self.h(f"/approve {r[1]}"), "Готово."); self.assertIn("не найдено", self.h(f"/approve {r[1]}").lower())
        self.assertIn("remotive", self.h("/sources")); self.assertIn("отключён", self.h("/source_off remotive")); self.assertIn("ОТКЛЮЧЁН", self.h("/sources")); self.assertIn("включён", self.h("/source_on remotive"))
    def test_command_crash_is_contained(self):
        orig = bot.COMMANDS["status"]; bot.COMMANDS["status"] = lambda c, a: 1 / 0
        try: self.assertIn("Ошибка выполнения", self.h("/status"))
        finally: bot.COMMANDS["status"] = orig
        self.assertEqual(self.c.execute("SELECT COUNT(*) FROM errors WHERE where_='cmd:status'").fetchone()[0], 1)
    def test_process_updates(self):
        config.OWNER = "42"; sent = []
        ups = {"result": [{"update_id": 10, "message": {"text": "/status", "chat": {"id": 42}}},
                          {"update_id": 11, "message": {"text": "/status", "chat": {"id": 99}}},      # чужой
                          {"update_id": 12, "edited_message": {}}, {"update_id": 13},                   # мусор
                          {"update_id": 14, "message": {"text": "/pause", "chat": {"id": 42}}}]}
        orig_api = bot.api; bot.api = lambda m, **k: ups
        try:
            self.assertEqual(bot.process_updates(self.c, lambda t, ch: sent.append((ch, t))), 5)
            self.assertEqual([ch for ch, _ in sent], [42, 42]); self.assertEqual(db.get(self.c, "tg_offset"), "15")
            def bad_send(t, ch): raise RuntimeError("tg down")
            ups["result"] = [{"update_id": 20, "message": {"text": "/status", "chat": {"id": 42}}}]
            bot.process_updates(self.c, bad_send); self.assertEqual(db.get(self.c, "tg_offset"), "21")   # офсет не теряется
        finally: bot.api = orig_api; config.OWNER = ""

class TestMonitor(Base):
    def test_all(self):
        st = ceo.run_cycle(self.c, sources=[Fake("fake", [GOOD])])
        self.assertTrue(monitor.should_send(self.c, st)); self.assertIn("задач 1", monitor.cycle_message(st))
        db.put(self.c, "notify_mode", "quiet"); self.assertFalse(monitor.should_send(self.c, st))
        db.put(self.c, "notify_mode", "events"); self.assertFalse(monitor.should_send(self.c, dict(st, tasks=0, drafts=0, errors=0, disabled=[])))
        db.put(self.c, "notify_mode", "all"); self.assertTrue(monitor.should_send(self.c, dict(st, tasks=0, drafts=0, errors=0, disabled=[])))
        morning = 1800000000 - (1800000000 % 86400) + 6 * 3600       # 06:00 UTC = 11:00 UTC+5
        self.assertTrue(monitor.digest_due(self.c, morning)); self.assertFalse(monitor.digest_due(self.c, morning + 60))
        self.assertIn("Отключены", monitor.cycle_message(dict(st, disabled=["x"])))

class TestSources(Base):
    def test_parsers(self):
        orig = sources._get
        try:
            sources._get = lambda u, **k: json.dumps({"jobs": [{"title": "Writer", "url": "https://r/1", "company_name": "Co", "salary": "$30/hr",
                "description": "<p>Write</p>", "job_type": "contract", "candidate_required_location": "Worldwide"}]})
            r = sources.Remotive({"name": "remotive", "categories": ["writing"]}).fetch()
            self.assertEqual((r[0]["title"], r[0]["location"], r[0]["only_gigs"]), ("Writer", "Worldwide", True)); self.assertNotIn("<p>", r[0]["description"])
            sources._get = lambda u, **k: json.dumps([{"legal": "x"}, {"position": "Editor", "company": "C", "url": "https://ok/1", "tags": ["a"],
                "salary_min": 40000, "salary_max": 60000, "location": "Worldwide", "description": "d"}])
            r = sources.RemoteOK({"name": "remoteok"}).fetch(); self.assertEqual((len(r), r[0]["annual_usd"]), (1, 50000))
            sources._get = lambda u, **k: "<rss><channel><item><title>Co: Copywriter</title><link>https://w/1</link><description>&lt;b&gt;hi&lt;/b&gt;</description></item></channel></rss>"
            r = sources.RSS({"name": "wwr", "url": "x"}).fetch(); self.assertEqual((r[0]["title"], r[0]["url"], r[0]["description"]), ("Co: Copywriter", "https://w/1", "hi"))
            sources._get = lambda u, **k: ('<feed xmlns="http://www.w3.org/2005/Atom"><entry><title>[HIRING] Translator</title><link href="https://rd/1"/><content>$30/hr</content></entry>'
                                           '<entry><title>[FOR HIRE] me</title><link href="https://rd/2"/></entry></feed>')
            r = sources.RSS({"name": "reddit", "url": "x", "title_contains": "[hiring]", "only_gigs": False}).fetch(); self.assertEqual((len(r), r[0]["url"]), (1, "https://rd/1"))
            sources._get = lambda u, **k: json.dumps({"items": [{"title": "Fix", "html_url": "https://github.com/a/b/issues/1", "body": "$100", "labels": [{"name": "bounty"}]}]})
            r = sources.GitHubBounties({"name": "gh", "division": "A"}).fetch(); self.assertEqual(r[0]["reward_kind"], "bounty")
        finally: sources._get = orig
    def test_config(self):
        names = [c["name"] for c in sources.load_configs()]; self.assertGreaterEqual(len(names), 5)
        self.assertEqual(len(sources.default_sources()), len(names))

class TestWorkflow(unittest.TestCase):
    def test_workflow(self):
        with open(os.path.join(os.path.dirname(os.path.dirname(__file__)), ".github/workflows/run.yml"), encoding="utf-8") as fh: txt = fh.read()
        for needle in ['*/15 3-15', "models: read", "contents: write", "origin HEAD:state", "if: always()", "timeout-minutes", "concurrency", "TELEGRAM_BOT_TOKEN", "GITHUB_TOKEN"]:
            self.assertIn(needle, txt)
        self.assertNotIn("|| true\n          git", txt)
        try:
            import yaml; d = yaml.safe_load(txt); self.assertIn("run", d["jobs"])
        except ImportError: pass
    def test_migration_old_db(self):
        import sqlite3, tempfile
        p = tempfile.mktemp(); o = sqlite3.connect(p)
        o.execute("CREATE TABLE opportunities(id INTEGER PRIMARY KEY, source TEXT, url TEXT UNIQUE, title TEXT, description TEXT, division TEXT, reward_usd REAL, cost_usd REAL, est_hours REAL, p_payout REAL, deadline TEXT, status TEXT, score REAL, flags TEXT, found_at REAL)")
        o.execute("CREATE TABLE tasks(id INTEGER PRIMARY KEY, opp_id INTEGER, agent_id TEXT, kind TEXT, status TEXT, created REAL, updated REAL, result TEXT, evidence TEXT)")
        o.commit(); o.close()
        c = db.connect(p); self.assertIn("p_mult", {r[1] for r in c.execute("PRAGMA table_info(opportunities)")}); self.assertIn("hours", {r[1] for r in c.execute("PRAGMA table_info(tasks)")})

if __name__ == "__main__":
    unittest.main(verbosity=1)
