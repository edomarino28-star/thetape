"""Turn raw filings into ranked, de-noised signals.

This ranks *filings by how unusual they are*. It is not advice and it makes no
claim about future prices. Weighting reflects what the academic literature on
insider trading finds least noisy (Lakonishok & Lee; Cohen, Malloy & Pomorski):
open-market purchases, by operating officers, not on a pre-set plan, clustered.
"""
from collections import defaultdict

SENIOR = ("chief executive", "ceo", "chief financial", "cfo", "president",
          "chief operating", "coo")


def _seniority(row):
    t = (row.get("title") or "").lower()
    if any(s in t for s in SENIOR):
        return 2.0
    if row.get("is_officer"):
        return 1.5
    if row.get("is_director"):
        return 1.2
    if row.get("is_10pct"):
        return 1.1
    return 1.0


def cluster_buys(rows, min_insiders=2, min_value=25_000):
    """Companies where several insiders bought on the open market at once."""
    by_issuer = defaultdict(list)
    for r in rows:
        if r.get("code") != "P" or r.get("acq_disp") != "A" or r.get("derivative"):
            continue
        if not r.get("value") or r["value"] < min_value:
            continue
        by_issuer[(r.get("ticker") or "?", r.get("issuer"))].append(r)

    out = []
    for (ticker, issuer), buys in by_issuer.items():
        insiders = {b.get("owner_cik") for b in buys}
        if len(insiders) < min_insiders:
            continue
        total = sum(b["value"] for b in buys)
        planned = sum(1 for b in buys if b.get("plan_10b5_1"))
        weight = max(_seniority(b) for b in buys)
        discount = 0.5 if planned == len(buys) else 1.0
        out.append({
            "ticker": ticker, "issuer": issuer,
            "insiders": len(insiders), "trades": len(buys),
            "total_value": total,
            "titles": sorted({(b.get("title") or ("Director" if b.get("is_director") else "?"))
                              for b in buys}),
            "all_10b5_1": planned == len(buys),
            "score": round(len(insiders) * (total ** 0.5) * weight * discount / 100, 1),
            "dates": sorted({b.get("date") for b in buys if b.get("date")}),
        })
    out.sort(key=lambda x: -x["score"])
    return out


def notable_sells(rows, min_value=1_000_000):
    """Large open-market sales NOT on a 10b5-1 plan -- the rarer, louder case.

    A single decision is often filed as a dozen tranche rows at different
    prices, so collapse by (insider, issuer, trade date) before ranking.
    """
    agg = {}
    for r in rows:
        if r.get("code") != "S" or r.get("acq_disp") != "D":
            continue
        if r.get("derivative") or r.get("plan_10b5_1") or not r.get("value"):
            continue
        key = (r.get("owner_cik"), r.get("ticker"), r.get("date"))
        a = agg.setdefault(key, {
            "ticker": r.get("ticker"), "issuer": r.get("issuer"),
            "owner": r.get("owner"), "title": r.get("title"),
            "is_officer": r.get("is_officer"), "is_director": r.get("is_director"),
            "date": r.get("date"), "value": 0.0, "shares": 0.0, "tranches": 0,
            "shares_after": r.get("shares_after"),
        })
        a["value"] += r["value"]
        a["shares"] += r.get("shares") or 0
        a["tranches"] += 1
        if r.get("shares_after") is not None:
            a["shares_after"] = r["shares_after"]

    out = [a for a in agg.values() if a["value"] >= min_value]
    for a in out:
        held = a["shares_after"]
        total = (held or 0) + a["shares"]
        a["pct_of_stake"] = (a["shares"] / total * 100) if total else None
        a["avg_price"] = a["value"] / a["shares"] if a["shares"] else None
    out.sort(key=lambda a: -a["value"])
    return out


def summarize_congress(rows, equities_only=True):
    """Aggregate parsed PTR rows by ticker."""
    if equities_only:
        rows = [r for r in rows if r.get("asset_type") in (None, "ST", "OP", "SC")
                and r.get("ticker")]
    agg = defaultdict(lambda: {"buy": 0, "sell": 0, "members": set(),
                               "low": 0, "high": 0, "asset": None,
                               "trade_dates": [], "filed_dates": []})
    for r in rows:
        key = r.get("ticker") or r.get("asset")
        a = agg[key]
        a["asset"] = a["asset"] or r.get("asset")
        a["members"].add(r["member"])
        # keep the dates -- aggregating them away is what made the table
        # impossible to read: "2 members bought AAPL" with no when
        if r.get("date"):
            a["trade_dates"].append(r["date"])
        if r.get("filed"):
            a["filed_dates"].append(r["filed"])
        a["low"] += r["amount_low"] or 0
        a["high"] += r["amount_high"] or r["amount_low"] or 0
        if r["type"] == "purchase":
            a["buy"] += 1
        elif r["type"] == "sale":
            a["sell"] += 1
    def _iso(d):
        """PTR dates are MM/DD/YYYY; sort them properly, not as strings."""
        try:
            m, day, y = d.split("/")
            return f"{y}-{m}-{day}"
        except (ValueError, AttributeError):
            return d

    out = []
    for k, a in agg.items():
        td = sorted(a["trade_dates"], key=_iso)
        fd = sorted(a["filed_dates"], key=_iso)
        out.append({"ticker": k, "asset": a["asset"], "buys": a["buy"],
                    "sells": a["sell"], "members": len(a["members"]),
                    "names": sorted(a["members"]),
                    "min_notional": a["low"], "max_notional": a["high"],
                    "first_trade": td[0] if td else None,
                    "last_trade": td[-1] if td else None,
                    "last_filed": fd[-1] if fd else None})
    out.sort(key=lambda x: (-x["members"], -x["max_notional"]))
    return out
