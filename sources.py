"""Источники возможностей (публичные API/RSS). Настраиваются в sources.json.
У каждого источника свой min_interval_min, чтобы не нарушать лимиты и правила сервисов."""
import json, re, html, urllib.request, os
import xml.etree.ElementTree as ET
from . import config

UA = {"User-Agent": "money-hunters/2.0 (personal research bot)", "Accept": "application/json, application/rss+xml, application/atom+xml, */*"}
ATOM = "{http://www.w3.org/2005/Atom}"

def _get(url, timeout=20, headers=None):
    req = urllib.request.Request(url, headers={**UA, **(headers or {})})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", "replace")

def _strip(t, n=1500):
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html.unescape(t or ""))).strip()[:n]

class Source:
    def __init__(self, cfg):
        self.cfg = cfg
        self.name = cfg["name"]
        self.division = cfg.get("division", "B")
        self.interval = cfg.get("min_interval_min", 0)

class GitHubBounties(Source):
    def fetch(self):
        q = cfg_q = self.cfg.get("query", "label:bounty state:open is:issue no:assignee")
        import urllib.parse
        url = f"https://api.github.com/search/issues?q={urllib.parse.quote(q)}&sort=created&per_page=30"
        h = {"Accept": "application/vnd.github+json"}
        if os.environ.get("GITHUB_TOKEN"):
            h["Authorization"] = "Bearer " + os.environ["GITHUB_TOKEN"]
        data = json.loads(_get(url, headers=h))
        return [dict(source=self.name, division=self.division, title=i["title"], url=i["html_url"], reward_kind="bounty", only_gigs=False,
                     description=(i.get("body") or "")[:1500] + " " + " ".join(l["name"] for l in i.get("labels", [])))
                for i in data.get("items", [])]

class Remotive(Source):
    def fetch(self):
        out = []
        for cat in self.cfg.get("categories", ["writing"]):
            data = json.loads(_get(f"https://remotive.com/api/remote-jobs?category={cat}&limit=50"))
            for j in data.get("jobs", []):
                out.append(dict(source=self.name, division=self.division, title=j.get("title", ""), url=j.get("url", ""),
                                description=f'{j.get("company_name", "")} | {j.get("salary", "")} | ' + _strip(j.get("description", "")),
                                job_type=j.get("job_type", ""), location=j.get("candidate_required_location", ""),
                                reward_kind="gig", only_gigs=True))
        return out

class RemoteOK(Source):
    def fetch(self):
        out = []
        for j in json.loads(_get("https://remoteok.com/api")):
            if not isinstance(j, dict) or "position" not in j:
                continue  # первый элемент — юридическая заметка
            lo, hi = j.get("salary_min") or 0, j.get("salary_max") or 0
            out.append(dict(source=self.name, division=self.division, title=j["position"], url=j.get("url", ""),
                            description=f'{j.get("company", "")} | tags: {" ".join(j.get("tags", []))} | ' + _strip(j.get("description", "")),
                            location=j.get("location", ""), annual_usd=(lo + hi) / 2 if lo and hi else 0,
                            reward_kind="gig", only_gigs=True))
        return out

class RSS(Source):
    def fetch(self):
        root = ET.fromstring(_get(self.cfg["url"]))
        out, must = [], self.cfg.get("title_contains", "").lower()
        for it in list(root.iter("item")) + list(root.iter(ATOM + "entry")):
            title = (it.findtext("title") or it.findtext(ATOM + "title") or "").strip()
            link = (it.findtext("link") or "").strip()
            if not link:
                le = it.find(ATOM + "link")
                link = le.get("href", "") if le is not None else ""
            desc = it.findtext("description") or it.findtext(ATOM + "content") or it.findtext(ATOM + "summary") or ""
            if must and must not in title.lower():
                continue
            out.append(dict(source=self.name, division=self.division, title=html.unescape(title), url=link, description=_strip(desc),
                            reward_kind="gig", only_gigs=self.cfg.get("only_gigs", True)))
        return out

BUILDERS = {"github_bounties": GitHubBounties, "remotive": Remotive, "remoteok": RemoteOK, "rss": RSS}

DEFAULT = [
 {"type": "github_bounties", "name": "github-bounties", "division": "A", "min_interval_min": 15, "enabled": True},
 {"type": "remotive", "name": "remotive", "division": "B", "categories": ["writing", "qa", "software-dev"], "min_interval_min": 360, "enabled": True},
 {"type": "remoteok", "name": "remoteok", "division": "B", "min_interval_min": 180, "enabled": True},
 {"type": "rss", "name": "weworkremotely", "division": "B", "url": "https://weworkremotely.com/remote-jobs.rss", "min_interval_min": 60, "enabled": True},
 {"type": "rss", "name": "reddit-forhire", "division": "B", "url": "https://www.reddit.com/r/forhire/new/.rss", "title_contains": "[hiring]",
  "only_gigs": False, "min_interval_min": 60, "enabled": True},
]

def load_configs():
    try:
        doc = json.loads(config.SOURCES_FILE.read_text())
    except (FileNotFoundError, ValueError):
        return list(DEFAULT)
    cfgs = doc.get("sources")
    if cfgs is None:  # старый формат {"rss": [...]}
        cfgs = list(DEFAULT) + [dict(type="rss", **s) for s in doc.get("rss", [])]
    return cfgs

def default_sources():
    out = []
    for cfg in load_configs():
        if cfg.get("enabled", True) and cfg.get("type") in BUILDERS and cfg.get("name"):
            out.append(BUILDERS[cfg["type"]](cfg))
    return out
