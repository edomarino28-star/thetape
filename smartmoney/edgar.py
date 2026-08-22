"""EDGAR primitives: entity lookup, full-text search, filing file access."""
import functools, re
from . import http

FTS = "https://efts.sec.gov/LATEST/search-index"
SUBS = "https://data.sec.gov/submissions/CIK{cik:010d}.json"
ARCH = "https://www.sec.gov/Archives/edgar/data/{cik}/{acc_nodash}"


def _cik_int(cik):
    return int(str(cik).lstrip("CIK").lstrip("0") or 0)


@functools.lru_cache(maxsize=1)
def ticker_map():
    """ticker -> (cik, name)"""
    j = http.get_json("https://www.sec.gov/files/company_tickers.json")
    return {v["ticker"].upper(): (v["cik_str"], v["title"]) for v in j.values()}


def resolve_ticker(ticker):
    return ticker_map().get(ticker.upper())


def find_filer(name, form="13F-HR", limit=10):
    """Resolve a fund/person name to CIKs by searching their actual filings."""
    j = http.get_json(FTS, params={"q": "", "forms": form, "entityName": name})
    seen, out = set(), []
    for h in j.get("hits", {}).get("hits", []):
        for disp in h["_source"].get("display_names", []):
            m = re.search(r"\(CIK (\d{10})\)", disp)
            if not m:
                continue
            cik = _cik_int(m.group(1))
            if cik in seen:
                continue
            seen.add(cik)
            out.append({"cik": cik, "name": disp.split("  (CIK")[0].strip()})
            if len(out) >= limit:
                return out
    return out


def submissions(cik):
    return http.get_json(SUBS.format(cik=_cik_int(cik)))


def filings(cik, forms=None, limit=None):
    """Flatten the 'recent' filings block into dicts. forms = set of form types."""
    j = submissions(cik)
    rec = j["filings"]["recent"]
    out = []
    for i, form in enumerate(rec["form"]):
        if forms and form not in forms:
            continue
        out.append({
            "cik": _cik_int(cik),
            "entity": j.get("name"),
            "form": form,
            "accession": rec["accessionNumber"][i],
            "filed": rec["filingDate"][i],
            "period": rec["reportDate"][i],
            "primary_doc": rec["primaryDocument"][i],
        })
        if limit and len(out) >= limit:
            break
    return out


def filing_files(cik, accession):
    nod = accession.replace("-", "")
    url = f"{ARCH.format(cik=_cik_int(cik), acc_nodash=nod)}/index.json"
    j = http.get_json(url)
    return [it["name"] for it in j["directory"]["item"]]


def file_url(cik, accession, filename):
    nod = accession.replace("-", "")
    return f"{ARCH.format(cik=_cik_int(cik), acc_nodash=nod)}/{filename}"


def fetch_file(cik, accession, filename):
    return http.get(file_url(cik, accession, filename)).content


def search_filings(forms, start, end, size=100, offset=0, q="", entity=None):
    """EDGAR full-text search. Returns raw hits, each with accession + document name."""
    params = {"q": q, "forms": forms, "dateRange": "custom",
              "startdt": start, "enddt": end, "from": offset, "size": size}
    if entity:
        params["entityName"] = entity
    j = http.get_json(FTS, params=params)
    hits = j.get("hits", {})
    out = []
    for h in hits.get("hits", []):
        acc, _, doc = h["_id"].partition(":")
        s = h["_source"]
        out.append({
            "accession": acc,
            "document": doc,
            "form": s.get("form"),
            "filed": s.get("file_date"),
            "period": s.get("period_ending"),
            "ciks": [_cik_int(c) for c in s.get("ciks", [])],
            "names": s.get("display_names", []),
            "items": s.get("items", []),
        })
    return out, hits.get("total", {}).get("value", 0)
