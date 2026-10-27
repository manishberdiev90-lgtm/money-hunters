"""Антискам, парсинг оплаты, проверка доступности по стране и способам выплаты."""
import re
from urllib.parse import urlparse

# (regex, вес риска, причина). Риск >= 60 => автоматический отказ.
SCAM = [
 (r"seed ?phrase|recovery phrase|mnemonic|private key|секретн\w+ фраз|приватн\w+ ключ|сид-?фраз", 100, "запрос секретных ключей/seed-фразы"),
 (r"(share|send|enter|provide|give).{0,20}(wallet|account|exchange|bank).{0,15}(password|credentials|login)", 80, "запрос паролей/доступов"),
 (r"send (us |me )?(eth|btc|usdt|sol|crypto|funds|bitcoin)|отправьте.{0,40}(usdt|btc|eth|крипт)", 80, "просьба отправить средства"),
 (r"double your|2x your|guaranteed (profit|return|income|payout|earnings)|risk[- ]free|гарантированн\w+ (доход|прибыл|выплат)|удво\w+ (депозит|вложен)", 70, "ложная гарантия дохода"),
 (r"registration fee|activation fee|processing fee|security deposit|pay (a )?(small |one-time )?fee|pay to (join|apply|start|withdraw)|"
  r"buy (a |the )?(starter )?(kit|equipment|license|software|gift ?cards?)|оплатите (взнос|комиссию|регистрацию)|вступительный взнос|внесите (депозит|залог)", 70, "требование предоплаты/взноса"),
 (r"(deposit|cash) (the |this |a )?che(ck|que)|overpay|send back the (difference|balance|excess)", 70, "схема с чеком/переплатой"),
 (r"connect (your )?wallet.{0,80}(claim|airdrop)|(claim|airdrop).{0,80}connect (your )?wallet", 60, "подключение кошелька ради 'клейма' (дрейнер)"),
 (r"connect (your )?wallet|approve (the )?(transaction|spending|token)|setapprovalforall", 30, "запрос подключения кошелька/approve"),
 (r"no experience (needed|required).{0,60}\$\s?\d{3,}\s?(/|per|a)\s?(day|week)|без опыта.{0,50}\d{3,}.{0,12}(в день|в сутки|в неделю)", 60, "нереальный доход без опыта"),
 (r"earn \$?\d{2,}\s?(/|per|a)\s?(day|hour) (from home|online)|заработ\w+ \d{3,}.{0,10}(в день|в сутки)", 40, "обещание лёгкого дохода"),
 (r"(contact|message|text|dm|write)( us| me)?( only)? (on|via|in|through) (whatsapp|telegram|signal)|пишите (только )?(в|на) (whatsapp|ватсап|telegram|телеграм)", 35, "общение только через мессенджер"),
 (r"urgent(ly)? hiring|act now|limited (spots|time|slots)|hurry up|срочно требуются|количество мест ограничено", 15, "давление срочностью"),
 (r"пассивный доход|passive income", 20, "обещание пассивного дохода"),
 (r"вложите|invest (at least|a minimum)", 40, "требуются вложения"),
]
SHORTENERS = {"bit.ly", "tinyurl.com", "t.co", "goo.gl", "ow.ly", "is.gd", "cutt.ly", "rebrand.ly", "t.ly", "shorturl.at", "rb.gy", "tiny.cc", "buff.ly"}
RISKY_TLDS = {"zip", "mov", "top", "xyz", "click", "icu", "gq", "tk", "ml", "ga", "cf", "work", "rest", "buzz", "monster", "cyou", "sbs"}
BRANDS = {"paypal": "paypal.com", "binance": "binance.com", "metamask": "metamask.io", "coinbase": "coinbase.com",
          "upwork": "upwork.com", "fiverr": "fiverr.com", "telegram": "telegram.org", "payoneer": "payoneer.com", "wise": "wise.com"}
TRUSTED = ("github.com", "remotive.com", "remoteok.com", "weworkremotely.com", "reddit.com", "linkedin.com", "docs.google.com", "notion.so")
URL_RE = re.compile(r"https?://[^\s<>\"')\]]+", re.I)
IP_RE = re.compile(r"^\d{1,3}(\.\d{1,3}){3}$")

def _trusted(host):
    return any(host == t or host.endswith("." + t) for t in TRUSTED)

def url_risk(u):
    p = urlparse(u if "://" in u else "http://" + u)
    host = (p.hostname or "").lower()
    if not host or _trusted(host):
        return 0, []
    risk, why = 0, []
    if host in SHORTENERS: risk += 30; why.append(f"сокращённая ссылка ({host})")
    if "xn--" in host: risk += 40; why.append("punycode-домен")
    if IP_RE.match(host): risk += 40; why.append("ссылка на IP-адрес")
    if "@" in (p.netloc or ""): risk += 50; why.append("логин@ в ссылке")
    if host.rsplit(".", 1)[-1] in RISKY_TLDS: risk += 20; why.append(f"рискованная зона .{host.rsplit('.', 1)[-1]}")
    if host.count("-") >= 3: risk += 15; why.append("много дефисов в домене")
    if p.scheme == "http": risk += 10; why.append("http без шифрования")
    for brand, dom in BRANDS.items():
        if brand in host and not (host == dom or host.endswith("." + dom)):
            risk += 50; why.append(f"имитация бренда {brand}: {host}")
    return risk, why

def assess(text, url=""):
    """-> (риск 0..100, [причины])."""
    t = text or ""
    risk, reasons = 0, []
    for pat, w, why in SCAM:
        if re.search(pat, t, re.I | re.S):
            risk += w; reasons.append(why)
    urls = set(URL_RE.findall(t))
    if url:
        urls.add(url)
    for u in urls:
        r, w = url_risk(u)
        risk += r; reasons += w
    return min(100, risk), list(dict.fromkeys(reasons))

# ---------- оплата ----------
PAY = re.compile(r"\$\s?(\d[\d,]*(?:\.\d+)?)|(\d[\d,]*(?:\.\d+)?)\s?(?:USD|USDT|USDC)\b", re.I)
HOURLY = re.compile(r"\$\s?(\d+(?:\.\d+)?)(?:\s?[-–]\s?\$?\s?(\d+(?:\.\d+)?))?\s?(?:/|per|an|a)\s?(?:hr|hour)\b", re.I)
RANGE = re.compile(r"\$\s?(\d[\d,]*(?:\.\d+)?)\s?(k)?\s?(?:-|–|to)\s?\$?\s?(\d[\d,]*(?:\.\d+)?)\s?(k)?", re.I)

def reward(text):
    vals = []
    for m in PAY.finditer(text or ""):
        try:
            vals.append(float((m.group(1) or m.group(2)).replace(",", "")))
        except ValueError:
            pass
    vals = [v for v in vals if 0 < v < 1000000]
    return max(vals) if vals else 0.0

def hourly_usd(text):
    """$/час из '$25/hr', '$20-30 per hour' или годовой вилки '$60,000 - $80,000' (/2000 ч)."""
    t = text or ""
    m = HOURLY.search(t)
    if m:
        a = float(m.group(1)); b = float(m.group(2)) if m.group(2) else a
        return (a + b) / 2
    for m in RANGE.finditer(t):
        def num(v, k):
            x = float(v.replace(",", ""))
            return x * 1000 if k else x
        a, b = num(m.group(1), m.group(2)), num(m.group(3), m.group(4) or m.group(2))
        if a >= 10000 and b >= 10000:
            return round((a + b) / 2 / 2000, 2)
    return 0.0

# ---------- география и способы выплаты ----------
RESTRICT = re.compile(r"(?:\b(?:us|u\.s\.|usa|uk|canada|eu|europe|north america|latam|australia|germany|france)\b[ -]*(?:only|residents?|citizens?|based)"
                      r"|(?:must|need to|should)\s+(?:be\s+)?(?:located|based|reside|live)\s+(?:in|within)\s+(?:the\s+)?(?:us|usa|united states|uk|canada|eu|europe)"
                      r"|(?:us|united states)\s+(?:citizens?|work authorization)|authorized to work in|right to work in)", re.I)
OK_LOC = re.compile(r"worldwide|anywhere|global|asia|tajikistan|central asia|international|any country", re.I)

def geo(text, location=""):
    """Эвристика: можно ли участвовать из Таджикистана. Это НЕ гарантия — условия нужно читать в источнике."""
    if RESTRICT.search(text or ""):
        return False, "ограничение по стране в тексте"
    loc = (location or "").strip()
    if loc and not OK_LOC.search(loc):
        return False, f"локация: {loc[:40]}"
    return True, ""

US_ONLY_PAY = re.compile(r"\b(venmo|zelle|cash ?app|direct deposit|ach)\b|\bw-?9\b|\bssn\b|social security", re.I)
CHECK_PAY = re.compile(r"\b(paypal|wise|stripe|upwork|fiverr|payoneer)\b", re.I)

def payout(text):
    """-> (множитель вероятности выплаты, заметка)."""
    if US_ONLY_PAY.search(text or ""):
        return 0.3, "оплата через метод, вероятно недоступный из Таджикистана"
    m = CHECK_PAY.search(text or "")
    if m:
        return 0.7, f"оплата через {m.group(1)}: проверьте, доступен ли вывод у вас"
    return 1.0, ""
