#!/usr/bin/env python3
# ::ILANG
# [TYPE:module][PROJECT:hostingdeals][LANG:zh]
# ::STATE{@SELF, role:scraper, reads:.ilang/site.ilang, writes:data/offers.json}
# ::RULE{入口和字段只从 .ilang/site.ilang 读 不许在代码里另写一份厂商清单}
# ::RULE{只抓公开页面 sitemap 与官方接口 遵守 robots.txt 抓不到的字段一律留空}
# ::BOUNDARY{never:编优惠 编价格 编折扣码 编佣金|scope:permanent}

"""Read .ilang/site.ilang, fetch public provider sources, write data/offers.json.

Zero third-party dependencies: standard library only.
Deterministic: same inputs -> same outputs (apart from fetched_at / source changes).
"""

import gzip
import html
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(ROOT, ".ilang", "site.ilang")
OUT_PATH = os.path.join(ROOT, "data", "offers.json")

DEFAULT_SCRAPE = {
    "timeout": "25",
    "delay": "1.0",
    "max_pages_per_sitemap": "4",
    "max_api_items": "6",
    "sitemap_keywords": "promo,deal,coupon,discount,offer,pricing,save",
    "respect_robots": "true",
    "user_agent": "hostingdeals-promo-radar/1.0 (public data only)",
}


# --------------------------------------------------------------------------
# I-Lang config
# --------------------------------------------------------------------------
def load_config(path=CONFIG_PATH):
    with open(path, "r", encoding="utf-8") as fh:
        lines = fh.read().splitlines()

    cfg = {"site": {}, "providers": [], "fields": [], "scrape": dict(DEFAULT_SCRAPE), "render": {}}
    section = None
    for raw in lines:
        line = raw.strip()
        if not line or line.startswith("#"):
            continue

        m = re.match(r"^::STATE\{\s*@(\w+)\s*,(.*)\}\s*$", line)
        if m:
            if m.group(1).upper() == "SITE":
                for pair in m.group(2).split(","):
                    if ":" in pair:
                        k, v = pair.split(":", 1)
                        cfg["site"][k.strip()] = v.strip()
            continue

        m = re.match(r"^::MODULE\{(\w+)", line)
        if m:
            section = m.group(1).lower()
            continue

        if line.startswith("::"):
            section = None
            continue

        if section == "providers":
            if line.startswith("<") or line.startswith("["):
                continue
            parts = [p.strip() for p in line.split("|")]
            if len(parts) < 3 or not parts[0]:
                continue
            cfg["providers"].append(
                {
                    "name": parts[0],
                    "homepage": parts[1],
                    "entry": parts[2],
                    "landing": parts[3] if len(parts) > 3 else "",
                    "affiliate": parts[4] if len(parts) > 4 else "",
                }
            )
        elif section == "fields":
            if re.fullmatch(r"[a-z_]+(\s+[a-z_]+)*", line):
                cfg["fields"] = line.split()
        elif section in ("scrape", "render"):
            m = re.match(r"^([a-z_]+)\s*:\s*(.*)$", line)
            if m:
                cfg[section][m.group(1)] = m.group(2).strip()

    if not cfg["fields"]:
        cfg["fields"] = "title price currency offer_url valid_until source_url fetched_at".split()
    return cfg


# --------------------------------------------------------------------------
# HTTP
# --------------------------------------------------------------------------
class Fetcher:
    def __init__(self, user_agent, timeout, delay, respect_robots=True):
        self.user_agent = user_agent
        self.timeout = timeout
        self.delay = delay
        self.respect_robots = respect_robots
        self._robots = {}
        self.log = []

    def _robots_rules(self, url):
        parts = urllib.parse.urlsplit(url)
        origin = "%s://%s" % (parts.scheme, parts.netloc)
        if origin in self._robots:
            return self._robots[origin]
        rules = []
        try:
            req = urllib.request.Request(
                origin + "/robots.txt", headers={"User-Agent": self.user_agent}
            )
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                body = resp.read().decode("utf-8", "ignore")
            agent = None
            for line in body.splitlines():
                line = line.split("#", 1)[0].strip()
                if not line:
                    continue
                low = line.lower()
                if low.startswith("user-agent:"):
                    agent = line.split(":", 1)[1].strip()
                elif low.startswith(("disallow:", "allow:")) and agent in ("*", self.user_agent):
                    kind, value = line.split(":", 1)
                    rules.append((kind.strip().lower(), value.strip()))
        except Exception:
            self._robots[origin] = rules
            return rules
        self._robots[origin] = rules
        return rules

    def allowed(self, url):
        if not self.respect_robots:
            return True
        path = urllib.parse.urlsplit(url).path or "/"
        best = None
        for kind, value in self._robots_rules(url):
            if not value:
                continue
            if path.startswith(value) and (best is None or len(value) > len(best[1])):
                best = (kind, value)
        if best is None:
            return True
        return best[0] == "allow"

    def get(self, url):
        """Return (final_url, text) or raise."""
        if not self.allowed(url):
            raise RuntimeError("robots.txt disallows %s" % url)
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": self.user_agent,
                "Accept": "text/html,application/xhtml+xml,application/xml,application/json;q=0.9,*/*;q=0.8",
                "Accept-Encoding": "gzip, identity",
            },
        )
        with urllib.request.urlopen(req, timeout=self.timeout) as resp:
            data = resp.read()
            final_url = resp.geturl()
            encoding = (resp.headers.get("Content-Encoding") or "").lower()
        if "gzip" in encoding or data[:2] == b"\x1f\x8b":
            try:
                data = gzip.decompress(data)
            except OSError:
                pass
        if self.delay:
            time.sleep(self.delay)
        return final_url, data.decode("utf-8", "ignore")

    def note(self, text):
        self.log.append(text)
        print("[scrape] " + text)


# --------------------------------------------------------------------------
# Extraction
# --------------------------------------------------------------------------
TAG_RE = re.compile(r"<(script|style|noscript)\b.*?</\1>", re.I | re.S)
COMMENT_RE = re.compile(r"<!--.*?-->", re.S)
ANY_TAG_RE = re.compile(r"<[^>]+>")

PRICE_RE = re.compile(
    r"(?P<sym>[$€£])\s*(?P<num>\d{1,5}(?:[.,]\d{1,2})?)\s*(?:(?:USD|EUR|GBP)\s*)?"
    r"(?:/\s*|per\s*)?(?P<unit>mo|month|monthly|yr|year|yearly|annually)\b",
    re.I,
)
PCT_RE = re.compile(r"(?P<pct>\d{1,2})\s?%\s*(?:off|discount)\b", re.I)
SAVE_RE = re.compile(r"(?:save|up\s+to)\s*(?P<pct>\d{1,2})\s?%", re.I)
CODE_RE = re.compile(
    r"(?:promo\s*code|coupon\s*code|discount\s*code|voucher\s*code|use\s*code)\s*[:=]?\s*"
    r"[\"'’]?(?P<code>[A-Z0-9][A-Z0-9\-_]{2,20})\b"
)
DATE_HINT_RE = re.compile(
    r"(?:valid\s+(?:through|until)|through|until|ends(?:\s+on)?|expires?(?:\s+on)?)\s*[: ]*"
    r"(?P<date>[A-Za-z]{3,9}\.?\s+\d{1,2}(?:st|nd|rd|th)?,?\s+\d{4}"
    r"|\d{1,2}\s+[A-Za-z]{3,9}\.?\s+\d{4}|\d{4}-\d{2}-\d{2}|\d{1,2}/\d{1,2}/\d{4})",
    re.I,
)
DATE_FORMATS = (
    "%B %d, %Y", "%b %d, %Y", "%B %d %Y", "%b %d %Y",
    "%d %B %Y", "%d %b %Y", "%Y-%m-%d", "%m/%d/%Y",
)

SYMBOL_CURRENCY = {"$": "USD", "€": "EUR", "£": "GBP"}

# Words that mark a price/discount as belonging to an add-on rather than a plan.
ADDON_WORDS = (
    "add-on", "addon", "add on", "/domain", "per domain", "dns", "cdn", "ssl",
    "backup", "support", "invoice", "worth", "migration", "email", "seat",
    "license", "storage", "object cache", "malware", "protection", "rackspace",
)
# Words that tie a discount to an actual hosting plan.
PLAN_WORDS = (
    "plan", "plans", "hosting", "server", "vps", "droplet", "cloud",
    "shared", "wordpress", "starter", "unlimited", "starting at", "starting from",
    "for 3 months", "first year", "on sale", "save", "per month",
)


def context_of(text, start, end, pad=70, pad_after=None):
    """Words just before (and a few after) a match - enough to classify it."""
    after = pad if pad_after is None else pad_after
    return text[max(0, start - pad) : end + after].lower()


def plan_score(text, start, end):
    """+1 if the snippet reads like a plan price, -1 if it reads like an add-on.

    Plan words are matched close to the number; add-on words get a wider window so
    that "best email hosting service ... starting at just $1/month" is not mistaken
    for the entry price of a hosting plan.
    """
    near = context_of(text, start, end, pad=50, pad_after=15)
    wide = context_of(text, start, end, pad=110, pad_after=15)
    return int(any(w in near for w in PLAN_WORDS)) - int(any(w in wide for w in ADDON_WORDS))


def visible_text(raw_html):
    stripped = COMMENT_RE.sub(" ", raw_html)
    stripped = TAG_RE.sub(" ", stripped)
    stripped = ANY_TAG_RE.sub(" ", stripped)
    return re.sub(r"\s+", " ", html.unescape(stripped)).strip()


def clean_title(raw, provider_name, max_len=110):
    title = re.sub(r"\s+", " ", html.unescape(raw or "")).strip()
    for sep in ("|", "–", "—", "-", "·"):
        pat = re.compile(r"\s*%s\s*%s\s*$" % (re.escape(sep), re.escape(provider_name)), re.I)
        title = pat.sub("", title).strip()
    return title[:max_len].strip()


def meta_description(raw_html):
    m = re.search(
        r"<meta[^>]+name=[\"']description[\"'][^>]+content=[\"'](.*?)[\"']", raw_html, re.I | re.S
    ) or re.search(
        r"<meta[^>]+content=[\"'](.*?)[\"'][^>]+name=[\"']description[\"']", raw_html, re.I | re.S
    )
    return re.sub(r"\s+", " ", html.unescape(m.group(1))).strip() if m else ""


def h1_text(raw_html):
    m = re.search(r"<h1[^>]*>(.*?)</h1>", raw_html, re.I | re.S)
    if not m:
        return ""
    return re.sub(r"\s+", " ", html.unescape(ANY_TAG_RE.sub(" ", m.group(1)))).strip()


def parse_date(value):
    value = re.sub(r"\s+", " ", value).replace(",", "").strip()
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(value, fmt).date()
        except ValueError:
            continue
    return None


def money(num, sym):
    try:
        return float(num.replace(",", ""))
    except ValueError:
        return None


def extract_offer_from_page(final_url, raw_html, provider, now):
    """Pull one offer out of a public page. Missing fields stay missing."""
    if not re.search(r"<(html|body|title)\b", raw_html[:4000], re.I):
        return None  # not an HTML page (image, binary, redirect to a file)

    text = visible_text(raw_html)
    page_title_m = re.search(r"<title[^>]*>(.*?)</title>", raw_html, re.I | re.S)
    page_title = clean_title(page_title_m.group(1), provider["name"]) if page_title_m else ""
    title = page_title or h1_text(raw_html)
    if not title:
        return None

    offer = {
        "provider": provider["name"],
        "title": title,
        "page_title": page_title,
        "summary": meta_description(raw_html)[:300],
        "offer_url": final_url,
        "source_url": final_url,
        "fetched_at": now,
    }

    # Every monthly price stated on the page. Add-on prices (DNS, CDN, support,
    # migrations...) are dropped by context so the published number is the entry
    # price of an actual plan, then the lowest non-zero one wins.
    # A "$0 /mo" free tier is real but is not what a buyer pays, so it is skipped.
    monthly = []
    for pm in PRICE_RE.finditer(text):
        amount = money(pm.group("num"), pm.group("sym"))
        if amount is None:
            continue
        if not pm.group("unit").lower().startswith(("mo", "month")):
            continue
        monthly.append((amount, pm.group("sym"), plan_score(text, pm.start(), pm.end())))
    if monthly:
        scored = [(c[2], c) for c in monthly]
        best = max(s for s, _ in scored)
        pool = [c for s, c in scored if s == best]
        nonzero = [c for c in pool if c[0] > 0]
        amount, sym, _ = min(nonzero or pool, key=lambda c: c[0])
        offer["price"] = round(amount, 2)
        offer["currency"] = SYMBOL_CURRENCY.get(sym, "USD")
        offer["price_period"] = "month"

    # Only publish a discount when the page ties it to plans/hosting, otherwise a
    # random "50% off [event]" banner would be reported as this provider's deal.
    matches = list(PCT_RE.finditer(text)) + list(SAVE_RE.finditer(text))
    tied = []
    for m in matches:
        ctx = context_of(text, m.start(), m.end(), pad=60, pad_after=30)
        if any(w in ctx for w in ADDON_WORDS):
            continue
        if any(w in ctx for w in PLAN_WORDS):
            tied.append(int(m.group("pct")))
    if tied:
        offer["discount_pct"] = max(tied)

    cm = CODE_RE.search(text)
    if cm:
        code = cm.group("code").strip("-_")
        if re.search(r"\d", code) or code.isupper():
            offer["promo_code"] = code

    dtm = DATE_HINT_RE.search(text)
    if dtm:
        parsed = parse_date(dtm.group("date"))
        if parsed:
            if parsed.isoformat() >= now[:10]:
                offer["valid_until"] = parsed.isoformat()
            else:
                return None  # expired -> do not list it as live

    offer["has_price"] = "price" in offer
    return offer


def sitemap_urls(fetcher, url, keywords, limit, lang="en"):
    """Return candidate page URLs from a sitemap or sitemap index."""
    kws = [k.strip().lower() for k in keywords.split(",") if k.strip()]
    try:
        _, body = fetcher.get(url)
    except Exception as exc:
        fetcher.note("sitemap fetch failed %s (%s)" % (url, exc))
        return []

    locs = re.findall(r"<loc>\s*(?:<!\[CDATA\[)?\s*(.*?)\s*(?:\]\]>)?\s*</loc>", body, re.S)
    locs = [l.strip() for l in locs if l.strip()]

    if "<sitemapindex" in body.lower():
        picked = []
        for child in locs[:12]:
            if any(k in child.lower() for k in kws) or len(picked) < 3:
                picked.extend(sitemap_urls(fetcher, child, keywords, limit, lang))
                if len(picked) >= limit:
                    break
        return picked[:limit]

    hits = []
    for loc in locs:
        low = loc.lower()
        if low.endswith((".xml", ".xml.gz", ".pdf", ".jpg", ".jpeg", ".png", ".webp")):
            continue
        if any(k in low for k in kws):
            hits.append(loc)
    if lang and any("/%s/" % lang in h for h in hits):
        hits = [h for h in hits if "/%s/" % lang in h]
    return hits[:limit]


def api_offers(fetcher, url, provider, landing, now, limit):
    final_url, body = fetcher.get(url)
    payload = json.loads(body)
    items = None
    if isinstance(payload, dict):
        for key in ("plans", "data", "items", "results", "prices"):
            if isinstance(payload.get(key), list):
                items = payload[key]
                break
        if items is None:
            items = next((v for v in payload.values() if isinstance(v, list)), [])
    else:
        items = payload

    out = []
    for item in items or []:
        if not isinstance(item, dict):
            continue
        price = item.get("monthly_cost", item.get("price", item.get("monthly")))
        if price in (None, "", 0):
            continue
        try:
            price = float(price)
        except (TypeError, ValueError):
            continue
        parts = [
            provider["name"],
            str(item.get("type", "")).upper(),
            "%s vCPU" % item.get("vcpu_count", "?"),
            "%sMB RAM" % item.get("ram", "?"),
            "%sGB %s" % (item.get("disk", "?"), item.get("disk_type", "")),
        ]
        out.append(
            {
                "provider": provider["name"],
                "title": " ".join(p for p in parts if p).strip(),
                "page_title": "",
                "summary": "Official plan pricing published by %s." % provider["name"],
                "price": round(price, 2),
                "currency": "USD",
                "price_period": "month",
                "offer_url": landing or provider["homepage"],
                "source_url": final_url,
                "fetched_at": now,
                "has_price": True,
            }
        )
    out.sort(key=lambda o: o["price"])
    return out[:limit]


# --------------------------------------------------------------------------
# Main
# --------------------------------------------------------------------------
def slugify(value):
    value = re.sub(r"[^a-z0-9]+", "-", (value or "").lower()).strip("-")
    return value or "item"


def main():
    cfg = load_config()
    scrape = cfg["scrape"]
    fetcher = Fetcher(
        user_agent=scrape["user_agent"],
        timeout=float(scrape["timeout"]),
        delay=float(scrape["delay"]),
        respect_robots=scrape["respect_robots"].lower() in ("1", "true", "yes"),
    )
    now = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")

    offers = []
    seen = set()
    statuses = []

    for provider in cfg["providers"]:
        entry = provider["entry"]
        kind, target = (entry.split(":", 1) + [""])[:2] if ":" in entry else ("page", entry)
        kind = kind.strip().lower()
        landing = provider.get("landing") or ""
        label = "%s [%s]" % (provider["name"], target)

        try:
            if kind == "api":
                got = api_offers(
                    fetcher, target, provider, landing, now, int(scrape["max_api_items"])
                )
                statuses.append({"provider": provider["name"], "entry": target, "status": "ok", "count": len(got)})
                for o in got:
                    key = (o["provider"], o["title"], o.get("price"))
                    if key not in seen:
                        seen.add(key)
                        offers.append(o)
                continue

            targets = []
            if kind == "sitemap":
                targets = sitemap_urls(
                    fetcher,
                    target,
                    scrape["sitemap_keywords"],
                    int(scrape["max_pages_per_sitemap"]),
                    cfg["site"].get("language", "en"),
                )
            else:
                targets = [target]

            got = 0
            for page_url in targets:
                try:
                    final_url, raw = fetcher.get(page_url)
                except Exception as exc:
                    fetcher.note("skip %s (%s)" % (page_url, exc))
                    statuses.append({"provider": provider["name"], "entry": page_url, "status": "error", "detail": str(exc)[:120]})
                    continue
                offer = extract_offer_from_page(final_url, raw, provider, now)
                if not offer:
                    statuses.append({"provider": provider["name"], "entry": final_url, "status": "empty"})
                    continue
                if not any(k in offer for k in ("price", "discount_pct", "promo_code")):
                    # Page was readable but publishes no quotable number. Listing it
                    # with an invented price is forbidden, so it is not published.
                    statuses.append({"provider": provider["name"], "entry": final_url, "status": "no_price"})
                    continue
                key = (offer["provider"], offer["title"], offer.get("price"))
                if key in seen:
                    continue
                seen.add(key)
                offers.append(offer)
                got += 1
            statuses.append({"provider": provider["name"], "entry": target, "status": "ok" if got else "empty", "count": got})
        except Exception as exc:
            fetcher.note("failed %s (%s)" % (label, exc))
            statuses.append({"provider": provider["name"], "entry": target, "status": "error", "detail": str(exc)[:120]})

    # provider summaries
    providers = []
    names = []
    for p in cfg["providers"]:
        if p["name"] not in names:
            names.append(p["name"])
    for name in names:
        mine = [o for o in offers if o["provider"] == name]
        prices = [o["price"] for o in mine if isinstance(o.get("price"), (int, float))]
        homepage = next(p["homepage"] for p in cfg["providers"] if p["name"] == name)
        affiliate = next((p["affiliate"] for p in cfg["providers"] if p["name"] == name and p["affiliate"]), "")
        providers.append(
            {
                "name": name,
                "slug": slugify(name),
                "homepage": homepage,
                "affiliate": affiliate,
                "offer_count": len(mine),
                "min_price": min(prices) if prices else None,
                "max_price": max(prices) if prices else None,
                "currency": (mine[0].get("currency") if mine else cfg["site"].get("currency", "USD")) or "USD",
            }
        )

    data = {
        "brand": cfg["site"].get("brand", "cloudhostdeals"),
        "niche": cfg["site"].get("niche", ""),
        "locale": cfg["site"].get("locale", "en-US"),
        "language": cfg["site"].get("language", "en"),
        "currency": cfg["site"].get("currency", "USD"),
        "generated_at": now,
        "fields": cfg["fields"],
        "providers": providers,
        "offers": offers,
        "status": statuses,
    }

    os.makedirs(os.path.dirname(OUT_PATH), exist_ok=True)
    with open(OUT_PATH, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=2, sort_keys=False)
        fh.write("\n")

    priced = sum(1 for o in offers if isinstance(o.get("price"), (int, float)))
    print("[scrape] wrote %s offers (%d priced) to %s" % (len(offers), priced, OUT_PATH))
    return 0 if offers else 1


if __name__ == "__main__":
    sys.exit(main())
