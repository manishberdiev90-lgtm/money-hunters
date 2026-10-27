"""Источники возможностей. Только публичные API/RSS. Список RSS правится в sources.json."""
import json, urllib.request, urllib.parse, xml.etree.ElementTree as ET
from . import config

UA = {"User-Agent": "money-hunters/1.0"}

def _get(url, timeout=15):
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=timeout) as r:
        return r.read().decode("utf-8", "replace")

class GitHubBounties:
    name = "github-bounties"
    def fetch(self):
        q = urllib.parse.quote('label:bounty state:open is:issue no:assignee')
        data = json.loads(_get(f"https://api.github.com/search/issues?q={q}&sort=created&per_page=20"))
        return [dict(source=self.name, division="A", title=i["title"], url=i["html_url"],
                     description=(i.get("body") or "")[:1500] + " " + " ".join(l["name"] for l in i.get("labels", [])))
                for i in data.get("items", [])]

class RSS:
    def __init__(self, name, url, division="E"):
        self.name, self.url, self.division = name, url, division
    def fetch(self):
        root = ET.fromstring(_get(self.url))
        out = []
        for it in root.iter("item"):
            g = lambda t: (it.findtext(t) or "").strip()
            out.append(dict(source=self.name, division=self.division, title=g("title"), url=g("link"), description=g("description")[:1500]))
        return out

def default_sources():
    srcs = [GitHubBounties()]
    try:
        for s in json.loads(config.SOURCES_FILE.read_text()).get("rss", []):
            srcs.append(RSS(s["name"], s["url"], s.get("division", "E")))
    except FileNotFoundError:
        pass
    return srcs
