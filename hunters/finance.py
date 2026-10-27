"""Финансовый центр. Деньгами считаются ТОЛЬКО записи kind='received' с подтверждением."""
import time, json, hashlib
from .db import get, put, log

KINDS = ("potential", "earned_unpaid", "confirmed", "received", "expense", "fee")
FIAT = {"USD", "EUR", "USDT", "USDC", "RUB", "TJS"}
MIN_PAYOUT_USD = 1.0

class FinanceError(ValueError):
    pass

def add(c, kind, amount, source, currency="USD", amount_usd=None, status="", proof="", tx_id=None, idem=None):
    if kind not in KINDS:
        raise FinanceError(f"неизвестный тип {kind}")
    if amount <= 0:
        raise FinanceError("сумма должна быть > 0")
    currency = currency.upper()
    if amount_usd is None:
        if currency in ("USD", "USDT", "USDC"):
            amount_usd = amount
        else:
            raise FinanceError("для EUR/RUB/TJS и токенов укажите amount_usd по фактическому курсу")
    if kind in ("received", "confirmed") and not (proof or tx_id):
        raise FinanceError("received/confirmed требуют подтверждения (proof или tx_id)")
    if kind == "received" and currency not in FIAT and not tx_id:
        raise FinanceError("токены считаются полученными только с tx_id и фактической стоимостью при выводе")
    idem = idem or hashlib.sha256(f"{kind}|{source}|{amount}|{currency}|{tx_id}|{proof}".encode()).hexdigest()
    try:
        cur = c.execute("INSERT INTO ledger(ts,source,kind,amount,currency,amount_usd,status,proof,tx_id,idem) VALUES(?,?,?,?,?,?,?,?,?,?)",
                        (time.time(), source, kind, amount, currency, amount_usd, status, proof, tx_id, idem))
    except Exception as e:
        if "UNIQUE" in str(e):
            return None  # повторная запись — защита от дублей
        raise
    c.commit()
    return cur.lastrowid

def summary(c):
    s = {k: 0.0 for k in KINDS}
    for r in c.execute("SELECT kind, SUM(amount_usd) t FROM ledger GROUP BY kind"):
        s[r["kind"]] = r["t"] or 0.0
    s["net_profit"] = s["received"] - s["expense"] - s["fee"]
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
