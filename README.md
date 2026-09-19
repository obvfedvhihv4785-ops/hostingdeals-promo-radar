# hostingdeals.promo-radar

A self-updating, niche site for **cloud hosting and VPS deals**. Every number on
the site is read automatically from each provider's own public pricing or
promo page; nothing is invented.

- **Live site:** <https://cloudhostdeals.com/> (also reachable at
  <https://hostingdeals-promo-radar.pages.dev/>, the original Pages subdomain)
- **Source pipeline:** `scraper.py` + `build.py`, both pure Python standard library
- **Refresh schedule:** every 6 hours via GitHub Actions
- **Hosting:** Cloudflare Pages (free tier), domain registered 2026-09-19
- **Monetisation:** outbound affiliate links to provider sites (see `MONETIZE`)

## What this repository contains

```
.ilang/site.ilang     # The site's rules, single source of truth
templates/            # HTML shells (base, index, compare, provider, deal)
scraper.py            # Reads public provider pages and writes data/offers.json
build.py              # Renders site/ from data/offers.json + .ilang/site.ilang
data/offers.json      # Latest snapshot read from the providers
.github/workflows/update.yml
                      # Cron refresh + commit + optional deploy
AGENTS.md             # Standing instructions for any AI working on this repo
```

## How to add a provider

Open `.ilang/site.ilang` and append a line to the `PROVIDERS` module:

```
SomeCloud | https://somecloud.com | page:https://somecloud.com/pricing/ |  |
```

Then re-run `python scraper.py && python build.py`. The site updates and the
next GitHub Actions run does the same automatically.

## How to bind a custom domain

1. Register the domain (the longer it lives, the more domain age this asset
   accumulates, which is the whole point).
2. In the Cloudflare Pages project, add the custom domain - and add `www.<domain>`
   too, otherwise a `www` CNAME alone returns an error page.
3. Check the domain's status in the Pages dashboard. If it says
   `CNAME record not set`, Cloudflare did **not** create the record for you
   (this happens when your API token or role lacks zone DNS write). Add it by
   hand: `CNAME @ -> <project>.pages.dev`, proxy on, plus the same for `www`.
4. **Only once the domain actually resolves**, change `domain:` in
   `.ilang/site.ilang` to the new host (and the self-referencing URL inside
   `user_agent:`). Pointing canonicals at a host that does not resolve yet is
   worse than leaving the old one in place.
5. Re-run the build (or wait for the next cron tick). All canonical tags,
   the sitemap and the Open Graph image URL update automatically. Verify with
   `grep -rl "pages.dev" site/` - it must return nothing.

## Site rules

The site rules - what to scrape, what to publish, what is forbidden - are
described in plain text with the **I-Lang** protocol: `.ilang/site.ilang`.
This file is read by `scraper.py` and `build.py` at runtime, so changing it
changes the site on the next refresh. The protocol is documented at
<https://ilang.ai>.