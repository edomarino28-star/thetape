#!/usr/bin/env python
"""Build the public static site into site/.

Runs in CI with no secrets: every source is a free public endpoint. Set
SEC_CONTACT to a real email -- SEC asks that automated clients identify
themselves, and will throttle those that don't.
"""
import os
import shutil
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from smartmoney import dashboard
from smartmoney.collect import collect

HERE = os.path.dirname(os.path.abspath(__file__))
SITE = os.path.join(HERE, "site")


def main():
    days = int(os.environ.get("INSIDER_DAYS", 14))
    cdays = int(os.environ.get("CONGRESS_DAYS", 60))
    ptrs = int(os.environ.get("MAX_PTRS", 60))

    data = collect(days=days, max_filings=int(os.environ.get("MAX_FILINGS", 600)),
                   congress_days=cdays, max_ptrs=ptrs)

    os.makedirs(SITE, exist_ok=True)

    # GitHub Pages serves a project repo at https://OWNER.github.io/REPO.
    # Without this, canonical/og:url/sitemap have no absolute address to point at.
    site_url = os.environ.get("SITE_URL", "").rstrip("/")
    dashboard.render(data, path=os.path.join(SITE, "index.html"),
                     standalone=True, site_url=site_url)

    with open(os.path.join(SITE, "robots.txt"), "w", encoding="utf-8") as fh:
        fh.write("User-agent: *\nAllow: /\n")
        if site_url:
            fh.write(f"\nSitemap: {site_url}/sitemap.xml\n")

    if site_url:
        stamp = str(data.get("generated", ""))[:10]
        with open(os.path.join(SITE, "sitemap.xml"), "w", encoding="utf-8") as fh:
            fh.write(
                '<?xml version="1.0" encoding="UTF-8"?>\n'
                '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
                '  <url>\n'
                f'    <loc>{site_url}/</loc>\n'
                f'    <lastmod>{stamp}</lastmod>\n'
                '    <changefreq>daily</changefreq>\n'
                '    <priority>1.0</priority>\n'
                '  </url>\n'
                '</urlset>\n')
        print(f"sitemap -> {site_url}/sitemap.xml")
    else:
        print("SITE_URL unset: skipping sitemap (canonical URLs will be empty)")

    # Anything in static/ is copied to the site root verbatim. Search-engine
    # verification files live here so a rebuild cannot quietly delete them --
    # Google re-checks the file periodically and un-verifies the site if it
    # disappears.
    static_dir = os.path.join(HERE, "static")
    if os.path.isdir(static_dir):
        for name in sorted(os.listdir(static_dir)):
            src = os.path.join(static_dir, name)
            if os.path.isfile(src):
                shutil.copy(src, os.path.join(SITE, name))
                print(f"static -> {name}")

    icon = os.path.join(HERE, "smartmoney", "the-tape.ico")
    if os.path.exists(icon):
        shutil.copy(icon, os.path.join(SITE, "favicon.ico"))

    print(f"site built -> {SITE}")


if __name__ == "__main__":
    main()
