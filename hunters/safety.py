import re
SCAM = [r"seed ?phrase", r"recovery phrase", r"private key", r"секретн\w+ фраз", r"приватн\w+ ключ", r"send (us )?(eth|btc|usdt|funds)",
        r"double your", r"guaranteed (profit|return)", r"registration fee", r"pay (a )?fee to (join|withdraw)",
        r"гарантированн\w+ (доход|прибыл)", r"оплатите (взнос|комиссию) для (вывода|участия)"]
PAY = re.compile(r"\$\s?(\d[\d,]*(?:\.\d+)?)|(\d[\d,]*(?:\.\d+)?)\s?(?:USD|USDT|USDC)\b", re.I)

def scan(text):
    t = (text or "").lower()
    return [p for p in SCAM if re.search(p, t)]

def reward(text):
    vals = []
    for m in PAY.finditer(text or ""):
        try:
            vals.append(float((m.group(1) or m.group(2)).replace(",", "")))
        except ValueError:
            pass
    vals = [v for v in vals if 0 < v < 100000]
    return max(vals) if vals else 0.0
