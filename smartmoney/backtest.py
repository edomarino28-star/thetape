"""Event-study backtester for insider cluster buys.

THE RULES THAT MAKE OR BREAK THIS
---------------------------------
1. Signals are stamped with the FILING date, never the trade date. An insider
   who bought on the 1st and filed on the 3rd was not knowable on the 1st.
   Indexing by trade date is lookahead bias and makes almost any strategy look
   brilliant. This is the single most common backtest bug.

2. Entry is the NEXT session's open after the filing. Not the same day's close.

3. Intrabar ambiguity: if one daily bar's high touches the take-profit AND its
   low touches the stop, daily data cannot say which happened first. We assume
   the STOP filled first. That is pessimistic on purpose -- assuming the target
   filled first is the second most common way to fake a good result.

4. Gaps fill at the open. If the stock opens below the stop, you are out at the
   open price, not at the stop level.

5. Every trade is also run on SPY over the identical dates, so the report shows
   excess return. A strategy that makes 8% while the market made 9% lost.

6. Costs are charged both ways. Default 5 basis points per side is optimistic
   for small caps; raise it.

WHAT THIS CANNOT TELL YOU
-------------------------
Companies that were delisted or acquired mostly vanish from the price source, so
the surviving sample is biased upward. And sweeping a grid of parameters
guarantees one cell looks good by luck -- `sweep()` reports how many were tried
so the winner can be discounted accordingly.
"""
import datetime as dt
import json
import math
import os
import random
import statistics
from collections import defaultdict

from . import edgar, form4, prices, score

OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "out")
SIGNALS = os.path.join(OUT, "signals.json")


# ------------------------------------------------------------------ signals
def harvest(start, end, universe=150, seed=7, min_insiders=2, min_value=25_000,
            max_per_company=140, log=print):
    """Find historical insider cluster buys across a random company sample.

    The sample is random, not hand-picked, so the test is not run on the same
    names that inspired it.
    """
    tmap = edgar.ticker_map()
    items = sorted(tmap.items())
    random.Random(seed).shuffle(items)
    picked = items[:universe]
    log(f"universe: {len(picked)} companies, {start} -> {end}")

    signals, done = [], 0
    for ticker, (cik, name) in picked:
        done += 1
        try:
            fs = [f for f in edgar.filings(cik, forms={"4"}, limit=max_per_company)
                  if start.isoformat() <= f["filed"] <= end.isoformat()]
        except Exception as e:
            log(f"  ! {ticker}: {e}")
            continue
        if not fs:
            continue

        rows = []
        for f in fs:
            # submissions gives the XSL-rendered path ("xslF345X06/form4.xml");
            # the bare filename is the raw XML, so we skip the index lookup and
            # halve the request count.
            doc = (f.get("primary_doc") or "").split("/")[-1]
            if not doc.lower().endswith(".xml"):
                continue
            try:
                for r in form4.parse(edgar.fetch_file(cik, f["accession"], doc)):
                    r["filed"] = f["filed"]
                    rows.append(r)
            except Exception:
                continue

        # cluster within each filing date's trailing week
        by_week = defaultdict(list)
        for r in rows:
            if r.get("filed"):
                by_week[r["filed"]].append(r)
        for filed, group in by_week.items():
            window = [r for r in rows
                      if r.get("filed") and
                      0 <= (dt.date.fromisoformat(filed)
                            - dt.date.fromisoformat(r["filed"])).days <= 6]
            for c in score.cluster_buys(window, min_insiders=min_insiders,
                                        min_value=min_value):
                signals.append({"ticker": ticker, "issuer": name, "cik": cik,
                                "filed": filed, "insiders": c["insiders"],
                                "value": c["total_value"], "score": c["score"]})
        if done % 20 == 0:
            log(f"  {done}/{len(picked)} companies, {len(signals)} signals")

    # one signal per ticker per filing date
    seen, unique = set(), []
    for s in sorted(signals, key=lambda s: (s["filed"], s["ticker"])):
        k = (s["ticker"], s["filed"])
        if k in seen:
            continue
        seen.add(k)
        unique.append(s)

    os.makedirs(OUT, exist_ok=True)
    with open(SIGNALS, "w", encoding="utf-8") as fh:
        json.dump({"start": start.isoformat(), "end": end.isoformat(),
                   "universe": universe, "seed": seed, "signals": unique}, fh, indent=1)
    log(f"{len(unique)} unique signals -> {SIGNALS}")
    return unique


def load_signals():
    with open(SIGNALS, encoding="utf-8") as fh:
        return json.load(fh)


# ------------------------------------------------------------------ one trade
def simulate(bars, filed, tp_pct, sl_pct, max_days):
    """Walk one trade forward bar by bar. Returns None if it cannot be entered."""
    i, entry_bar = prices.next_session(bars, filed)
    if entry_bar is None or i is None:
        return None
    entry = entry_bar["open"]
    if not entry or entry <= 0:
        return None

    tp = entry * (1 + tp_pct / 100.0)
    sl = entry * (1 - sl_pct / 100.0)

    for held, bar in enumerate(bars[i:i + max_days], start=0):
        # a gap through either level fills at the open
        if bar["open"] <= sl:
            return _close(entry, bar["open"], entry_bar, bar, held, "stop_gap")
        if bar["open"] >= tp:
            return _close(entry, bar["open"], entry_bar, bar, held, "target_gap")
        hit_sl = bar["low"] <= sl
        hit_tp = bar["high"] >= tp
        if hit_sl:                      # pessimistic: stop wins any tie
            return _close(entry, sl, entry_bar, bar, held, "stop")
        if hit_tp:
            return _close(entry, tp, entry_bar, bar, held, "target")

    tail = bars[i:i + max_days]
    if not tail:
        return None
    last = tail[-1]
    return _close(entry, last["close"], entry_bar, last, len(tail) - 1, "timeout")


def _close(entry, exit_px, entry_bar, exit_bar, held, reason):
    return {"entry_date": entry_bar["date"], "entry": entry,
            "exit_date": exit_bar["date"], "exit": exit_px,
            "held_days": held, "reason": reason,
            "ret_pct": (exit_px / entry - 1) * 100}


# ------------------------------------------------------------------ the run
def dedupe(sigs, cooldown_days=30):
    """Collapse repeat signals on the same name inside a cooldown window.

    A cluster of insiders filing on three consecutive days is ONE event, not
    three. Counting it three times inflates the sample size and makes the
    significance test claim far more confidence than the data supports -- the
    trades overlap in time, so they are not independent draws.
    """
    kept, last = [], {}
    for s in sorted(sigs, key=lambda s: (s["ticker"], s["filed"])):
        d = dt.date.fromisoformat(s["filed"])
        prev = last.get(s["ticker"])
        if prev and (d - prev).days < cooldown_days:
            continue
        last[s["ticker"]] = d
        kept.append(s)
    return sorted(kept, key=lambda s: s["filed"])


def run(tp_pct=10.0, sl_pct=6.0, max_days=40, cost_bps=5.0, signals=None,
        benchmark="SPY", cooldown_days=30, log=print):
    blob = signals or load_signals()
    sigs = blob["signals"] if isinstance(blob, dict) else blob
    raw_n = len(sigs)
    sigs = dedupe(sigs, cooldown_days)
    if raw_n != len(sigs):
        log(f"deduped {raw_n} -> {len(sigs)} independent signals "
            f"({cooldown_days}-day cooldown per name)")
    start = dt.date.fromisoformat(blob["start"]) - dt.timedelta(days=5) \
        if isinstance(blob, dict) else dt.date(2023, 1, 1)
    end = dt.date.today()

    bench_bars = prices.history(benchmark, start, end)
    bench_ix = prices.index_by_date(bench_bars)

    trades, skipped = [], 0
    for s in sigs:
        bars = prices.history(s["ticker"], start, end)
        if len(bars) < 30:
            skipped += 1
            continue
        t = simulate(bars, s["filed"], tp_pct, sl_pct, max_days)
        if not t:
            skipped += 1
            continue
        gross = t["ret_pct"]
        t["ret_pct"] = gross - (cost_bps / 100.0) * 2      # both sides
        t["ticker"] = s["ticker"]
        t["issuer"] = s.get("issuer")
        t["filed"] = s["filed"]
        t["insiders"] = s.get("insiders")

        # same dates, on the index
        be, bx = bench_ix.get(t["entry_date"]), bench_ix.get(t["exit_date"])
        t["bench_pct"] = ((bx["close"] / be["open"] - 1) * 100
                          if be and bx and be["open"] else None)
        t["excess_pct"] = (t["ret_pct"] - t["bench_pct"]
                           if t["bench_pct"] is not None else None)
        trades.append(t)

    stats = summarize(trades, tp_pct, sl_pct, max_days, cost_bps)
    stats["signals"] = len(sigs)
    stats["skipped_no_price"] = skipped
    log(f"{len(trades)} trades from {len(sigs)} signals ({skipped} unpriceable)")
    return trades, stats


def summarize(trades, tp_pct=None, sl_pct=None, max_days=None, cost_bps=None):
    if not trades:
        return {"n": 0}
    rets = [t["ret_pct"] for t in trades]
    exc = [t["excess_pct"] for t in trades if t["excess_pct"] is not None]
    wins = [r for r in rets if r > 0]
    losses = [r for r in rets if r <= 0]

    equity, peak, dd = 100.0, 100.0, 0.0
    for t in sorted(trades, key=lambda t: t["entry_date"]):
        equity *= (1 + t["ret_pct"] / 100.0)
        peak = max(peak, equity)
        dd = min(dd, equity / peak - 1)

    reasons = defaultdict(int)
    for t in trades:
        reasons[t["reason"]] += 1

    return {
        "n": len(trades),
        "tp_pct": tp_pct, "sl_pct": sl_pct, "max_days": max_days,
        "cost_bps": cost_bps,
        "win_rate": len(wins) / len(rets) * 100,
        "avg_return": statistics.fmean(rets),
        "median_return": statistics.median(rets),
        "avg_win": statistics.fmean(wins) if wins else 0.0,
        "avg_loss": statistics.fmean(losses) if losses else 0.0,
        "expectancy": statistics.fmean(rets),
        "profit_factor": (sum(wins) / abs(sum(losses))) if losses and sum(losses) else None,
        "avg_excess": statistics.fmean(exc) if exc else None,
        "beat_market_pct": (sum(1 for e in exc if e > 0) / len(exc) * 100) if exc else None,
        "avg_hold_days": statistics.fmean([t["held_days"] for t in trades]),
        "final_equity": equity,
        "max_drawdown_pct": dd * 100,
        "exit_reasons": dict(reasons),
        "t_stat": _t_stat(exc if exc else rets),
        "p_value_approx": _p_value(_t_stat(exc if exc else rets)),
        "tested_on": "excess return vs benchmark" if exc else "raw return",
    }


def _t_stat(xs):
    """Is the mean distinguishable from zero, given this much noise?"""
    if len(xs) < 3:
        return None
    sd = statistics.stdev(xs)
    if sd == 0:
        return None
    return statistics.fmean(xs) / (sd / math.sqrt(len(xs)))


def _p_value(t):
    """Two-sided normal approximation. Fine at n>30; indicative below that."""
    if t is None:
        return None
    z = abs(t)
    return 2 * (1 - 0.5 * (1 + math.erf(z / math.sqrt(2))))


# ------------------------------------------------------------------ sweep
def sweep(tps=(5, 8, 10, 15, 20), sls=(3, 5, 8, 12), max_days=(20, 40, 60),
          cost_bps=5.0, log=print):
    """Grid search -- and a warning about what a grid search actually proves."""
    blob = load_signals()
    results = []
    for tp in tps:
        for sl in sls:
            for md in max_days:
                _, st = run(tp, sl, md, cost_bps, signals=blob, log=lambda *a: None)
                if st.get("n"):
                    results.append(st)
    results.sort(key=lambda s: -(s.get("avg_excess") or s.get("avg_return") or 0))
    tried = len(results)
    log(f"tried {tried} parameter combinations")
    log("NOTE: the best cell of a grid this size is expected to look good by "
        "chance alone. Treat its p-value as roughly p x " + str(tried) + ".")
    return results, tried


def placebo(tp_pct=10.0, sl_pct=6.0, max_days=40, cost_bps=5.0, runs=200,
            seed=11, log=print):
    """The control experiment.

    Take the same tickers and the same number of trades, but pick the entry
    dates at random. If the real signal cannot beat a coin flip on the same
    stocks, then the "edge" was never in the insider filing -- it was in which
    stocks happened to be in the sample.

    This is the check that separates a real effect from a story.
    """
    blob = load_signals()
    sigs = dedupe(blob["signals"])
    start = dt.date.fromisoformat(blob["start"]) - dt.timedelta(days=5)
    end = dt.date.today()

    series = {}
    for s in sigs:
        bars = prices.history(s["ticker"], start, end)
        if len(bars) >= 60:
            series[s["ticker"]] = bars
    if not series:
        return None

    rng = random.Random(seed)
    tickers = [s["ticker"] for s in sigs if s["ticker"] in series]
    means = []
    for _ in range(runs):
        rets = []
        for tk in tickers:
            bars = series[tk]
            j = rng.randrange(0, max(1, len(bars) - max_days - 2))
            t = simulate(bars, bars[j]["date"], tp_pct, sl_pct, max_days)
            if t:
                rets.append(t["ret_pct"] - (cost_bps / 100.0) * 2)
        if rets:
            means.append(statistics.fmean(rets))

    means.sort()
    real, _ = run(tp_pct, sl_pct, max_days, cost_bps, log=lambda *a: None)
    real_mean = statistics.fmean([t["ret_pct"] for t in real]) if real else 0.0
    better = sum(1 for m in means if m >= real_mean)
    return {
        "runs": len(means),
        "real_mean": real_mean,
        "placebo_mean": statistics.fmean(means),
        "placebo_p5": means[int(len(means) * 0.05)],
        "placebo_p95": means[int(len(means) * 0.95)],
        "percentile_of_real": (1 - better / len(means)) * 100,
        "empirical_p": better / len(means),
    }
