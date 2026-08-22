"""8-K material events -- company news, straight from the primary source.

An 8-K is what a company files when something material happens that shareholders
are entitled to know before the next quarterly report. It is news before it is
news: the press writes the story from this document.

Each 8-K declares one or more numbered items saying what kind of event it was.
Most are routine plumbing (9.01 is just "we attached an exhibit"). A handful mean
something genuinely bad happened, and those are worth surfacing on their own.
"""
from . import edgar

ITEMS = {
    "1.01": ("Signed a major agreement", 1),
    "1.02": ("Ended a major agreement", 2),
    "1.03": ("Bankruptcy or receivership", 3),
    "1.05": ("Material cybersecurity incident", 3),
    "2.01": ("Completed an acquisition or sale", 1),
    "2.02": ("Earnings / financial results", 1),
    "2.03": ("Took on significant debt", 1),
    "2.04": ("Debt obligation accelerated", 3),
    "2.05": ("Restructuring or exit costs", 2),
    "2.06": ("Wrote down assets (impairment)", 2),
    "3.01": ("Delisting notice / listing rule failure", 2),
    "3.02": ("Sold unregistered shares (dilution)", 2),
    "3.03": ("Changed shareholder rights", 2),
    "4.01": ("Changed auditors", 3),
    "4.02": ("Past financials can no longer be relied on", 3),
    "5.01": ("Change of control", 2),
    "5.02": ("Executive or director change", 2),
    "5.03": ("Amended charter or bylaws", 0),
    "5.07": ("Shareholder vote results", 0),
    "5.08": ("Shareholder director nominations", 0),
    "7.01": ("Regulation FD disclosure", 0),
    "8.01": ("Other events", 0),
    "9.01": ("Exhibits attached", 0),
}
# 3 = serious (something went materially wrong), 2 = notable, 1 = substantive,
# 0 = routine plumbing. Delisting notices sit at 2, not 3: they are common for
# microcaps and mostly resolve, so ranking them top drowns out real red flags.
SEVERITY = {3: "serious", 2: "notable", 1: "substantive", 0: "routine"}


def describe(codes):
    """Translate a filing's item codes into plain English, worst first."""
    out = []
    for c in codes or []:
        label, weight = ITEMS.get(c, (f"Item {c}", 0))
        out.append({"code": c, "label": label, "weight": weight})
    out.sort(key=lambda x: -x["weight"])
    return out


def recent(start, end, max_filings=400, min_weight=2):
    """Recent 8-Ks, keeping only those with at least one item of `min_weight`.

    Returns one row per filing, not per item -- a single 8-K reporting an
    executive departure and attaching an exhibit is one piece of news.
    """
    rows, offset, seen = [], 0, set()
    while offset < max_filings:
        hits, total = edgar.search_filings("8-K", start, end, size=100, offset=offset)
        if not hits:
            break
        for h in hits:
            if h["accession"] in seen:
                continue
            seen.add(h["accession"])
            items = describe(h.get("items"))
            top = items[0] if items else None
            if not top or top["weight"] < min_weight:
                continue
            name = h["names"][0] if h["names"] else ""
            ticker = None
            if "(" in name and ")" in name:
                inner = name.split("(")[1].split(")")[0].strip()
                if inner.replace("-", "").replace(".", "").isalnum() and len(inner) <= 6:
                    ticker = inner
            rows.append({
                "company": name.split("  (")[0].strip(),
                "ticker": ticker,
                "cik": h["ciks"][0] if h["ciks"] else None,
                "filed": h["filed"],
                "accession": h["accession"],
                "headline": top["label"],
                "severity": SEVERITY[top["weight"]],
                "weight": top["weight"],
                "all_items": [i["label"] for i in items if i["weight"] > 0],
                "url": (f"https://www.sec.gov/Archives/edgar/data/"
                        f"{h['ciks'][0]}/{h['accession'].replace('-', '')}/"
                        f"{h['document']}") if h["ciks"] else None,
            })
        offset += len(hits)
        if offset >= min(total, max_filings):
            break
    rows.sort(key=lambda r: (-r["weight"], r["filed"]), reverse=False)
    rows.sort(key=lambda r: (r["filed"], r["weight"]), reverse=True)
    return rows


def cross_reference(events, tickers):
    """Events at companies that also showed up elsewhere in the dashboard.

    A cluster of insiders buying is more interesting when you can see what the
    company told the market the same week.
    """
    want = {t.upper() for t in tickers if t}
    return [e for e in events if e.get("ticker") and e["ticker"].upper() in want]
