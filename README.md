# hostingdeals.promo-radar

A self-updating, niche site for **cloud hosting and VPS deals**. Every number on
the site is read automatically from each provider's own public pricing or
promo page; nothing is invented.

- **Live site:** <https://hostingdeals-promo-radar.pages.dev/>
- **Source pipeline:** `scraper.py` + `build.py`, both pure Python standard library
- **Refresh schedule:** every 6 hours via GitHub Actions
- **Hosting:** Cloudflare Pages (free tier, no custom domain required to start)
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
2. In the Cloudflare Pages project, add the custom domain. Cloudflare
   automatically adds the right DNS records if the zone is already on
   Cloudflare, otherwise follow the instructions it shows.
3. Change `domain:` in `.ilang/site.ilang` to the new host.
4. Re-run the build (or wait for the next cron tick). All canonical tags,
   the sitemap and the Open Graph image URL update automatically.

## Site rules

The site rules - what to scrape, what to publish, what is forbidden - are
described in plain text with the **I-Lang** protocol: `.ilang/site.ilang`.
This file is read by `scraper.py` and `build.py` at runtime, so changing it
changes the site on the next refresh. The protocol is documented at
<https://ilang.ai>.