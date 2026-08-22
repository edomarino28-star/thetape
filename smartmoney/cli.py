import argparse, csv, datetime as dt, os, sys
from . import dashboard, edgar, form4, thirteenf, congress, score

OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "out")


def _save(name, rows):
    if not rows:
        return None
    os.makedirs(OUT, exist_ok=True)
    path = os.path.join(OUT, name)
    keys, seen = [], set()
    for r in rows:
        for k in r:
            if k not in seen:
                seen.add(k)
                keys.append(k)
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=keys, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow({k: (",".join(map(str, v)) if isinstance(v, (list, set)) else v)
                        for k, v in r.items()})
    return path


def _money(v):
    if v is None:
        return "-"
    for unit, div in (("B", 1e9), ("M", 1e6), ("K", 1e3)):
        if abs(v) >= div:
            return f"${v/div:,.1f}{unit}"
    return f"${v:,.0f}"


def _window(args):
    end = dt.date.fromisoformat(args.end) if args.end else dt.date.today()
    start = (dt.date.fromisoformat(args.start) if args.start
             else end - dt.timedelta(days=args.days))
    return start.isoformat(), end.isoformat()


def _resolve_cik(value):
    if str(value).isdigit():
        return int(value)
    hits = edgar.find_filer(str(value))
    if not hits:
        raise SystemExit(f"no 13F filer matches {value!r}  (try: sm find \"{value}\")")
    print(f"resolved to CIK {hits[0]['cik']} ({hits[0]['name']})", file=sys.stderr)
    return hits[0]["cik"]


# ---------------------------------------------------------------- commands
def cmd_insiders(args):
    start, end = _window(args)
    scope = f" for {args.ticker.upper()}" if args.ticker else ""
    print(f"Form 4 filings {start} -> {end}{scope} ...", file=sys.stderr)
    rows = form4.recent(start, end, ticker=args.ticker, max_filings=args.max)
    print(f"{len(rows)} transactions parsed\n", file=sys.stderr)

    clusters = score.cluster_buys(rows, min_insiders=args.min_insiders,
                                  min_value=args.min_value)
    print(f"=== CLUSTER BUYS ({len(clusters)}) "
          f"[>={args.min_insiders} insiders buying on the open market] ===")
    for c in clusters[:args.top]:
        flag = "  (all 10b5-1 pre-planned)" if c["all_10b5_1"] else ""
        issuer = (c["issuer"] or "")[:34]
        print(f"{c['ticker']:<7} {issuer:<34} {c['insiders']} insiders  "
              f"{_money(c['total_value']):>9}  score {c['score']:>7}{flag}")
        titles = ", ".join(t[:40] for t in c["titles"])[:100]
        print(f"        {titles}")

    sells = score.notable_sells(rows, min_value=args.min_sell)
    print(f"\n=== UNPLANNED LARGE SELLS (>{_money(args.min_sell)}, "
          f"not on a 10b5-1 plan) ===")
    for s in sells[:args.top]:
        tick = s["ticker"] or "?"
        owner = (s["owner"] or "")[:24]
        title = (s["title"] or ("Director" if s["is_director"] else ""))[:26]
        stake = f"{s['pct_of_stake']:.0f}% of stake" if s["pct_of_stake"] else ""
        print(f"{tick:<7} {owner:<24} {_money(s['value']):>9}  {s['date']}  "
              f"{stake:<14} {title}")

    for name, data in (("insider_transactions.csv", rows),
                       ("insider_clusters.csv", clusters)):
        path = _save(name, data)
        if path:
            print(f"\nwrote {path}", file=sys.stderr)


def cmd_find(args):
    hits = edgar.find_filer(args.name, form=args.form)
    if not hits:
        print(f"nothing filed {args.form} under a name like {args.name!r}")
    for r in hits:
        print(f"{r['cik']:>10}  {r['name']}")


def cmd_holdings(args):
    cik = _resolve_cik(args.cik)
    snaps = thirteenf.holdings(cik, n=1)
    if not snaps:
        raise SystemExit("no 13F-HR found for that CIK")
    meta, rows = snaps[0]["meta"], snaps[0]["rows"]
    total = sum(r["value"] for r in rows) or 1
    print(f"{meta['entity']}  |  period {meta['period']}  filed {meta['filed']}  |  "
          f"{len(rows)} positions  {_money(total)}")
    print(f"  {'ISSUER':<38} {'CUSIP':<10} {'VALUE':>10} {'%PORT':>7} {'SHARES':>14}")
    for r in sorted(rows, key=lambda r: -r["value"])[:args.top]:
        pc = " " + r["put_call"] if r["put_call"] else ""
        label = (r["issuer"] or "")[:36] + pc
        print(f"  {label:<38} {r['cusip']:<10} {_money(r['value']):>10} "
              f"{r['value']/total*100:>6.2f}% {r['shares']:>14,.0f}")
    _save(f"holdings_{cik}_{meta['period']}.csv", rows)


def cmd_moves(args):
    cik = _resolve_cik(args.cik)
    d = thirteenf.delta(cik)
    print(f"{d['cur']['entity']}  {d['prev']['period']} -> {d['cur']['period']}  "
          f"(filed {d['cur']['filed']})   portfolio {_money(d['total_value'])}")
    for action in ("NEW", "ADD", "TRIM", "EXIT"):
        sel = [m for m in d["moves"] if m["action"] == action]
        if action in ("NEW", "ADD"):
            sel.sort(key=lambda m: -(m["value"] or 0))
        else:
            sel.sort(key=lambda m: -(m["prev_shares"] or 0))
        print(f"\n--- {action} ({len(sel)}) ---")
        for m in sel[:args.top]:
            pct = f"{m['pct_shares']:+.0f}%" if m["pct_shares"] is not None else ""
            pc = " " + m["put_call"] if m["put_call"] else ""
            label = (m["issuer"] or "")[:36] + pc
            print(f"  {label:<38} {m['cusip']:<10} {_money(m['value']):>10} "
                  f"{m['pct_portfolio']:>6.2f}%  {m['d_shares']:>+14,.0f} sh {pct:>7}")
    _save(f"moves_{cik}_{d['cur']['period']}.csv", d["moves"])


def cmd_congress(args):
    since = dt.date.today() - dt.timedelta(days=args.days)
    year = args.year or dt.date.today().year
    ptrs = congress.house_ptrs(year=year, since=since)
    print(f"{len(ptrs)} House PTRs filed since {since} (year {year})", file=sys.stderr)
    ptrs = ptrs[:args.max]

    rows, unparsed = [], 0
    for i, rec in enumerate(ptrs, 1):
        print(f"  [{i}/{len(ptrs)}] {rec['First']} {rec['Last']} {rec['FilingDate']}",
              file=sys.stderr)
        try:
            got, _ = congress.parse_ptr(rec)
        except Exception as e:
            print(f"    ! {e}", file=sys.stderr)
            continue
        if not got:
            unparsed += 1
        rows.extend(got)

    print(f"\n{len(rows)} transactions parsed ({unparsed} PDFs yielded no text - "
          f"likely scanned images)\n", file=sys.stderr)
    agg = score.summarize_congress(rows, equities_only=not args.all_assets)
    print(f"{'TICKER':<8} {'B':>3} {'S':>3} {'MEM':>4} {'NOTIONAL RANGE':>24}  MEMBERS")
    for a in agg[:args.top]:
        rng = f"{_money(a['min_notional'])} - {_money(a['max_notional'])}"
        tick = (a["ticker"] or "?")[:8]
        names = ", ".join(a["names"])[:50]
        print(f"{tick:<8} {a['buys']:>3} {a['sells']:>3} {a['members']:>4} "
              f"{rng:>24}  {names}")
    _save("congress_transactions.csv", rows)
    _save("congress_by_ticker.csv", agg)
    print(f"\nwrote {OUT}", file=sys.stderr)


def cmd_dashboard(args):
    dashboard.build(days=args.days, max_filings=args.max,
                    congress_days=args.congress_days, max_ptrs=args.max_ptrs,
                    funds=args.fund or ("1067983", "1336528", "1649339"),
                    refresh=not args.no_refresh, open_browser=not args.no_open)


def main(argv=None):
    p = argparse.ArgumentParser(prog="sm", description="Public disclosure tracker")
    sub = p.add_subparsers(dest="cmd", required=True)

    a = sub.add_parser("insiders", help="Form 4 insider trades + cluster-buy ranking")
    a.add_argument("--ticker")
    a.add_argument("--days", type=int, default=7)
    a.add_argument("--start")
    a.add_argument("--end")
    a.add_argument("--max", type=int, default=300, help="max filings to pull")
    a.add_argument("--min-insiders", type=int, default=2)
    a.add_argument("--min-value", type=float, default=25_000)
    a.add_argument("--min-sell", type=float, default=1_000_000)
    a.add_argument("--top", type=int, default=25)
    a.set_defaults(fn=cmd_insiders)

    a = sub.add_parser("find", help="resolve a fund/person name to an EDGAR CIK")
    a.add_argument("name")
    a.add_argument("--form", default="13F-HR")
    a.set_defaults(fn=cmd_find)

    a = sub.add_parser("holdings", help="latest 13F portfolio")
    a.add_argument("cik", help="CIK number or fund name")
    a.add_argument("--top", type=int, default=30)
    a.set_defaults(fn=cmd_holdings)

    a = sub.add_parser("moves", help="quarter-over-quarter 13F changes")
    a.add_argument("cik", help="CIK number or fund name")
    a.add_argument("--top", type=int, default=15)
    a.set_defaults(fn=cmd_moves)

    a = sub.add_parser("congress", help="House periodic transaction reports")
    a.add_argument("--days", type=int, default=30)
    a.add_argument("--year", type=int)
    a.add_argument("--max", type=int, default=40, help="max PDFs to download")
    a.add_argument("--top", type=int, default=30)
    a.add_argument("--all-assets", action="store_true",
                   help="include bonds, funds, CDs -- default is listed equities only")
    a.set_defaults(fn=cmd_congress)

    a = sub.add_parser("dashboard", help="build the visual HTML dashboard and open it")
    a.add_argument("--days", type=int, default=14, help="insider lookback")
    a.add_argument("--max", type=int, default=600, help="max Form 4 filings")
    a.add_argument("--congress-days", type=int, default=60)
    a.add_argument("--max-ptrs", type=int, default=60, help="max congress PDFs")
    a.add_argument("--fund", action="append",
                   help="13F filer CIK to include (repeatable)")
    a.add_argument("--no-refresh", action="store_true",
                   help="re-render from the last download instead of fetching")
    a.add_argument("--no-open", action="store_true")
    a.set_defaults(fn=cmd_dashboard)

    args = p.parse_args(argv)
    return args.fn(args)
