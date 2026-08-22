"""Daily price history, cached to disk.

A backtest hammers the same tickers repeatedly, so every series is cached and
re-read from disk rather than re-fetched. Delete out/prices/ to force a refresh.

Yahoo's chart endpoint is unofficial and can change or rate-limit without
notice. It is used here because it needs no key; if it breaks, swap the one
`_fetch` function -- everything above it is source-agnostic.
"""
import datetime as dt
import json
import os
import time
import urllib.error
import urllib.request

OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "out")
CACHE = os.path.join(OUT, "prices")
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120 Safari/537.36")
CHART = ("https://query1.finance.yahoo.com/v8/finance/chart/{t}"
         "?period1={p1}&period2={p2}&interval=1d")

_last_call = [0.0]
MIN_GAP = 0.35


def _throttle():
    gap = time.monotonic() - _last_call[0]
    if gap < MIN_GAP:
        time.sleep(MIN_GAP - gap)
    _last_call[0] = time.monotonic()


def _fetch(ticker, start, end):
    p1 = int(dt.datetime.combine(start, dt.time()).timestamp())
    p2 = int(dt.datetime.combine(end, dt.time()).timestamp())
    url = CHART.format(t=ticker.replace(".", "-"), p1=p1, p2=p2)
    for attempt in range(3):
        _throttle()
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            raw = urllib.request.urlopen(req, timeout=25).read()
            break
        except urllib.error.HTTPError as e:
            if e.code in (404, 400):
                return []                       # no such listing
            if attempt == 2:
                raise
            time.sleep(2 ** attempt)
        except Exception:
            if attempt == 2:
                raise
            time.sleep(2 ** attempt)

    j = json.loads(raw)
    res = (j.get("chart") or {}).get("result")
    if not res:
        return []
    r = res[0]
    ts = r.get("timestamp") or []
    q = (r.get("indicators") or {}).get("quote") or [{}]
    q = q[0]
    bars = []
    for i, t in enumerate(ts):
        o, h, lo, c = (q.get("open") or [])[i], (q.get("high") or [])[i], \
                      (q.get("low") or [])[i], (q.get("close") or [])[i]
        if None in (o, h, lo, c):
            continue
        bars.append({"date": dt.date.fromtimestamp(t).isoformat(),
                     "open": o, "high": h, "low": lo, "close": c})
    return bars


def history(ticker, start, end, refresh=False):
    """Daily bars for `ticker` between two dates. Cached on disk."""
    os.makedirs(CACHE, exist_ok=True)
    safe = ticker.replace("/", "_").replace("\\", "_").upper()
    path = os.path.join(CACHE, f"{safe}.json")

    if os.path.exists(path) and not refresh:
        with open(path, encoding="utf-8") as fh:
            blob = json.load(fh)
        if blob.get("start") <= start.isoformat() and blob.get("end") >= end.isoformat():
            return blob["bars"]

    bars = _fetch(ticker, start, end)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump({"ticker": ticker, "start": start.isoformat(),
                   "end": end.isoformat(), "bars": bars}, fh)
    return bars


def index_by_date(bars):
    return {b["date"]: b for b in bars}


def next_session(bars, after):
    """First trading day strictly after `after` (an ISO date string).

    This is the entry rule: you read a filing, you cannot trade before the next
    open. Using the same day's close instead is the single most common way a
    backtest accidentally sees the future.
    """
    for i, b in enumerate(bars):
        if b["date"] > after:
            return i, b
    return None, None
