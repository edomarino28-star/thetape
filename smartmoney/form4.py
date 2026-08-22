"""Form 3/4/5 (insider transactions) — the fastest-reporting signal on EDGAR.

Form 4 is due within 2 business days of the trade, so this is near-real-time.
Transaction codes that matter:
  P  open-market purchase       <- the one with actual predictive research behind it
  S  open-market sale           <- noisy; most are diversification / 10b5-1
  A  grant/award (free shares)  <- not a signal
  M  option exercise
  F  shares withheld for tax
  G  gift
"""
import xml.etree.ElementTree as ET
from . import edgar, http

MEANINGFUL_BUY = {"P"}
MEANINGFUL_SELL = {"S"}


def _v(node, path, default=None):
    """Ownership XML wraps most values in a <value> child."""
    el = node.find(path)
    if el is None:
        return default
    child = el.find("value")
    text = (child.text if child is not None else el.text) or ""
    return text.strip() or default


def _f(node, path):
    raw = _v(node, path)
    if raw is None:
        return None
    try:
        return float(raw.replace(",", "").replace("$", ""))
    except ValueError:
        return None


def parse(xml_bytes):
    """Parse one ownership document into a list of transaction dicts."""
    root = ET.fromstring(xml_bytes)
    issuer_cik = _v(root, "issuer/issuerCik")
    issuer = _v(root, "issuer/issuerName")
    ticker = _v(root, "issuer/issuerTradingSymbol")
    period = _v(root, "periodOfReport")
    plan_10b5 = _v(root, "aff10b5One") == "1"

    owners = []
    for ro in root.findall("reportingOwner"):
        rel = ro.find("reportingOwnerRelationship")
        owners.append({
            "owner": _v(ro, "reportingOwnerId/rptOwnerName"),
            "owner_cik": _v(ro, "reportingOwnerId/rptOwnerCik"),
            "is_director": _v(rel, "isDirector") == "1" if rel is not None else False,
            "is_officer": _v(rel, "isOfficer") == "1" if rel is not None else False,
            "is_10pct": _v(rel, "isTenPercentOwner") == "1" if rel is not None else False,
            "title": _v(rel, "officerTitle") if rel is not None else None,
        })
    who = owners[0] if owners else {}

    rows = []
    for table, derivative in (("nonDerivativeTable/nonDerivativeTransaction", False),
                              ("derivativeTable/derivativeTransaction", True)):
        for t in root.findall(table):
            code = _v(t, "transactionCoding/transactionCode")
            shares = _f(t, "transactionAmounts/transactionShares")
            price = _f(t, "transactionAmounts/transactionPricePerShare")
            ad = _v(t, "transactionAmounts/transactionAcquiredDisposedCode")
            held = _f(t, "postTransactionAmounts/sharesOwnedFollowingTransaction")
            rows.append({
                "ticker": ticker, "issuer": issuer, "issuer_cik": issuer_cik,
                "period": period,
                "date": _v(t, "transactionDate"),
                "owner": who.get("owner"), "owner_cik": who.get("owner_cik"),
                "title": who.get("title"),
                "is_officer": who.get("is_officer"), "is_director": who.get("is_director"),
                "is_10pct": who.get("is_10pct"),
                "security": _v(t, "securityTitle"),
                "derivative": derivative,
                "code": code,
                "acq_disp": ad,
                "shares": shares,
                "price": price,
                "value": (shares * price) if (shares and price) else None,
                "shares_after": held,
                "plan_10b5_1": plan_10b5,
                "n_owners": len(owners),
            })
    return rows


def fetch(cik, accession, document):
    return parse(edgar.fetch_file(cik, accession, document))


def recent(start, end, ticker=None, max_filings=400):
    """All Form 4s filed in a date window (optionally for one issuer ticker)."""
    entity = None
    if ticker:
        hit = edgar.resolve_ticker(ticker)
        if not hit:
            raise SystemExit(f"unknown ticker {ticker}")
        entity = f"CIK{hit[0]:010d}"

    rows, offset = [], 0
    while offset < max_filings:
        hits, total = edgar.search_filings("4", start, end, size=100,
                                           offset=offset, entity=entity)
        if not hits:
            break
        for h in hits:
            cik = h["ciks"][0] if h["ciks"] else None
            try:
                rows.extend(dict(r, accession=h["accession"], filed=h["filed"])
                            for r in fetch(cik, h["accession"], h["document"]))
            except Exception as e:                      # skip malformed/legacy docs
                print(f"  ! {h['accession']}: {e}")
        offset += len(hits)
        if offset >= min(total, max_filings) or offset >= 10000:
            break
    return rows
