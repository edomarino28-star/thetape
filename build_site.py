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

SITE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "site")


def main():
    days = int(os.environ.get("INSIDER_DAYS", 14))
    cdays = int(os.environ.get("CONGRESS_DAYS", 60))
    ptrs = int(os.environ.get("MAX_PTRS", 60))

    data = collect(days=days, max_filings=int(os.environ.get("MAX_FILINGS", 600)),
                   congress_days=cdays, max_ptrs=ptrs)

    os.makedirs(SITE, exist_ok=True)
    dashboard.render(data, path=os.path.join(SITE, "index.html"), standalone=True)

    # tell crawlers not to index a page of raw filing data
    with open(os.path.join(SITE, "robots.txt"), "w", encoding="utf-8") as fh:
        fh.write("User-agent: *\nAllow: /\n")
    icon = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        "smartmoney", "the-tape.ico")
    if os.path.exists(icon):
        shutil.copy(icon, os.path.join(SITE, "favicon.ico"))
    print(f"site built -> {SITE}")


if __name__ == "__main__":
    main()
