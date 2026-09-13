"""Short positions -- the one thing a 13F can never show you.

Form 13F covers LONG US equity positions only. Short positions are excluded by
law, so no 13F tracker anywhere has them, and neither does any site built on
13F data. If you want to know what a fund is betting against, 13F is the wrong
document entirely.

The UK is different. Under the Short Selling Regulation, any net short position
reaching 0.5% of a company's issued share capital must be disclosed publicly,
by name, and every 0.1% move after that. The FCA publishes the whole register.
That gives genuine per-fund short positions -- for UK-listed shares only.

A trap worth knowing about: a fund re-files only when it crosses a threshold, so
the register's last row for a position can be years old. Debenhams and Thomas
Cook still show open shorts from 2019; both companies are gone. Anything not
re-disclosed close to the feed's own cutoff is treated as closed here, which
takes ~6,200 apparently-open positions down to ~900 real ones.
"""
import datetime as dt
import io
import os
from collections import Counter, defaultdict

from . import http

FCA_URL = "https://www.fca.org.uk/publication/data/short-positions-daily-update.xlsx"
CACHE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                     "out", "fca-shorts.xlsx")

# A position not re-disclosed within this many days of the feed's own latest
# date is assumed closed rather than live.
LIVE_WINDOW_DAYS = 90


def download(refresh=True):
    os.makedirs(os.path.dirname(CACHE), exist_ok=True)
    if refresh or not os.path.exists(CACHE):
        raw = http.get(FCA_URL, timeout=90).content
        with open(CACHE, "wb") as fh:
            fh.write(raw)
    return CACHE


def _rows(path):
    import openpyxl
    wb = openpyxl.load_workbook(path, read_only=True)
    ws = wb[wb.sheetnames[0]]
    it = ws.iter_rows(values_only=True)
    next(it, None)                                  # header
    for row in it:
        if not row or len(row) < 5:
            continue
        holder, issuer, isin, pct, date = row[:5]
        if not isinstance(date, dt.datetime) or not holder:
            continue
        try:
            pct = float(pct) if pct not in (None, "") else 0.0
        except (TypeError, ValueError):
            continue
        yield holder.strip(), (issuer or "").strip(), (isin or "").strip(), pct, date


def collect(path=None, live_window=LIVE_WINDOW_DAYS, log=print):
    """Current UK short positions, plus who is shorting the most."""
    path = path or download()

    latest = {}
    for holder, issuer, isin, pct, date in _rows(path):
        key = (holder, isin)
        if key not in latest or date > latest[key]["date"]:
            latest[key] = {"date": date, "pct": pct, "issuer": issuer, "holder": holder}
    if not latest:
        return None

    feed_date = max(v["date"] for v in latest.values()).date()
    cutoff = feed_date - dt.timedelta(days=live_window)

    live = [v for v in latest.values()
            if v["date"].date() >= cutoff and v["pct"] > 0]
    live.sort(key=lambda v: -v["pct"])

    by_fund = defaultdict(lambda: {"n": 0, "total": 0.0})
    for v in live:
        f = by_fund[v["holder"]]
        f["n"] += 1
        f["total"] += v["pct"]

    by_issuer = defaultdict(lambda: {"n": 0, "total": 0.0, "funds": []})
    for v in live:
        b = by_issuer[v["issuer"]]
        b["n"] += 1
        b["total"] += v["pct"]
        b["funds"].append(v["holder"])

    crowded = sorted(
        ({"issuer": k, "funds": v["n"], "total_pct": v["total"],
          "names": sorted(set(v["funds"]))[:6]} for k, v in by_issuer.items()),
        key=lambda x: (-x["funds"], -x["total_pct"]))

    funds = sorted(({"fund": k, "positions": v["n"], "total_pct": v["total"]}
                    for k, v in by_fund.items()),
                   key=lambda x: -x["positions"])

    today = dt.date.today()
    out = {
        "source": "UK FCA short position register",
        "source_url": "https://www.fca.org.uk/markets/short-selling/notification-and-disclosure-net-short-positions",
        "feed_date": feed_date.isoformat(),
        "feed_age_days": (today - feed_date).days,
        "live_window_days": live_window,
        "n_live": len(live),
        "n_funds": len(funds),          # real total, not the display cap below
        "n_all_time": len(latest),
        "biggest": [{"issuer": v["issuer"], "holder": v["holder"],
                     "pct": v["pct"], "date": v["date"].date().isoformat()}
                    for v in live[:14]],
        "crowded": crowded[:12],
        "funds": funds[:14],
    }
    log(f"      {out['n_live']} live UK shorts as of {feed_date} "
        f"({out['feed_age_days']}d old), {len(funds)} funds")
    return out


def cross_reference(shorts, long_names):
    """Funds that appear both in the 13F long list and the UK short register.

    Seeing the same manager on both sides is the closest this data gets to a
    real picture of what a fund is actually doing.
    """
    if not shorts:
        return []
    norm = lambda s: "".join(c for c in (s or "").lower() if c.isalnum())[:12]
    longs = {norm(n): n for n in long_names if n}
    hits = []
    for f in shorts["funds"]:
        k = norm(f["fund"])
        for lk, ln in longs.items():
            if k and lk and (k.startswith(lk[:8]) or lk.startswith(k[:8])):
                hits.append({**f, "long_name": ln})
                break
    return hits
