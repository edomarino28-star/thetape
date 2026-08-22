"""Congressional trading disclosures (STOCK Act).

House: the Clerk publishes a yearly ZIP index of every financial disclosure,
free and unauthenticated. Periodic Transaction Reports (filing type 'P') are
the trade filings. Each is a PDF; most are text-extractable.

Senate: efdsearch.senate.gov requires you to accept its terms-of-use form
before it returns results. That is a consent action, so this tool does not
click it for you -- see README.

PTR table layout, as rendered by pdfplumber:

    SP Airbnb, Inc. - Class A Common Stock S 12/16/2025 08/13/2026 $1,001 - $15,000
    (ABNB) [ST]
    Filing Status: New
    Subholding Of: Trust - KF19

  - leading SP / DC / JT is the OWNER column (spouse / dependent child / joint)
  - transaction type S / P / E, optionally "(partial)"
  - two dates: transaction date, then notification date
  - amount bracket, which may wrap onto the next line
  - the asset name may wrap, carrying the (TICKER) and [asset-type] with it
"""
import io
import re
import zipfile
import datetime as dt
from . import http

HOUSE_ZIP = "https://disclosures-clerk.house.gov/public_disc/financial-pdfs/{year}FD.ZIP"
HOUSE_PTR = "https://disclosures-clerk.house.gov/public_disc/ptr-pdfs/{year}/{doc}.pdf"

FILING_TYPES = {"P": "PeriodicTransactionReport", "C": "Candidate", "A": "Annual",
                "D": "Due", "W": "Withdrawal", "X": "Extension", "H": "Hearing",
                "T": "Termination", "O": "Other"}

OWNER_CODES = {"SP": "spouse", "DC": "dependent_child", "JT": "joint"}
TYPE_NAMES = {"P": "purchase", "S": "sale", "E": "exchange"}

# The spine of a transaction row: type code, then two dates.
TXN_RE = re.compile(
    r"(?P<type>[SPE])(?:\s*\((?:partial|full)\))?\s+"
    r"(?P<date>\d{2}/\d{2}/\d{4})\s+(?P<notified>\d{2}/\d{2}/\d{4})\s*(?P<tail>.*)$")
TICKER_RE = re.compile(r"\(([A-Z][A-Z0-9.\-]{0,6})\)\s*(?=\[|$)")
ASSET_TYPE_RE = re.compile(r"\[([A-Z]{2})\]")
MONEY_RE = re.compile(r"\$([\d,]+)")
# "Filing Status:", "Subholding Of:", "Location:", "Description:" -- the PDF
# renders these in small caps, which pdfplumber emits as NUL-padded junk
# ("F<NUL x5> S<NUL x5>: New"). We NUL->space first, then match.
META_RE = re.compile(r"^[A-Za-z][A-Za-z\s]{0,28}:")
TRAILING_MONEY_RE = re.compile(r"(?:Over\s*)?\$[\d,]+(?:\s*-\s*(?:\$[\d,]+)?)?\s*$")


def house_index(year=None):
    """Every House financial disclosure filed in `year`."""
    year = year or dt.date.today().year
    raw = http.get(HOUSE_ZIP.format(year=year)).content
    z = zipfile.ZipFile(io.BytesIO(raw))
    lines = z.read(f"{year}FD.txt").decode("utf-8", "replace").splitlines()
    cols = lines[0].split("\t")
    out = []
    for line in lines[1:]:
        if not line.strip():
            continue
        parts = line.split("\t")
        if len(parts) < len(cols):
            continue
        rec = dict(zip(cols, parts))
        rec["Year"] = year
        rec["kind"] = FILING_TYPES.get(rec.get("FilingType", ""), rec.get("FilingType"))
        out.append(rec)
    return out


def house_ptrs(year=None, since=None):
    """Only the Periodic Transaction Reports -- the actual trades."""
    rows = [r for r in house_index(year) if r.get("FilingType") == "P"]
    for r in rows:
        try:
            r["filed_date"] = dt.datetime.strptime(r["FilingDate"], "%m/%d/%Y").date()
        except ValueError:
            r["filed_date"] = None
    if since:
        rows = [r for r in rows if r["filed_date"] and r["filed_date"] >= since]
    rows.sort(key=lambda r: r["filed_date"] or dt.date.min, reverse=True)
    return rows


def ptr_url(rec):
    return HOUSE_PTR.format(year=rec["Year"], doc=rec["DocID"])


def _parse_amount(text):
    """'$1,001 - $15,000' | '$250,001 - / $500,000' | 'Over $1,000,000'."""
    nums = [int(n.replace(",", "")) for n in MONEY_RE.findall(text)]
    if not nums:
        return None, None
    if len(nums) >= 2:
        return nums[0], nums[1]
    return (nums[0], None) if "over" in text.lower() else (nums[0], nums[0])


def _clean_asset(text):
    text = ASSET_TYPE_RE.sub("", text)
    text = re.sub(r"\([A-Z][A-Z0-9.\-]{0,6}\)\s*$", "", text)
    return re.sub(r"\s+", " ", text).strip(" .,-")


def parse_text(body, member=None, rec=None):
    """Parse the extracted text of one PTR into transaction rows."""
    rec = rec or {}
    body = body.replace(chr(0), " ")
    lines = [ln.rstrip() for ln in body.splitlines()]
    rows = []

    for i, line in enumerate(lines):
        m = TXN_RE.search(line)
        if not m:
            continue
        head = line[:m.start()].strip()
        if not head or head.lower().startswith(("type", "id owner")):
            continue

        owner = ""
        first, _, remainder = head.partition(" ")
        if first in OWNER_CODES:
            owner = OWNER_CODES[first]
            head = remainder.strip()

        amount_raw = m.group("tail").strip()
        head_money = TRAILING_MONEY_RE.search(head)
        if head_money:
            amount_raw += " " + head_money.group(0)
            head = head[:head_money.start()].strip()
        asset_parts = [head]

        # Pull in wrapped continuation lines. A continuation can carry the rest
        # of the asset name, the (TICKER) [TYPE], a wrapped amount, or all three.
        for nxt in lines[i + 1:i + 3]:
            frag = nxt.strip()
            if not frag or META_RE.match(frag) or TXN_RE.search(frag):
                break
            money = TRAILING_MONEY_RE.search(frag)
            if money:
                amount_raw += " " + money.group(0)
                frag = frag[:money.start()].strip()
            if frag:
                asset_parts.append(frag)

        joined = " ".join(asset_parts)
        tick = TICKER_RE.search(joined)
        atype = ASSET_TYPE_RE.search(joined)
        low, high = _parse_amount(amount_raw)

        rows.append({
            "member": member,
            "state_dist": rec.get("StateDst"),
            "doc_id": rec.get("DocID"),
            "filed": rec.get("FilingDate"),
            "owner": owner or "self",
            "asset": _clean_asset(joined),
            "ticker": tick.group(1) if tick else None,
            "asset_type": atype.group(1) if atype else None,
            "type": TYPE_NAMES.get(m.group("type"), m.group("type")),
            "partial": "partial" in line.lower(),
            "date": m.group("date"),
            "notified": m.group("notified"),
            "amount_low": low,
            "amount_high": high,
            "url": ptr_url(rec) if rec else None,
        })
    return rows


def parse_ptr(rec):
    """Download and parse one PTR PDF. Returns (rows, raw_text)."""
    import pdfplumber
    raw = http.get(ptr_url(rec)).content
    with pdfplumber.open(io.BytesIO(raw)) as pdf:
        body = "\n".join(page.extract_text() or "" for page in pdf.pages)
    if len(body.strip()) < 50:
        return [], body                      # scanned image -- would need OCR
    member = f"{rec.get('First', '')} {rec.get('Last', '')}".strip()
    return parse_text(body, member=member, rec=rec), body
