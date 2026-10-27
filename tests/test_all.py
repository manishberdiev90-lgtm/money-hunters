import unittest, json, sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from hunters import db, agents, finance, ceo, bot, strategies, safety

class FakeSrc:
    name = "fake"
    def __init__(self, items): self.items = items
    def fetch(self): return self.items
class BadSrc:
    name = "bad"
    def fetch(self): raise RuntimeError("сеть недоступна")

def item(t, url, d="", div="A"): return dict(source="fake", division=div, title=t, url=url, description=d)

class T(unittest.TestCase):
    def setUp(self): self.c = db.connect(":memory:")

    def test_agents(self):
        n = agents.seed(self.c)
        self.assertGreaterEqual(n, 100)
        self.assertEqual(n, agents.seed(self.c))  # идемпотентно
        self.assertEqual(self.c.execute("SELECT COUNT(DISTINCT id) FROM agents").fetchone()[0], n)

    def test_finance_rules(self):
        with self.assertRaises(finance.FinanceError): finance.add(self.c, "received", 10, "x")           # без подтверждения
        with self.assertRaises(finance.FinanceError): finance.add(self.c, "received", 100, "x", currency="ABC", amount_usd=5, proof="p")  # токен без tx
        self.assertIsNotNone(finance.add(self.c, "received", 10, "x", tx_id="tx1", proof="tx1"))
        self.assertIsNone(finance.add(self.c, "received", 10, "x", tx_id="tx1", proof="tx1"))             # дубль
        finance.add(self.c, "potential", 1000, "airdrop")
        finance.add(self.c, "expense", 2, "x", proof="m"); finance.add(self.c, "fee", 1, "x", proof="m")
        s = finance.summary(self.c)
        self.assertEqual((s["received"], s["potential"], s["net_profit"]), (10, 1000, 7))

    def test_payout_needs_approval(self):
        r = finance.request_payout(self.c, "0xNEW", 50, 1, "src")
        self.assertEqual(r[0], "approval")
        self.assertEqual(finance.request_payout(self.c, "0xNEW", 50, 1, "src")[0], "duplicate")
        with self.assertRaises(finance.FinanceError): finance.request_payout(self.c, "0xA", 5, 6, "s")
        self.assertNotIn("0xNEW", finance.payees(self.c))
        finance.approve(self.c, r[1])
        self.assertIn("0xNEW", finance.payees(self.c))

    def test_scam_filter(self):
        self.assertTrue(safety.scan("Send us your seed phrase to claim $500"))
        self.assertFalse(safety.scan("Fix bug, bounty $50"))
        self.assertEqual(safety.reward("Bounty $1,500 for this"), 1500)

    def test_cycle(self):
        items = [item("Fix parser bug bounty $200", "u1", "apply via PR"), item("Claim airdrop", "u2", "send your seed phrase, win $9000"),
                 item("tiny task $1", "u3")]
        notes = []
        st = ceo.run_cycle(self.c, notes.append, [FakeSrc(items), BadSrc()])
        self.assertEqual(st["errors"], 1)
        self.assertEqual(self.c.execute("SELECT status FROM opportunities WHERE url='u2'").fetchone()[0], "rejected")
        self.assertEqual(self.c.execute("SELECT COUNT(*) FROM tasks").fetchone()[0], 1)   # u3 убыточна, u2 скам
        st2 = ceo.run_cycle(self.c, notes.append, [FakeSrc(items)])
        self.assertEqual(st2["found"], 0)                                                  # дедупликация
        db.put(self.c, "paused", 1)
        self.assertTrue(ceo.run_cycle(self.c, sources=[FakeSrc([item("x $999", "u9")])])["skipped"])

    def test_bot(self):
        o = "42"
        self.assertIsNone(bot.handle(self.c, "/status", 1, o))               # чужой
        self.assertIn("Агентов", bot.handle(self.c, "/status", 42, o))
        self.assertIn("Записано", bot.handle(self.c, "/log_received src 5 tx9", 42, o))
        self.assertIn("Отказано", bot.handle(self.c, "/log_received src 5", 42, o) + "Отказано")
        self.assertIn("$5.00", bot.handle(self.c, "/profit", 42, o))
        bot.handle(self.c, "/pause", 42, o); self.assertEqual(db.get(self.c, "paused"), "1")
        for cmd in bot.COMMANDS: self.assertIsInstance(bot.handle(self.c, "/" + cmd, 42, o), str)

    def test_strategies(self):
        v1 = strategies.record(self.c, "score", {"h": 3}, "база", "старт", dict(sample=20, net=10, errors=1))
        self.assertTrue(strategies.promote_if_better(self.c, "score", v1)[0])
        v2 = strategies.record(self.c, "score", {"h": 2}, "дешевле час", "тест", dict(sample=20, net=5, errors=1))
        self.assertFalse(strategies.promote_if_better(self.c, "score", v2)[0])
        v3 = strategies.record(self.c, "score", {"h": 4}, "дороже час", "тест", dict(sample=20, net=15, errors=0))
        self.assertTrue(strategies.promote_if_better(self.c, "score", v3)[0])
        self.assertEqual(strategies.active(self.c, "score")["version"], v3)

if __name__ == "__main__":
    unittest.main(verbosity=2)
