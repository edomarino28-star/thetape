# The Tape

> Reading the tape: public trading disclosures, ranked and dated.

Pulls the disclosure filings that institutions, corporate insiders, and members of
Congress are **legally required to publish**, and ranks them by how unusual they are.

Everything here comes from free, public, unauthenticated government sources. No
scraping of paywalled aggregators, no login, no terms-of-use to click through.

```bash
pip install requests pandas lxml pdfplumber
```

Run from `C:\Users\edoma\smart-money`:

```bash
python sm.py --help
```

---

## What each source actually gives you

| Source | Who files | Reporting lag | What you see | What you DON'T see |
|---|---|---|---|---|
| **Form 4** (§16) | Officers, directors, >10% holders | **2 business days** | Exact shares, exact price, exact date | Anyone below officer level |
| **13F-HR** | Managers with >$100M in US equities | **45 days after quarter end** | Long US-listed equity positions | Shorts, cash, bonds, non-US, intra-quarter round trips |
| **13D / 13G** | Anyone crossing 5% of a company | 5 days (13D) / annual-ish (13G) | Activist stakes and intent | Sub-5% positions |
| **House PTR** (STOCK Act) | Representatives | **up to 45 days** | Ticker, buy/sell, date, amount *bracket* | Exact dollar amounts (brackets only) |

The lag column is the whole story. **Form 4 is the only one of these that is
close to real time.** 13F is a photograph of a portfolio that may be four and a
half months old — Berkshire's Q2 filing lands in mid-August. Congressional PTRs
are frequently filed at the 45-day deadline, and the late-filing penalty is $200.

---

## The dashboard

```bash
python sm.py dashboard
```

Downloads everything, builds `out/dashboard.html`, and opens it in your browser.
One self-contained file -- no server, no internet needed to view it afterwards.
Works on your phone if you send yourself the file.

It is organized by **how stale each source is**, because that is the fact that
decides whether a filing is worth anything. Charts have hover tooltips; light and
dark themes both included.

```bash
python sm.py dashboard --days 30 --max 1200      # wider insider window
python sm.py dashboard --no-refresh              # re-render without re-downloading
python sm.py dashboard --fund 1067983 --fund 1350694   # pick your own funds by CIK
```

Every build also refreshes a **The Tape** shortcut on your Desktop, with a
generated icon (`smartmoney/the-tape.ico` -- three delay bars, short-green
to long-red, the same idea the page opens with). Double-click it to open the
latest build in your browser. Rebuild the icon alone with
`python -m smartmoney.makeicon`, or re-point the shortcut with
`python -m smartmoney.shortcut`.

A full refresh takes a few minutes -- it is rate-limited to 4 requests/second out
of respect for SEC's servers, and congressional PDFs are downloaded one at a time.
Use `--no-refresh` while you are tweaking anything visual.

## Commands

### `insiders` — Form 4, near-real-time

```bash
python sm.py insiders --days 7 --max 500
python sm.py insiders --ticker NVDA --days 90
```

Ranks two things:

- **Cluster buys** — several insiders buying on the open market (code `P`) at the
  same company within the window. This is the single filing pattern with the most
  supporting academic evidence (Lakonishok & Lee 2001; Cohen, Malloy & Pomorski
  2012, who separate "routine" from "opportunistic" insiders).
- **Unplanned large sells** — big sales *not* executed under a Rule 10b5-1 plan.
  Most executive selling is pre-scheduled diversification and means nothing; a
  large discretionary sale is the rarer signal. Tranches from one decision are
  collapsed, and `% of stake` shows how much of the position went out the door.

Transaction codes the parser keeps straight: `P` open-market buy, `S`
open-market sale, `A` grant, `M` option exercise, `F` shares withheld for tax,
`G` gift. Screens that count `A` as "insider buying" are noise.

### `find` — resolve a name to an EDGAR CIK

```bash
python sm.py find "pershing square"
python sm.py find "Burry"
python sm.py find "icahn" --form SC 13D
```

Searches actual filings rather than a hardcoded list, so it stays correct when
entities rename or re-register.

### `holdings` / `moves` — 13F

```bash
python sm.py holdings 1067983
python sm.py holdings "pershing square"
python sm.py moves "scion asset"        # quarter-over-quarter NEW / ADD / TRIM / EXIT
```

`moves` is the useful one — a static holdings list tells you nothing about
intent. Positions are keyed by CUSIP, so share classes (GOOG vs GOOGL) stay
separate rather than silently merging.

### `congress` — House periodic transaction reports

```bash
python sm.py congress --days 30 --max 40
python sm.py congress --days 90 --max 200 --all-assets
```

Downloads the Clerk's yearly disclosure index, filters to Periodic Transaction
Reports, fetches each PDF, and parses the transaction table. Defaults to listed
equities; `--all-assets` includes municipal bonds, treasuries, CDs, and funds
(which are the bulk of the volume and rarely interesting).

A small share of PTRs are scanned images with no text layer. Those are reported
as "yielded no text" and skipped rather than silently dropped. Adding OCR
(tesseract) would recover them.

**Senate is not implemented.** `efdsearch.senate.gov` requires accepting a
terms-of-use form before it returns results. That is a consent action, so this
tool does not click it for you. If you want Senate coverage, go to the site,
accept the terms yourself, and either export manually or add your own session
handling.

---

## Output

CSVs land in `out/`:

- `insider_transactions.csv` — every parsed Form 4 line
- `insider_clusters.csv` — ranked cluster buys
- `congress_transactions.csv` / `congress_by_ticker.csv`
- `holdings_<cik>_<period>.csv`, `moves_<cik>_<period>.csv`

Load into pandas, Excel, or feed into whatever you already run.

---

## Rate limits and etiquette

`smartmoney/http.py` throttles to 4 requests/second (SEC's published ceiling is
10/s) and sends a User-Agent with a contact address, as SEC requires. Don't raise
it — EDGAR will block the IP, and the block is not instant to lift. Retries use
exponential backoff on 429/503.

---

## Honest limitations

- **13F is stale and incomplete by construction.** It is a long-equity snapshot
  with a 45-day lag. A manager can buy and fully exit inside a quarter and you
  will never see it. Options show as notional, not delta. Nothing about leverage,
  shorts, or hedges is disclosed. Copying a 13F is copying a four-month-old
  photograph of one leg of a position.
- **Congressional trades are amount-bracketed, often late, and mostly boring.**
  The bulk of disclosed volume is index funds, treasuries, and advisor-managed
  accounts the member does not direct. Several members disclose exactly that in
  the comments field.
- **The insider-buying edge is documented but small, slow, and concentrated in
  small caps.** The published effect sizes are on long horizons and diversified
  baskets, not on single names over weeks.
- **This tool ranks filings by unusualness. It does not forecast prices, and it
  is not investment advice.** No backtest ships with it. If you intend to trade
  on any of this, backtest it yourself on data that existed at the time — which
  means indexing by *filing* date, never by *transaction* date. Indexing by
  transaction date is lookahead bias and will make any strategy look excellent.

## Legal note

Trading on public disclosures is legal — that is what disclosure is for. What is
illegal is trading on material non-public information obtained in breach of a
duty. Everything this tool reads was published by the filer to the whole world.
