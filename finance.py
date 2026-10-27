"""Финансовый центр. Деньгами считаются ТОЛЬКО записи kind='received' с подтверждением."""
import time, json, hashlib
from .db import get, put, log

KINDS = ("potential", "earned_unpaid", "confirmed", "received", "expense", "fee")
FIAT = {"USD", "EUR", "USDT", "USDC", "RUB", "TJS"}
MIN_PAYOUT_USD = 1.0
JUNK = {"test", "none", "n/a", "na", "-", "tx", "txid", "proof", "manual", "fake", "example", "abc", "xxx", "123", "1234", "12345", "123456", "000000"}

class FinanceError(ValueError):
    pass

def _proof_ok(*vals):
    for v in vals:
        v = (v or "").strip().lower()
        if len(v) >= 6 and v not in JUNK and len(set(v)) > 2:
            return True
    return False

def add(c, kind, amount, source, currency="USD", amount_usd=None, status="", proof="", tx_id=None, idem=None):
    if kind not in KINDS:
        raise FinanceError(f"неизвестный тип {kind}")
    if not (0 < amount < 10_000_000):
        raise FinanceError("сумма вне допустимого диапазона")
    currency = currency.upper()
    if amount_usd is None:
        if currency in ("USD", "USDT", "USDC"):
            amount_usd = amount
        else:
            raise FinanceError("для EUR/RUB/TJS и токенов укажите amount_usd по фактическому курсу")
    if kind in ("received", "confirmed") and not _proof_ok(proof, tx_id):
        raise FinanceError("received/confirmed требуют реального подтверждения (хеш транзакции, ID выплаты или ссылка, ≥6 символов)")
    if kind == "received" and currency not in FIAT and not tx_id:
        raise FinanceError("токены считаются полученными только с tx_id и фактической стоимостью при выводе")
    if kind in ("received", "confirmed") and tx_id and c.execute("SELECT 1 FROM ledger WHERE kind=? AND tx_id=?", (kind, tx_id)).fetchone():
        return None  # тот же платёж уже учтён
    idem = idem or hashlib.sha256(f"{kind}|{source}|{amount}|{currency}|{tx_id}|{proof}".encode()).hexdigest()
    try:
        cur = c.execute("INSERT INTO ledger(ts,source,kind,amount,currency,amount_usd,status,proof,tx_id,idem) VALUES(?,?,?,?,?,?,?,?,?,?)",
                        (time.time(), source, kind, amount, currency, amount_usd, status, proof, tx_id, idem))
    except Exception as e:
        if "UNIQUE" in str(e):
            return None
        raise
    c.commit()
    return cur.lastrowid

def log_hours(c, task_id, hours):
    if not (0 < hours <= 24):
        raise FinanceError("часы должны быть от 0 до 24 за одну запись")
    if not c.execute("SELECT 1 FROM tasks WHERE id=?", (task_id,)).fetchone():
        raise FinanceError("задача не найдена")
    c.execute("UPDATE tasks SET hours=COALESCE(hours,0)+?, updated=? WHERE id=?", (hours, time.time(), task_id))
    c.commit()

def summary(c):
    s = {k: 0.0 for k in KINDS}
    for r in c.execute("SELECT kind, SUM(amount_usd) t FROM ledger GROUP BY kind"):
        s[r["kind"]] = r["t"] or 0.0
    s["net_profit"] = s["received"] - s["expense"] - s["fee"]
    s["hours"] = c.execute("SELECT COALESCE(SUM(hours),0) FROM tasks").fetchone()[0]
    s["net_per_hour"] = s["net_profit"] / s["hours"] if s["hours"] > 0 else None
    # оценка выгоды по открытым задачам: ПРОГНОЗ, не деньги
    s["pipeline"] = c.execute("SELECT COALESCE(SUM(score),0) FROM opportunities WHERE status='needs_owner' AND score>0").fetchone()[0]
    return s

def by_source(c):
    return c.execute("""SELECT source, SUM(CASE WHEN kind='received' THEN amount_usd ELSE 0 END) rec,
        SUM(CASE WHEN kind IN ('expense','fee') THEN amount_usd ELSE 0 END) cost FROM ledger GROUP BY source ORDER BY rec-cost DESC""").fetchall()

# ---- выплаты: система ничего не отправляет сама, только проверяет и просит одобрение ----
def payees(c):
    return json.loads(get(c, "payees", "[]"))

def request_payout(c, address, amount_usd, fee_usd, source):
    if amount_usd < MIN_PAYOUT_USD:
        raise FinanceError("сумма ниже минимальной")
    if fee_usd >= amount_usd:
        raise FinanceError("комиссия съедает всю сумму")
    idem = hashlib.sha256(f"payout|{address}|{amount_usd}|{source}".encode()).hexdigest()[:16]
    if c.execute("SELECT 1 FROM approvals WHERE payload LIKE ?", (f'%"idem": "{idem}"%',)).fetchone():
        return ("duplicate", None)
    payload = json.dumps({"address": address, "amount_usd": amount_usd, "fee_usd": fee_usd, "source": source, "idem": idem})
    kind = "payout" if address in payees(c) else "payout_new_payee"
    cur = c.execute("INSERT INTO approvals(ts,kind,payload) VALUES(?,?,?)", (time.time(), kind, payload))
    c.commit()
    return ("approval", cur.lastrowid)

def approve(c, aid, approve_it=True):
    r = c.execute("SELECT * FROM approvals WHERE id=? AND status='pending'", (aid,)).fetchone()
    if not r:
        return None
    c.execute("UPDATE approvals SET status=? WHERE id=?", ("approved" if approve_it else "rejected", aid))
    c.commit()
    p = json.loads(r["payload"])
    if approve_it and r["kind"] == "payout_new_payee":
        put(c, "payees", json.dumps(sorted(set(payees(c)) | {p["address"]})))
    log(c, "F00", "approval_" + ("yes" if approve_it else "no"), r["payload"])
    return r
