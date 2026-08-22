"""Gather every source into one JSON blob for the dashboard to render."""
import datetime as dt
import json
import os
from collections import Counter, defaultdict

from . import congress, events, form4, people, score, thirteenf

OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "out")


def _sector_bucket(title):
    return title


# Big banks and asset managers. Their 13Fs are enormous and mostly client money,
# which is exactly the point the dashboard makes with them.
INSTITUTIONS = [
    ("JPMorgan Chase", 19617),
    ("BlackRock", 2012383),
    ("Vanguard Group", 102909),
    ("State Street", 93751),
    ("Goldman Sachs", 886982),
    ("Morgan Stanley", 895421),
    ("Citadel Advisors", 1423053),
]


def collect(days=14, max_filings=600, congress_days=60, max_ptrs=60,
            funds=("1067983", "1336528", "1649339"), institutions=None,
            news_days=5, watchlist=None, log=print):
    today = dt.date.today()
    start = (today - dt.timedelta(days=days)).isoformat()
    end = today.isoformat()

    # ---------------------------------------------------------- Form 4
    log(f"[1/6] insider filings {start} -> {end} ...")
    rows = form4.recent(start, end, max_filings=max_filings)
    log(f"      {len(rows)} transactions")

    clusters = score.cluster_buys(rows, min_insiders=2, min_value=25_000)
    sells = score.notable_sells(rows, min_value=1_000_000)

    buys_all = [r for r in rows if r.get("code") == "P" and r.get("acq_disp") == "A"
                and not r.get("derivative") and r.get("value")]
    sells_all = [r for r in rows if r.get("code") == "S" and r.get("acq_disp") == "D"
                 and not r.get("derivative") and r.get("value")]

    # daily buy/sell dollar flow
    flow = defaultdict(lambda: {"buy": 0.0, "sell": 0.0, "nbuy": 0, "nsell": 0})
    for r in buys_all:
        if r.get("date"):
            flow[r["date"]]["buy"] += r["value"]
            flow[r["date"]]["nbuy"] += 1
    for r in sells_all:
        if r.get("date"):
            flow[r["date"]]["sell"] += r["value"]
            flow[r["date"]]["nsell"] += 1
    flow_series = [dict(date=d, **v) for d, v in sorted(flow.items()) if d >= start]

    # what kind of filings are these, really?
    code_names = {"P": "Open-market buy", "S": "Open-market sale", "A": "Free stock grant",
                  "M": "Option exercise", "F": "Shares held back for tax", "G": "Gift",
                  "C": "Convertible exercise", "D": "Disposition to issuer",
                  "X": "Option expiry"}
    code_mix = Counter(r.get("code") for r in rows if r.get("code"))
    code_mix = [{"code": c, "label": code_names.get(c, c), "n": n}
                for c, n in code_mix.most_common(8)]

    # seniority split of buyers
    def rank(r):
        t = (r.get("title") or "").lower()
        if any(s in t for s in ("chief executive", "ceo")):
            return "CEO"
        if any(s in t for s in ("chief financial", "cfo")):
            return "CFO"
        if r.get("is_officer"):
            return "Other officer"
        if r.get("is_director"):
            return "Board director"
        if r.get("is_10pct"):
            return "10%+ owner"
        return "Other"

    buyer_mix = Counter(rank(r) for r in buys_all)
    buyer_mix = [{"who": k, "n": v} for k, v in buyer_mix.most_common()]

    planned = sum(1 for r in sells_all if r.get("plan_10b5_1"))
    plan_split = [{"kind": "Pre-scheduled (10b5-1)", "n": planned},
                  {"kind": "Discretionary decision", "n": len(sells_all) - planned}]

    # ---------------------------------------------------------- Congress
    log(f"[2/6] congress PTRs, last {congress_days} days ...")
    since = today - dt.timedelta(days=congress_days)
    ptrs = congress.house_ptrs(year=today.year, since=since)[:max_ptrs]
    crows, scanned = [], 0
    for i, rec in enumerate(ptrs, 1):
        try:
            got, _ = congress.parse_ptr(rec)
        except Exception as e:
            log(f"      ! {rec.get('Last')}: {e}")
            continue
        if not got:
            scanned += 1
        crows.extend(got)
        if i % 10 == 0:
            log(f"      {i}/{len(ptrs)} PDFs")
    log(f"      {len(crows)} congressional transactions")

    cagg = score.summarize_congress(crows, equities_only=True)

    # how late were they? filing date minus transaction date
    lateness = []
    for r in crows:
        try:
            td = dt.datetime.strptime(r["date"], "%m/%d/%Y").date()
            fd = dt.datetime.strptime(r["filed"], "%m/%d/%Y").date()
            lateness.append((fd - td).days)
        except (ValueError, TypeError, KeyError):
            pass
    buckets = [("0-14 days", 0, 14), ("15-30 days", 15, 30), ("31-45 days", 31, 45),
               ("46-90 days", 46, 90), ("over 90 days", 91, 100000)]
    lateness_hist = [{"bucket": b, "n": sum(1 for d in lateness if lo <= d <= hi)}
                     for b, lo, hi in buckets]

    asset_mix = Counter(r.get("asset_type") or "??" for r in crows)
    type_names = {"ST": "Stocks", "GS": "Government bonds", "CS": "Cash / CDs",
                  "MF": "Mutual funds", "OT": "Other", "OP": "Options",
                  "EF": "ETFs", "RP": "Real property", "PS": "Private stock",
                  "AB": "Bank accounts", "??": "Unclassified"}
    asset_mix = [{"kind": type_names.get(k, k), "n": v}
                 for k, v in asset_mix.most_common(8)]

    by_member = defaultdict(lambda: {"n": 0, "low": 0, "high": 0, "buys": 0, "sells": 0})
    for r in crows:
        m = by_member[r["member"]]
        m["n"] += 1
        m["low"] += r["amount_low"] or 0
        m["high"] += r["amount_high"] or r["amount_low"] or 0
        if r["type"] == "purchase":
            m["buys"] += 1
        elif r["type"] == "sale":
            m["sells"] += 1
    members = sorted(({"member": k, **v} for k, v in by_member.items()),
                     key=lambda x: -x["high"])[:12]

    # ---------------------------------------------------------- 13F
    log("[3/6] fund quarterly moves ...")
    fund_blocks = []
    for cik in funds:
        try:
            d = thirteenf.delta(cik)
        except Exception as e:
            log(f"      ! {cik}: {e}")
            continue
        held = sorted((m for m in d["moves"] if m["value"] > 0),
                      key=lambda m: -m["value"])
        top = held[:10]
        held_total = sum(m["value"] for m in held) or 1.0
        acted = [m for m in d["moves"] if m["action"] != "HOLD"]
        acted.sort(key=lambda m: -(m["value"] or m["prev_shares"] * 0 or 0))
        fund_blocks.append({
            "name": d["cur"]["entity"],
            "cik": cik,
            "period": d["cur"]["period"],
            "prev_period": d["prev"]["period"],
            "filed": d["cur"]["filed"],
            "total": d["total_value"],
            "stale_days": (today - dt.date.fromisoformat(d["cur"]["period"])).days,
            "positions": len(held),
            "top10_pct": sum(m["value"] for m in held[:10]) / held_total * 100,
            "top": [{"issuer": m["issuer"], "value": m["value"],
                     "pct": m["pct_portfolio"], "action": m["action"],
                     "put_call": m["put_call"]} for m in top],
            "moves": [{"issuer": m["issuer"], "action": m["action"],
                       "value": m["value"], "pct_shares": m["pct_shares"],
                       "put_call": m["put_call"]} for m in acted[:14]],
            "counts": Counter(m["action"] for m in d["moves"]),
        })
        log(f"      {d['cur']['entity']}")

    # ---------------------------------------------------------- institutions
    log("[4/6] big banks and asset managers ...")
    inst = []
    for label, cik in (institutions or INSTITUTIONS):
        try:
            summ = thirteenf.summary(cik)
        except Exception as e:
            log(f"      ! {label}: {e}")
            continue
        if not summ:
            continue
        summ["label"] = label
        summ["stale_days"] = (today - dt.date.fromisoformat(summ["period"])).days
        inst.append(summ)
        log(f"      {label}: {summ['positions']:,} positions, "
            f"${summ['total']/1e12:.2f}T, top10 {summ['top10_pct']:.0f}%")

    # ---------------------------------------------------------- people
    log("[5/6] individual SEC records ...")
    profiles = people.collect(watchlist=watchlist, max_form4=10)
    for pr in profiles:
        log(f"      {pr.get('name')}: {pr.get('n_filings', 0)} filings")

    # ---------------------------------------------------------- 8-K news
    log(f"[6/6] 8-K material events, last {news_days} days ...")
    nstart = (today - dt.timedelta(days=news_days)).isoformat()
    news = events.recent(nstart, end, max_filings=500, min_weight=2)
    watch_tickers = ([c["ticker"] for c in clusters] +
                     [s2["ticker"] for s2 in sells] +
                     [t["ticker"] for t in cagg[:14]])
    linked = events.cross_reference(news, watch_tickers)
    news_mix = Counter(n["headline"] for n in news)
    log(f"      {len(news)} notable events; {len(linked)} at companies already on the page")

    data = {
        "generated": dt.datetime.now().strftime("%Y-%m-%d %H:%M"),
        "window": {"insider_days": days, "congress_days": congress_days,
                   "start": start, "end": end},
        "insiders": {
            "n_transactions": len(rows),
            "n_buys": len(buys_all),
            "n_sells": len(sells_all),
            "buy_value": sum(r["value"] for r in buys_all),
            "sell_value": sum(r["value"] for r in sells_all),
            "clusters": clusters[:12],
            "sells": sells[:12],
            "flow": flow_series,
            "code_mix": code_mix,
            "buyer_mix": buyer_mix,
            "plan_split": plan_split,
        },
        "congress": {
            "n_ptrs": len(ptrs),
            "n_transactions": len(crows),
            "n_scanned_skipped": scanned,
            "by_ticker": cagg[:14],
            "members": members,
            "lateness": lateness_hist,
            "asset_mix": asset_mix,
            "median_lateness": sorted(lateness)[len(lateness) // 2] if lateness else None,
        },
        "funds": fund_blocks,
        "institutions": inst,
        "people": profiles,
        "news": {
            "window_days": news_days,
            "n": len(news),
            "serious": [n for n in news if n["severity"] == "serious"][:14],
            "recent": news[:20],
            "linked": linked[:10],
            "mix": [{"label": k, "n": v} for k, v in news_mix.most_common(7)],
        },
    }

    os.makedirs(OUT, exist_ok=True)
    path = os.path.join(OUT, "data.json")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=1, default=str)
    log(f"wrote {path}")
    return data
