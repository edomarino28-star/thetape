"""Track a named individual's SEC record.

Anyone who is an officer, director, or >10% owner of a public company has an
EDGAR identity of their own, and every Form 3/4/5 and Schedule 13D they file
sits under it. That makes a person -- not just a company -- something you can
follow directly from primary sources.

Seeded with the Trump family because they are the most-asked-about case, but the
CIK is just a parameter: add anyone.
"""
from . import edgar, form4

WATCHLIST = [
    {"cik": 947033, "name": "Donald J. Trump",
     "note": "President; former direct holder of Trump Media (DJT)"},
    {"cik": 2016181, "name": "Donald Trump Jr.",
     "note": "Director at several listed companies"},
]

OWNERSHIP_FORMS = {"3", "4", "5", "4/A", "3/A", "5/A"}
STAKE_FORMS = {"SC 13D", "SC 13D/A", "SCHEDULE 13D", "SCHEDULE 13D/A",
               "SC 13G", "SC 13G/A", "SCHEDULE 13G", "SCHEDULE 13G/A"}


def profile(cik, name=None, note=None, max_form4=12):
    """Filing history plus parsed transactions for one person."""
    all_filings = edgar.filings(cik, limit=60)
    entity = all_filings[0]["entity"] if all_filings else name

    timeline = [{"form": f["form"], "filed": f["filed"], "period": f["period"],
                 "accession": f["accession"],
                 "kind": ("ownership" if f["form"] in OWNERSHIP_FORMS
                          else "stake" if f["form"].upper() in STAKE_FORMS
                          else "other")}
                for f in all_filings]

    txns = []
    for f in all_filings:
        if f["form"] not in ("4", "4/A") or len(txns) >= max_form4 * 4:
            continue
        try:
            files = edgar.filing_files(cik, f["accession"])
        except Exception:
            continue
        xml = [x for x in files if x.lower().endswith(".xml")]
        if not xml:
            continue
        pick = next((x for x in xml if "primary_doc" in x.lower()), xml[0])
        try:
            for r in form4.parse(edgar.fetch_file(cik, f["accession"], pick)):
                r["filed"] = f["filed"]
                r["accession"] = f["accession"]
                txns.append(r)
        except Exception:
            continue

    last_own = next((t for t in timeline if t["kind"] == "ownership"), None)
    last_any = timeline[0] if timeline else None
    issuers = sorted({t["ticker"] for t in txns if t.get("ticker")})

    return {
        "cik": cik,
        "name": name or entity,
        "entity": entity,
        "note": note,
        "n_filings": len(all_filings),
        "last_filing": last_any,
        "last_ownership_filing": last_own,
        "timeline": timeline[:14],
        "transactions": txns[:max_form4 * 4],
        "issuers": issuers,
        "profile_url": f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK={cik}&type=&dateb=&owner=include&count=40",
    }


def collect(watchlist=None, max_form4=12):
    out = []
    for p in (watchlist or WATCHLIST):
        try:
            out.append(profile(p["cik"], p.get("name"), p.get("note"), max_form4))
        except Exception as e:
            out.append({"cik": p["cik"], "name": p.get("name"), "error": str(e)})
    return out
