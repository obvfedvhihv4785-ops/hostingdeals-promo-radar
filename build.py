#!/usr/bin/env python3
# ::ILANG
# [TYPE:module][PROJECT:hostingdeals][LANG:zh]
# ::STATE{@SELF, role:builder, reads:.ilang/site.ilang + data/offers.json, writes:site/}
# ::RULE{品牌 域名 渲染文案只从 .ilang/site.ilang 读 改配置就改站}
# ::RULE{抓不到的价格不写进页面也不写进结构化数据 宁可少一个字段}
# ::BOUNDARY{never:编价格 编折扣 编有效期 编佣金|scope:permanent}

"""Render data/offers.json into a static site in site/.

Standard library only - no jinja, no Pillow, no npm. The Open Graph cards are
drawn by a tiny bitmap font and a hand-rolled PNG writer.
"""

import html
import json
import os
import re
import shutil
import struct
import zlib
from datetime import datetime, timezone
from string import Template

from scraper import load_config

ROOT = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(ROOT, "data", "offers.json")
TPL = os.path.join(ROOT, "templates")
OUT = os.path.join(ROOT, "site")

# ---------------------------------------------------------------------------
# 5x7 bitmap font, just enough for the OG cards (letters, digits, punctuation)
# ---------------------------------------------------------------------------
FONT = {
    "A": ("01110", "10001", "10001", "11111", "10001", "10001", "10001"),
    "B": ("11110", "10001", "10001", "11110", "10001", "10001", "11110"),
    "C": ("01110", "10001", "10000", "10000", "10000", "10001", "01110"),
    "D": ("11110", "10001", "10001", "10001", "10001", "10001", "11110"),
    "E": ("11111", "10000", "10000", "11110", "10000", "10000", "11111"),
    "F": ("11111", "10000", "10000", "11110", "10000", "10000", "10000"),
    "G": ("01110", "10001", "10000", "10111", "10001", "10001", "01110"),
    "H": ("10001", "10001", "10001", "11111", "10001", "10001", "10001"),
    "I": ("11111", "00100", "00100", "00100", "00100", "00100", "11111"),
    "J": ("00111", "00010", "00010", "00010", "00010", "10010", "01100"),
    "K": ("10001", "10010", "10100", "11000", "10100", "10010", "10001"),
    "L": ("10000", "10000", "10000", "10000", "10000", "10000", "11111"),
    "M": ("10001", "11011", "10101", "10101", "10001", "10001", "10001"),
    "N": ("10001", "11001", "10101", "10011", "10001", "10001", "10001"),
    "O": ("01110", "10001", "10001", "10001", "10001", "10001", "01110"),
    "P": ("11110", "10001", "10001", "11110", "10000", "10000", "10000"),
    "Q": ("01110", "10001", "10001", "10001", "10101", "10011", "01101"),
    "R": ("11110", "10001", "10001", "11110", "10100", "10010", "10001"),
    "S": ("01111", "10000", "10000", "01110", "00001", "00001", "11110"),
    "T": ("11111", "00100", "00100", "00100", "00100", "00100", "00100"),
    "U": ("10001", "10001", "10001", "10001", "10001", "10001", "01110"),
    "V": ("10001", "10001", "10001", "10001", "10001", "01010", "00100"),
    "W": ("10001", "10001", "10001", "10101", "10101", "11011", "10001"),
    "X": ("10001", "10001", "01010", "00100", "01010", "10001", "10001"),
    "Y": ("10001", "10001", "01010", "00100", "00100", "00100", "00100"),
    "Z": ("11111", "00001", "00010", "00100", "01000", "10000", "11111"),
    "0": ("01110", "10001", "10011", "10101", "11001", "10001", "01110"),
    "1": ("00100", "01100", "00100", "00100", "00100", "00100", "01110"),
    "2": ("01110", "10001", "00001", "00010", "00100", "01000", "11111"),
    "3": ("11110", "00001", "00001", "01110", "00001", "00001", "11110"),
    "4": ("00010", "00110", "01010", "10010", "11111", "00010", "00010"),
    "5": ("11111", "10000", "10000", "11110", "00001", "00001", "11110"),
    "6": ("00110", "01000", "10000", "11110", "10001", "10001", "01110"),
    "7": ("11111", "00001", "00010", "00100", "01000", "01000", "01000"),
    "8": ("01110", "10001", "10001", "01110", "10001", "10001", "01110"),
    "9": ("01110", "10001", "10001", "01111", "00001", "00010", "01100"),
    " ": ("00000", "00000", "00000", "00000", "00000", "00000", "00000"),
    ".": ("00000", "00000", "00000", "00000", "00000", "01100", "01100"),
    ",": ("00000", "00000", "00000", "00000", "01100", "01100", "00100"),
    "/": ("00001", "00010", "00010", "00100", "01000", "01000", "10000"),
    "-": ("00000", "00000", "00000", "11111", "00000", "00000", "00000"),
    "%": ("10001", "10010", "00100", "00100", "00100", "01001", "10001"),
    "$": ("00100", "01111", "10100", "01110", "00101", "11110", "00100"),
    ":": ("00000", "01100", "01100", "00000", "01100", "01100", "00000"),
    "(": ("00010", "00100", "01000", "01000", "01000", "00100", "00010"),
    ")": ("01000", "00100", "00010", "00010", "00010", "00100", "01000"),
    "&": ("01100", "10010", "10100", "01000", "10101", "10010", "01101"),
    "!": ("00100", "00100", "00100", "00100", "00100", "00000", "00100"),
    "'": ("00100", "00100", "00000", "00000", "00000", "00000", "00000"),
    "+": ("00000", "00100", "00100", "11111", "00100", "00100", "00000"),
    "?": ("01110", "10001", "00001", "00110", "00100", "00000", "00100"),
}
TRANSLIT = "—–−|".join([""] * 0) or {}
for _ch in "—–−|":
    TRANSLIT[_ch] = "-"
for _ch in "‘’":
    TRANSLIT[_ch] = "'"
for _ch in "“”":
    TRANSLIT[_ch] = '"'


def _og_text(value):
    out = []
    for ch in (value or "").upper():
        out.append(TRANSLIT.get(ch, ch))
    return "".join(out)


def _text_width(text, scale):
    return len(text) * 6 * scale


def _fill(pix, w, h, x0, y0, cw, ch, color):
    for y in range(max(0, y0), min(h, y0 + ch)):
        base = y * w * 3
        for x in range(max(0, x0), min(w, x0 + cw)):
            i = base + x * 3
            pix[i] = color[0]
            pix[i + 1] = color[1]
            pix[i + 2] = color[2]


def _draw(pix, w, h, text, x, y, scale, color):
    for ch in text:
        rows = FONT.get(ch)
        if rows is None:
            x += 6 * scale
            continue
        for r, row in enumerate(rows):
            for c, bit in enumerate(row):
                if bit == "1":
                    _fill(pix, w, h, x + c * scale, y + r * scale, scale, scale, color)
        x += 6 * scale


def _wrap(text, max_w, scale):
    lines, cur = [], ""
    for word in (text or "").split():
        trial = (cur + " " + word).strip()
        if _text_width(trial, scale) > max_w and cur:
            lines.append(cur)
            cur = word
        else:
            cur = trial
    if cur:
        lines.append(cur)
    return lines


def _hex_rgb(value, fallback=(16, 24, 40)):
    m = re.fullmatch(r"#?([0-9a-fA-F]{6})", (value or "").strip())
    if not m:
        return fallback
    raw = m.group(1)
    return tuple(int(raw[i : i + 2], 16) for i in (0, 2, 4))


def _write_png(path, width, height, pix):
    raw = bytearray()
    stride = width * 3
    for y in range(height):
        raw.append(0)
        raw += pix[y * stride : (y + 1) * stride]

    def chunk(tag, data):
        body = tag + data
        return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF)

    blob = b"\x89PNG\r\n\x1a\n"
    blob += chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
    blob += chunk(b"IDAT", zlib.compress(bytes(raw), 9))
    blob += chunk(b"IEND", b"")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as fh:
        fh.write(blob)


def make_og_card(path, cfg, brand, headline, price_text, domain):
    """Draw a 1200x630 social card. No fonts, no image library."""
    w, h = 1200, 630
    bg = _hex_rgb(cfg.get("og_bg"), (246, 248, 252))
    accent = _hex_rgb(cfg.get("og_accent"), (11, 95, 255))
    text_c = _hex_rgb(cfg.get("og_text"), (16, 24, 40))
    muted = (110, 118, 133)
    white = (255, 255, 255)
    pix = bytearray(bg * (w * h))

    _fill(pix, w, h, 0, 0, w, 160, accent)
    _draw(pix, w, h, _og_text(brand), 64, 56, 7, white)

    y = 240
    for line in _wrap(_og_text(headline), w - 128, 8)[:2]:
        _draw(pix, w, h, line, 64, y, 8, text_c)
        y += 8 * 7 + 26

    if price_text:
        _draw(pix, w, h, _og_text(price_text), 64, 450, 11, accent)
    _draw(pix, w, h, _og_text(domain), 64, 570, 4, muted)
    _write_png(path, w, h, pix)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------
def slugify(value):
    value = re.sub(r"[^a-z0-9]+", "-", (value or "").lower()).strip("-")
    return value or "item"


def esc(value):
    return html.escape(str(value if value is not None else ""), quote=True)


def money_text(offer):
    if not isinstance(offer.get("price"), (int, float)):
        return None
    sym = {"USD": "$", "EUR": "€", "GBP": "£"}.get(offer.get("currency"), "$")
    amount = offer["price"]
    shown = ("%g" % amount) if amount == int(amount) else ("%.2f" % amount)
    period = "mo" if offer.get("price_period", "month") == "month" else "yr"
    return "%s%s / %s" % (sym, shown, period)


def score_key(offer):
    return (-int(offer.get("discount_pct") or 0), offer.get("price") if isinstance(offer.get("price"), (int, float)) else 9e9)


def jsonld(obj):
    return '<script type="application/ld+json">%s</script>' % json.dumps(
        obj, ensure_ascii=False, separators=(",", ":")
    )


# ---------------------------------------------------------------------------
# main build
# ---------------------------------------------------------------------------
def main():
    cfg = load_config()
    site = cfg["site"]
    render = cfg["render"]
    with open(DATA, "r", encoding="utf-8") as fh:
        data = json.load(fh)

    brand = site.get("brand", "cloudhostdeals")
    domain = site.get("domain", "example.com").strip().rstrip("/")
    base = "https://" + domain.replace("https://", "").replace("http://", "")
    lang = site.get("language", "en")
    niche = site.get("niche", "")
    generated = data.get("generated_at") or datetime.now(timezone.utc).isoformat()
    updated_short = generated[:16].replace("T", " ")

    def url(path):
        return base + path

    offers = [o for o in data.get("offers", []) if any(o.get(k) for k in ("price", "discount_pct", "promo_code"))]
    offers.sort(key=score_key)
    providers = data.get("providers", [])
    live = [p for p in providers if p.get("offer_count")]
    status_rows = data.get("status", [])

    for idx, o in enumerate(offers):
        o["slug"] = slugify(o.get("title", ""))[:50].strip("-") + "-" + slugify(o.get("source_url", ""))[-8:]
        o["price_text"] = money_text(o)
        o["rank"] = idx + 1

    if os.path.isdir(OUT):
        shutil.rmtree(OUT)
    for sub in ("providers", "deals", "assets/og"):
        os.makedirs(os.path.join(OUT, sub), exist_ok=True)

    def read_tpl(name):
        with open(os.path.join(TPL, name), "r", encoding="utf-8") as fh:
            return fh.read()

    base_tpl = Template(read_tpl("base.html"))

    def page(title, description, path, content, jsonld_obj=None, og_name=None, og_head=None, og_price=None):
        canonical = url(path)
        og_path = "/assets/og/%s.png" % (og_name or "home")
        make_og_card(
            os.path.join(OUT, "assets", "og", (og_name or "home") + ".png"),
            render,
            brand,
            og_head or title,
            og_price or "",
            domain,
        )
        out = base_tpl.safe_substitute(
            lang=lang,
            brand=esc(brand),
            title=esc(title[:110]),
            description=esc(description[:155]),
            canonical=esc(canonical),
            xdefault=esc(url("/")),
            og_image=esc(url(og_path)),
            jsonld=jsonld(jsonld_obj) if jsonld_obj else "",
            content=content,
            niche=esc(niche),
            footer_note=esc(render.get("footer_note", "")),
            generated_at=esc(generated),
            initial=esc(brand[:1].upper()),
            repo_line=(
                'Source and refresh pipeline: <a href="https://github.com/%s" rel="noopener">github.com/%s</a>.'
                % (esc(site.get("repo", "")), esc(site.get("repo", "")))
            )
            if site.get("repo")
            else "",
        )
        with open(os.path.join(OUT, path.strip("/") + ".html" if path != "/" else "index.html"), "w", encoding="utf-8") as fh:
            fh.write(out)

    # ---------- deal cards ----------
    def deal_card(o):
        tags = []
        if o.get("discount_pct"):
            tags.append('<span class="tag">%d%% off</span>' % int(o["discount_pct"]))
        if o.get("promo_code"):
            tags.append('<span class="tag">Code %s</span>' % esc(o["promo_code"]))
        if not o.get("price_text"):
            tags.append('<span class="tag grey">Price not published in page source</span>')
        if o.get("valid_until"):
            tags.append('<span class="tag grey">Until %s</span>' % esc(o["valid_until"]))
        price = (
            '<div class="price">%s <small>%s</small></div>' % (esc(o["price_text"].split(" / ")[0]), esc("per " + o["price_text"].split(" / ")[1]))
            if o.get("price_text")
            else '<div class="price"><small>see provider page</small></div>'
        )
        link = o.get("affiliate") or o.get("offer_url")
        rel = "sponsored noopener" if o.get("affiliate") else "noopener nofollow"
        return (
            '<article class="card">'
            '<div class="prov">%s</div>'
            "<h3>%s</h3>"
            "%s"
            '<div class="kv">%s</div>'
            '<a class="cta" href="%s" rel="%s" target="_blank">View offer</a>'
            '<a class="src" href="%s">Source: %s</a>'
            "</article>"
        ) % (
            esc(o["provider"]),
            '<a href="%s">%s</a>' % (esc(url("/deals/" + o["slug"])), esc(o.get("title", "")[:90])),
            price,
            "".join(tags),
            esc(link),
            rel,
            esc(o.get("source_url", "")),
            esc(o.get("source_url", "")),
        )

    # ---------- index ----------
    faq_items = [
        (
            "Where do these prices come from?",
            "An automated job reads each provider's own public pricing or promo page every six hours and "
            "copies what that page states. Every listing links back to the page it came from.",
        ),
        (
            "Why is a provider missing a price?",
            "Some providers render prices with JavaScript or block automated readers. When this site cannot "
            "read a number it leaves the field empty instead of estimating one.",
        ),
        (
            "How often is this page updated?",
            "Every six hours, and the timestamp at the bottom of the page shows the last successful read.",
        ),
        (
            "Do you sell these plans?",
            "No. This site lists offers and links to the provider. Some links may be affiliate links, which "
            "means a commission may be earned at no extra cost to you.",
        ),
    ]
    faq_html = "".join(
        "<details><summary>%s</summary><p>%s</p></details>" % (esc(q), esc(a)) for q, a in faq_items
    )
    faq_ld = {
        "@context": "https://schema.org",
        "@type": "FAQPage",
        "mainEntity": [
            {"@type": "Question", "name": q, "acceptedAnswer": {"@type": "Answer", "text": a}}
            for q, a in faq_items
        ],
    }

    index_content = Template(read_tpl("index.html")).safe_substitute(
        hero_title=esc(render.get("hero_title", "Hosting and VPS deals")),
        hero_subtitle=esc(render.get("hero_subtitle", "")),
        offer_count=len(offers),
        provider_count=len(live),
        updated_short=esc(updated_short),
        deal_cards="".join(deal_card(o) for o in offers[: int(render.get("per_page", 12)) * 3]) or "<p>No offers readable right now.</p>",
        provider_cards="".join(
            '<article class="card"><div class="prov">%s</div><h3><a href="%s">%s deals</a></h3>'
            '<div class="kv"><span class="badge">%d listings</span>%s</div>'
            '<a class="src" href="%s" rel="noopener nofollow" target="_blank">%s</a></article>'
            % (
                esc(p["name"]),
                esc(url("/providers/" + p["slug"])),
                esc(p["name"]),
                p["offer_count"],
                ('<span class="badge">from %s</span>' % esc(p["min_price"])) if p.get("min_price") is not None else "",
                esc(p.get("homepage", "")),
                esc(p.get("homepage", "")),
            )
            for p in live
        ),
        coverage_table=coverage_table(status_rows),
        faq=faq_html,
    )
    page(
        "%s — %s (%s)" % (brand, niche, updated_short[:10]),
        "%s: %d live offers from %d providers, read from their own public pricing pages and refreshed every six hours."
        % (brand, len(offers), len(live)),
        "/",
        index_content,
        [
            {
                "@context": "https://schema.org",
                "@type": "WebSite",
                "name": brand,
                "url": url("/"),
            },
            {
                "@context": "https://schema.org",
                "@type": "ItemList",
                "name": "Latest hosting and VPS offers",
                "itemListElement": [
                    {"@type": "ListItem", "position": i + 1, "url": url("/deals/" + o["slug"]), "name": o.get("title", "")}
                    for i, o in enumerate(offers[:20])
                ],
            },
            faq_ld,
        ],
        og_name="home",
        og_head="Hosting and VPS deals",
        og_price="%d live offers" % len(offers),
    )

    # ---------- compare ----------
    compare_rows = []
    for p in sorted(live, key=lambda p: (p.get("min_price") is None, p.get("min_price") or 0)):
        pcts = [o.get("discount_pct") for o in offers if o["provider"] == p["name"] and o.get("discount_pct")]
        compare_rows.append(
            "<tr><td><strong>%s</strong><br><a class=\"src\" href=\"%s\" rel=\"noopener nofollow\" target=\"_blank\">%s</a></td>"
            "<td>%s</td><td>%s</td><td>%s</td><td><a href=\"%s\">Details</a></td></tr>"
            % (
                esc(p["name"]),
                esc(p.get("homepage", "")),
                esc(p.get("homepage", "")),
                esc(("%g %s / mo" % (p["min_price"], p.get("currency", "USD"))) if p.get("min_price") is not None else "not published"),
                esc(("%g %s / mo" % (p["max_price"], p.get("currency", "USD"))) if p.get("max_price") is not None else "-"),
                esc(("%d%% off" % max(pcts)) if pcts else "-"),
                esc(url("/providers/" + p["slug"])),
            )
        )
    compare_content = Template(read_tpl("compare.html")).safe_substitute(
        updated_short=esc(updated_short),
        provider_count=len(live),
        compare_table=(
            "<table><thead><tr><th>Provider</th><th>Lowest</th><th>Highest</th><th>Best discount</th><th></th></tr></thead><tbody>"
            + "".join(compare_rows)
            + "</tbody></table>"
        ),
        faq=faq_html,
        coverage_table=coverage_table(status_rows),
    )
    page(
        "Compare cloud hosting and VPS providers — %s" % brand,
        "Side-by-side entry prices and discounts for %d hosting providers, read from their own public pricing pages." % len(live),
        "/compare",
        compare_content,
        {
            "@context": "https://schema.org",
            "@type": "ItemList",
            "name": "Hosting providers compared",
            "itemListElement": [
                {"@type": "ListItem", "position": i + 1, "url": url("/providers/" + p["slug"]), "name": p["name"]}
                for i, p in enumerate(live)
            ],
        },
        og_name="compare",
        og_head="Compare hosting providers",
        og_price="%d providers" % len(live),
    )

    # ---------- provider pages ----------
    for p in live:
        mine = sorted([o for o in offers if o["provider"] == p["name"]], key=score_key)
        prices = [o["price"] for o in mine if isinstance(o.get("price"), (int, float))]
        cur = p.get("currency", "USD")
        price_range = (
            '<span class="badge">from %g %s / mo</span>' % (min(prices), cur) if prices else '<span class="badge">price not published</span>'
        )
        aggregate = []
        if prices:
            aggregate.append(
                {
                    "@context": "https://schema.org",
                    "@type": "Service",
                    "name": "%s cloud hosting" % p["name"],
                    "provider": {"@type": "Organization", "name": p["name"], "url": p.get("homepage", "")},
                    "offers": {
                        "@type": "AggregateOffer",
                        "priceCurrency": cur,
                        "lowPrice": min(prices),
                        "highPrice": max(prices),
                        "offerCount": len(prices),
                        "offers": [
                            {
                                "@type": "Offer",
                                "name": o.get("title", ""),
                                "url": o.get("offer_url", ""),
                                "price": o["price"],
                                "priceCurrency": o.get("currency", cur),
                                "availability": "https://schema.org/InStock",
                                **({"priceValidUntil": o["valid_until"]} if o.get("valid_until") else {}),
                            }
                            for o in mine
                            if isinstance(o.get("price"), (int, float))
                        ],
                    },
                }
            )
        aggregate.append(
            {
                "@context": "https://schema.org",
                "@type": "BreadcrumbList",
                "itemListElement": [
                    {"@type": "ListItem", "position": 1, "name": "Home", "item": url("/")},
                    {"@type": "ListItem", "position": 2, "name": "Compare", "item": url("/compare")},
                    {"@type": "ListItem", "position": 3, "name": p["name"], "item": url("/providers/" + p["slug"])},
                ],
            }
        )
        content = Template(read_tpl("provider.html")).safe_substitute(
            provider=esc(p["name"]),
            summary=esc(
                "%s publishes %d offer%s on the pages this site reads. Figures below are copied from those pages, "
                "with the lowest monthly price we could verify."
                % (p["name"], len(mine), "" if len(mine) == 1 else "s")
            ),
            offer_count=len(mine),
            price_range=price_range,
            updated_short=esc(updated_short),
            homepage=esc(p.get("homepage", "")),
            deal_cards="".join(deal_card(o) for o in mine),
            source_list="<br>".join(
                '<a href="%s" rel="noopener nofollow" target="_blank">%s</a>' % (esc(o.get("source_url", "")), esc(o.get("source_url", "")))
                for o in mine
            ),
        )
        page(
            "%s deals and pricing — %s" % (p["name"], brand),
            "%s: %d offers read from the provider's own public pages, lowest verified price %s."
            % (p["name"], len(mine), ("%g %s/mo" % (min(prices), cur)) if prices else "not published"),
            "/providers/" + p["slug"],
            content,
            aggregate,
            og_name="provider-" + p["slug"],
            og_head=p["name"],
            og_price=("%g %s / month" % (min(prices), cur)) if prices else "",
        )

    # ---------- deal pages ----------
    for o in offers:
        provider_slug = slugify(o["provider"])
        facts = [
            ("Provider", esc(o["provider"])),
            ("Listing", esc(o.get("title", ""))),
            ("Price", esc(o["price_text"]) if o.get("price_text") else "not stated on the source page"),
            ("Discount", ("%d%%" % int(o["discount_pct"])) if o.get("discount_pct") else "not stated on the source page"),
            ("Promo code", esc(o["promo_code"]) if o.get("promo_code") else "not stated on the source page"),
            ("Valid until", esc(o["valid_until"]) if o.get("valid_until") else "not stated on the source page"),
            ("Read at", esc(o.get("fetched_at", ""))),
        ]
        facts_html = "".join("<tr><th>%s</th><td>%s</td></tr>" % (esc(k), v) for k, v in facts)
        deal_faq = "".join(
            "<details><summary>%s</summary><p>%s</p></details>" % (esc(q), esc(a))
            for q, a in [
                ("Is this price guaranteed?", "No. The provider can change prices or end a promotion at any time. The number above is what the provider's page stated when this site last read it."),
                ("How do I use it?", "Open the offer on the provider's page. If a promo code is listed, the provider page is where it is applied at checkout."),
                ("Why is some data missing?", "This site only publishes fields that appear on the provider's own page. Anything absent was not stated there."),
            ]
        )
        content = Template(read_tpl("deal.html")).safe_substitute(
            provider=esc(o["provider"]),
            provider_url=esc(url("/providers/" + provider_slug)),
            title=esc(o.get("title", "")),
            price_block=('<div class="price">%s</div>' % esc(o["price_text"])) if o.get("price_text") else '<div class="price"><small>price not published in page source</small></div>',
            tags="".join(
                [
                    ('<span class="tag">%d%% off</span>' % int(o["discount_pct"])) if o.get("discount_pct") else "",
                    ('<span class="tag">Code %s</span>' % esc(o["promo_code"])) if o.get("promo_code") else "",
                    ('<span class="tag grey">Until %s</span>' % esc(o["valid_until"])) if o.get("valid_until") else "",
                    '<span class="tag grey">Verified %s</span>' % esc((o.get("fetched_at") or "")[:10]),
                ]
            ),
            fetched_short=esc((o.get("fetched_at") or "")[:16].replace("T", " ")),
            fetched_at=esc(o.get("fetched_at", "")),
            offer_url=esc(o.get("offer_url", "")),
            source_url=esc(o.get("source_url", "")),
            facts=facts_html,
            faq=deal_faq,
        )
        offer_ld = {
            "@context": "https://schema.org",
            "@type": "Product",
            "name": o.get("title", ""),
            "brand": {"@type": "Organization", "name": o["provider"]},
            "offers": {
                "@type": "Offer",
                "url": o.get("offer_url", ""),
                "availability": "https://schema.org/InStock",
                **({"price": o["price"], "priceCurrency": o.get("currency", "USD")} if isinstance(o.get("price"), (int, float)) else {}),
                **({"priceValidUntil": o["valid_until"]} if o.get("valid_until") else {}),
            },
        }
        breadcrumb_ld = {
            "@context": "https://schema.org",
            "@type": "BreadcrumbList",
            "itemListElement": [
                {"@type": "ListItem", "position": 1, "name": "Home", "item": url("/")},
                {"@type": "ListItem", "position": 2, "name": o["provider"], "item": url("/providers/" + provider_slug)},
                {"@type": "ListItem", "position": 3, "name": o.get("title", "")[:80], "item": url("/deals/" + o["slug"])},
            ],
        }
        page(
            "%s — %s | %s" % (o["provider"], o.get("title", "")[:70], brand),
            "%s: %s. Read from the provider's own page on %s."
            % (
                o["provider"],
                (o.get("price_text") or "price not published"),
                (o.get("fetched_at") or "")[:10],
            ),
            "/deals/" + o["slug"],
            content,
            [offer_ld, breadcrumb_ld],
            og_name="deal-" + o["slug"],
            og_head=o.get("title", ""),
            og_price=o.get("price_text") or "",
        )

    # ---------- about / privacy / contact ----------
    # The contact address is published only once it can actually receive mail. If
    # .ilang/site.ilang leaves contact_email empty, the pages say so in plain words
    # instead of printing an address that bounces.
    contact_email = (render.get("contact_email") or "").strip()
    contact_live = bool(re.fullmatch(r"[^@\s]+@[^@\s.]+(?:\.[^@\s.]+)+", contact_email))
    policy_updated = esc(render.get("policy_updated", ""))

    if contact_live:
        contact_block = (
            "<p>The address for anything to do with this site is "
            '<a href="mailto:%s">%s</a>. It is a forwarding address on this domain rather than a '
            "mailbox on a third-party service, and mail sent to it reaches the person who runs this "
            "site.</p>" % (esc(contact_email), esc(contact_email))
        )
        contact_block_hero = '<p class="lead">Write to <a href="mailto:%s">%s</a>.</p>' % (
            esc(contact_email),
            esc(contact_email),
        )
    else:
        contact_block = (
            "<p>This site has no working contact address yet, so there is currently no way to write "
            "to it. An address will be published here once it can actually receive mail. Until then "
            "nothing on this site claims one exists.</p>"
        )
        contact_block_hero = (
            '<p class="lead">No contact address is open yet. The address for this site is still '
            "being set up, and it is deliberately not published until it can receive mail.</p>"
        )

    tracked_names = [p.get("name", "") for p in providers if p.get("name")]
    if len(tracked_names) > 1:
        provider_names = ", ".join(tracked_names[:-1]) + " and " + tracked_names[-1]
    else:
        provider_names = tracked_names[0] if tracked_names else "no providers yet"

    about_content = Template(read_tpl("about.html")).safe_substitute(
        provider_count=len(tracked_names),
        offer_count=len(offers),
        updated_short=esc(updated_short),
        provider_names=esc(provider_names),
    )
    page(
        "About cloudhostdeals — who runs this site and where the numbers come from",
        "cloudhostdeals is an independent tracker for cloud hosting and VPS prices. This page covers who "
        "runs it, where every figure comes from, how often it refreshes, and what it refuses to do.",
        "/about",
        about_content,
        [
            {
                "@context": "https://schema.org",
                "@type": "AboutPage",
                "name": "About cloudhostdeals",
                "url": url("/about"),
            },
            {
                "@context": "https://schema.org",
                "@type": "BreadcrumbList",
                "itemListElement": [
                    {"@type": "ListItem", "position": 1, "name": "Home", "item": url("/")},
                    {"@type": "ListItem", "position": 2, "name": "About", "item": url("/about")},
                ],
            },
        ],
        og_name="about",
        og_head="About cloudhostdeals",
        og_price="%d providers tracked" % len(tracked_names),
    )

    privacy_content = Template(read_tpl("privacy.html")).safe_substitute(
        policy_updated=policy_updated,
        contact_block=contact_block,
    )
    page(
        "Privacy policy — cloudhostdeals",
        "What cloudhostdeals does and does not collect: no accounts, no cookies of its own, no analytics "
        "and no sale of visitor data — plus exactly what will change when third-party ads are added.",
        "/privacy",
        privacy_content,
        [
            {
                "@context": "https://schema.org",
                "@type": "WebPage",
                "name": "Privacy policy",
                "url": url("/privacy"),
            },
            {
                "@context": "https://schema.org",
                "@type": "BreadcrumbList",
                "itemListElement": [
                    {"@type": "ListItem", "position": 1, "name": "Home", "item": url("/")},
                    {"@type": "ListItem", "position": 2, "name": "Privacy", "item": url("/privacy")},
                ],
            },
        ],
        og_name="privacy",
        og_head="Privacy policy",
        og_price="",
    )

    contact_content = Template(read_tpl("contact.html")).safe_substitute(
        contact_block_hero=contact_block_hero,
    )
    page(
        "Contact cloudhostdeals — corrections, removals and questions",
        "How to reach cloudhostdeals about a price that looks wrong, a page that will not load, a provider "
        "to add, or a request about your data.",
        "/contact",
        contact_content,
        [
            {
                "@context": "https://schema.org",
                "@type": "ContactPage",
                "name": "Contact cloudhostdeals",
                "url": url("/contact"),
            },
            {
                "@context": "https://schema.org",
                "@type": "BreadcrumbList",
                "itemListElement": [
                    {"@type": "ListItem", "position": 1, "name": "Home", "item": url("/")},
                    {"@type": "ListItem", "position": 2, "name": "Contact", "item": url("/contact")},
                ],
            },
        ],
        og_name="contact",
        og_head="Contact cloudhostdeals",
        og_price="",
    )

    # ---------- 404 ----------
    with open(os.path.join(OUT, "404.html"), "w", encoding="utf-8") as fh:
        fh.write(
            "<!DOCTYPE html><html lang=\"%s\"><head><meta charset=\"utf-8\">"
            "<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">"
            "<meta name=\"robots\" content=\"noindex, follow\">"
            "<title>Page not found — %s</title>"
            "<style>body{font:16px/1.6 -apple-system,Segoe UI,Roboto,sans-serif;background:#f6f8fc;color:#101828;"
            "margin:0;display:grid;place-items:center;min-height:100vh;text-align:center;padding:24px}"
            "a{color:#0b5fff}</style></head><body><div><h1>Page not found</h1>"
            "<p>That listing may have expired or changed name.</p><p><a href=\"/\">Back to current deals</a></p>"
            "</div></body></html>" % (esc(lang), esc(brand))
        )

    # ---------- sitemap + robots ----------
    urls = (
        ["/", "/compare", "/about", "/privacy", "/contact"]
        + ["/providers/" + p["slug"] for p in live]
        + ["/deals/" + o["slug"] for o in offers]
    )
    sitemap = ['<?xml version="1.0" encoding="UTF-8"?>', '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">']
    for u in urls:
        sitemap.append(
            "  <url><loc>%s</loc><lastmod>%s</lastmod></url>"
            % (html.escape(url(u), quote=False), html.escape(generated[:19] + "Z" if not generated.endswith("Z") else generated))
        )
    sitemap.append("</urlset>")
    with open(os.path.join(OUT, "sitemap.xml"), "w", encoding="utf-8") as fh:
        fh.write("\n".join(sitemap) + "\n")
    with open(os.path.join(OUT, "robots.txt"), "w", encoding="utf-8") as fh:
        fh.write("User-agent: *\nAllow: /\n\nSitemap: %s/sitemap.xml\n" % base)

    print("[build] site/ written: %d offers, %d provider pages, %d urls" % (len(offers), len(live), len(urls)))


def coverage_table(status_rows):
    label = {
        "ok": "read",
        "empty": "page read, nothing usable found",
        "no_price": "page read, no price published in the HTML - not listed",
    }
    rows = []
    for s in status_rows:
        st = s.get("status")
        detail = s.get("detail", "")
        if st == "error":
            if "robots" in detail:
                text = "blocked by the provider's robots.txt - not fetched"
            else:
                text = "blocked by the provider (%s)" % (detail or "error")
        else:
            text = label.get(st, st)
        rows.append(
            "<tr><td>%s</td><td class=\"src\">%s</td><td>%s</td></tr>"
            % (esc(s.get("provider", "")), esc(s.get("entry", "")), esc(text))
        )
    return (
        "<table><thead><tr><th>Provider</th><th>Source we read</th><th>Status</th></tr></thead><tbody>"
        + "".join(rows)
        + "</tbody></table>"
    )


if __name__ == "__main__":
    main()
