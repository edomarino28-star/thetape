"""13F-HR — institutional holdings.

Reality check: filed 45 days after quarter end, long US-listed equities only,
no shorts, no bonds, no cash, no derivatives economics. You are seeing a
photograph of a portfolio that is up to 4.5 months stale. Useful for tracking
concentrated, low-turnover managers. Useless for tracking Citadel.
"""
import xml.etree.ElementTree as ET
from . import edgar


def _strip_ns(root):
    for el in root.iter():
        if "}" in el.tag:
            el.tag = el.tag.split("}", 1)[1]
    return root


def parse_infotable(xml_bytes):
    root = _strip_ns(ET.fromstring(xml_bytes))
    out = []
    for it in root.findall(".//infoTable"):
        def g(p, d=None):
            el = it.find(p)
            return (el.text or "").strip() if el is not None and el.text else d
        try:
            value = float(g("value", "0") or 0)
        except ValueError:
            value = 0.0
        try:
            shares = float(g("shrsOrPrnAmt/sshPrnamt", "0") or 0)
        except ValueError:
            shares = 0.0
        out.append({
            "issuer": g("nameOfIssuer"),
            "cusip": g("cusip"),
            "class": g("titleOfClass"),
            "value": value,              # USD (post-2022 filings are whole dollars)
            "shares": shares,
            "sh_prn": g("shrsOrPrnAmt/sshPrnamtType"),
            "put_call": g("putCall"),
            "discretion": g("investmentDiscretion"),
        })
    return out


def _infotable_name(files):
    cands = [f for f in files if f.lower().endswith(".xml")
             and "primary_doc" not in f.lower()]
    return cands[0] if cands else None


def holdings(cik, n=1):
    """Return the n most recent 13F-HR holdings snapshots, newest first."""
    snaps = []
    for f in edgar.filings(cik, forms={"13F-HR"}, limit=n):
        files = edgar.filing_files(f["cik"], f["accession"])
        name = _infotable_name(files)
        if not name:
            continue
        rows = parse_infotable(edgar.fetch_file(f["cik"], f["accession"], name))
        snaps.append({"meta": f, "rows": rows})
    return snaps


def _by_key(rows):
    agg = {}
    for r in rows:
        k = (r["cusip"], r["put_call"] or "")
        a = agg.setdefault(k, {"issuer": r["issuer"], "cusip": r["cusip"],
                               "put_call": r["put_call"], "value": 0.0, "shares": 0.0})
        a["value"] += r["value"]
        a["shares"] += r["shares"]
    return agg


def delta(cik):
    """Quarter-over-quarter change: what did this manager actually DO?"""
    snaps = holdings(cik, n=2)
    if len(snaps) < 2:
        raise SystemExit("need two 13F-HR filings to diff")
    new, old = _by_key(snaps[0]["rows"]), _by_key(snaps[1]["rows"])
    total_new = sum(v["value"] for v in new.values()) or 1.0

    moves = []
    for k in set(new) | set(old):
        a, b = new.get(k), old.get(k)
        cur_sh = a["shares"] if a else 0.0
        prev_sh = b["shares"] if b else 0.0
        if cur_sh == prev_sh:
            action = "HOLD"
        elif prev_sh == 0:
            action = "NEW"
        elif cur_sh == 0:
            action = "EXIT"
        elif cur_sh > prev_sh:
            action = "ADD"
        else:
            action = "TRIM"
        moves.append({
            "issuer": (a or b)["issuer"],
            "cusip": k[0], "put_call": k[1],
            "action": action,
            "shares": cur_sh, "prev_shares": prev_sh,
            "d_shares": cur_sh - prev_sh,
            "pct_shares": ((cur_sh - prev_sh) / prev_sh * 100) if prev_sh else None,
            "value": a["value"] if a else 0.0,
            "pct_portfolio": (a["value"] / total_new * 100) if a else 0.0,
        })
    moves.sort(key=lambda m: -abs(m["value"] if m["action"] in ("NEW", "ADD") else
                                  (m["prev_shares"] * 0 + m["value"])))
    return {"cur": snaps[0]["meta"], "prev": snaps[1]["meta"],
            "total_value": total_new, "moves": moves}


def summary(cik, top_n=10):
    """Headline stats for one 13F filer, without holding 30k rows in memory.

    Concentration is the number that matters: a bank's 13F is essentially the
    whole market, so its "top holdings" are just the market-cap ranking and
    carry no opinion. A concentrated manager's top ten IS the thesis.
    """
    snaps = holdings(cik, n=1)
    if not snaps:
        return None
    meta, rows = snaps[0]["meta"], snaps[0]["rows"]
    agg = _by_key(rows)
    vals = sorted((v["value"] for v in agg.values()), reverse=True)
    total = sum(vals) or 1.0
    top = sorted(agg.values(), key=lambda v: -v["value"])[:top_n]
    return {
        "cik": int(str(cik)),
        "name": meta["entity"],
        "period": meta["period"],
        "filed": meta["filed"],
        "total": total,
        "positions": len(agg),
        "top10_pct": sum(vals[:10]) / total * 100,
        "top": [{"issuer": t["issuer"], "value": t["value"],
                 "pct": t["value"] / total * 100, "put_call": t["put_call"]}
                for t in top],
    }
