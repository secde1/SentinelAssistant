"""V21-2: 4 nomzod uchun walk-forward (2 yil o'qitish / 6 oy test, 6 oyga surilib), yillar va rejimlar, filtrlar, Sharpe,
ko'p sinov tuzatmasi (Holm). Parametrlar O'ZGARMAYDI; yangi strategiya yo'q; savdo yo'q — faqat tarixiy ma'lumot.

Halol cheklov: nomzodlar 5 yillik natijalarga qarab tanlangan, shuning uchun walk-forward oynalari haqiqiy "yangi ma'lumot"
EMAS (tanlash ularni ko'rgan). Haqiqiy tasdiq — faqat bundan keyingi (forward) ma'lumot.

Filtr qiymati: bazaviy savdolar signal paytidagi filtr bo'yicha "o'tgan" va "rad etilgan"ga bo'linadi; ikki guruh
expectancy farqi (Welch) va Holm tuzatilgan p. Filtr ishlatilsa savdolar oqimi biroz o'zgaradi — bu yerda hisobga olinmagan.
"""
from __future__ import annotations

import math
import pickle
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import costs  # noqa: E402
import lab  # noqa: E402
from agent.trading.indicators import ema, percentile_rank  # noqa: E402

L = lab.ROOT / "data" / "trading_memory" / "lab"
CANDS = [("XAUUSDm", "4h", "MA-CROSS"), ("USTECm", "1h", "TF-PULLBACK"), ("BTCUSDm", "1h", "TF-PULLBACK"),
         ("XAUUSDm", "1h", "VOL-BRK")]
HIGHER = {"1h": "4h", "4h": "1d"}
FAMILY_SELECTION = 98  # nomzodlar 98 kombinatsiya ichidan eng yaxshisi sifatida tanlangan
WF_START = datetime(2023, 11, 8, tzinfo=timezone.utc)  # 2021-11-08 + 2 yil
WINDOWS = [(datetime(2023 + (10 + 6 * k) // 12, (10 + 6 * k) % 12 + 1, 8, tzinfo=timezone.utc),
            datetime(2023 + (16 + 6 * k) // 12, (16 + 6 * k) % 12 + 1, 8, tzinfo=timezone.utc)) for k in range(6)]


def norm_p2(z: float) -> float:
    return math.erfc(abs(z) / math.sqrt(2))


def mean_sd(rs):
    n = len(rs)
    m = sum(rs) / n
    sd = math.sqrt(sum((r - m) ** 2 for r in rs) / (n - 1)) if n > 1 else float("nan")
    return m, sd


def full_stats(trs: list, years: float) -> dict:
    ex = lab.executed(trs)
    s = lab.stats(trs)
    rs = [t.r for t in ex]
    if len(rs) > 1:
        m, sd = mean_sd(rs)
        s["t"] = round(m / (sd / math.sqrt(len(rs))), 2) if sd else None
        s["p_one"] = norm_p2(m / (sd / math.sqrt(len(rs)))) / 2 if sd and m > 0 else 1.0
        s["sharpe_trade"] = round(m / sd, 3) if sd else None
        s["sharpe_ann"] = round(m / sd * math.sqrt(len(rs) / years), 2) if sd else None
    return s


def holm(ps: list[float]) -> list[float]:
    m = len(ps)
    order = sorted(range(m), key=lambda i: ps[i])
    adj = [0.0] * m
    run = 0.0
    for rank, i in enumerate(order):
        run = max(run, min(1.0, (m - rank) * ps[i]))
        adj[i] = run
    return adj


# ------------------------------------------------------------------------------------------------ filtrlar
def macd_hist(close):
    e12, e26 = ema(close, 12), ema(close, 26)
    macd = [a - b if not (math.isnan(a) or math.isnan(b)) else math.nan for a, b in zip(e12, e26)]
    valid = [v for v in macd if not math.isnan(v)]
    sig_valid = ema(valid, 9)
    sig, k = [], 0
    for v in macd:
        if math.isnan(v):
            sig.append(math.nan)
        else:
            sig.append(sig_valid[k])
            k += 1
    return [m - s if not (math.isnan(m) or math.isnan(s)) else math.nan for m, s in zip(macd, sig)]


def engulfing(cs, i, long: bool) -> bool:
    a, b = cs[i - 1], cs[i]
    if long:
        return a.close < a.open and b.close > b.open and b.close >= a.open and b.open <= a.close
    return a.close > a.open and b.close < b.open and b.close <= a.open and b.open >= a.close


def pinbar(cs, i, long: bool) -> bool:
    c = cs[i]
    rng = c.high - c.low
    if rng <= 0:
        return False
    body = abs(c.close - c.open)
    lower = min(c.open, c.close) - c.low
    upper = c.high - max(c.open, c.close)
    if long:
        return lower >= 2 * body and lower >= 0.6 * rng and (c.close - c.low) / rng >= 0.66
    return upper >= 2 * body and upper >= 0.6 * rng and (c.high - c.close) / rng >= 0.66


def candle_pattern(cs, i, long: bool) -> bool:  # signal shamida yoki oldingisida
    return any(engulfing(cs, j, long) or pinbar(cs, j, long) for j in (i, i - 1))


def htf_state(htf: lab.HTF, t: datetime, long: bool) -> str:
    tr = htf.trend(t)
    if tr == "NA":
        return "NA"
    if tr in ("RANGE", "TRANSITION"):
        return "NEUTRAL"
    return "ALIGNED" if (tr == "TREND_UP") == long else "CONFLICT"


def build_flags(sym: str, tf: str, trades: list) -> dict[str, list[bool]]:
    c = lab.load(sym, tf)
    f = lab.Features.build(c)
    idx = {k.ts: i for i, k in enumerate(c)}
    hist = macd_hist(f.close)
    htf = lab.HTF(lab.load(sym, HIGHER[tf]))
    spec = costs.COSTS[sym]
    flags: dict[str, list[bool]] = defaultdict(list)
    for t in trades:
        i = idx[t.ts]
        long = t.direction == "LONG"
        h = hist[i]
        flags["MACD tasdig'i"].append(bool(not math.isnan(h) and (h > 0 if long else h < 0)))
        flags["Engulfing/Pin bar"].append(candle_pattern(c, i, long))
        pr = percentile_rank(f.atr_pct, i, 200)
        flags["ATR filtri (20-80 pers.)"].append(bool(not math.isnan(pr) and 20 <= pr <= 80))
        px = c[i].close
        risk = t.risk_pct / 100 * px
        sp = lab.spread_price(spec, px, 1.0)
        flags["Spred filtri (spred<=10% risk)"].append(bool(risk > 0 and sp / risk <= 0.10))
        st = htf_state(htf, c[i].end, long)
        flags["Yuqori TF zid emas"].append(st in ("ALIGNED", "NEUTRAL"))
        flags["Yuqori TF mos (ALIGNED)"].append(st == "ALIGNED")
    return flags


def group(trs, flags):
    keep = [t for t, ok in zip(trs, flags) if ok]
    drop = [t for t, ok in zip(trs, flags) if not ok]
    return keep, drop


def welch(a: list[float], b: list[float]) -> tuple[float, float]:
    if len(a) < 5 or len(b) < 5:
        return float("nan"), 1.0
    ma, sa = mean_sd(a)
    mb, sb = mean_sd(b)
    se = math.sqrt(sa ** 2 / len(a) + sb ** 2 / len(b))
    return ma - mb, norm_p2((ma - mb) / se) if se else 1.0


def fmt(s: dict) -> str:
    if not s["n"]:
        return "n=0"
    return (f"n={s['n']} E={s['expectancy']:+.3f} CI[{s['ci_lo']:+.2f},{s['ci_hi']:+.2f}] PF={s['pf']} WR={s['win_rate']}% "
            f"DD={s['maxdd']}R")


def main() -> None:
    out, report = {}, []
    P = report.append
    base_p = []
    for sym, tf, sid in CANDS:
        trs = lab.executed(pickle.load(open(L / f"trades_{sym}_{tf}_{sid}_net.pkl", "rb")))
        years = (trs[-1].ts - trs[0].ts).days / 365.25
        s = full_stats(trs, years)
        base_p.append(s["p_one"])
        out[(sym, tf, sid)] = {"trs": trs, "stats": s, "years": years}
    adj = holm([p for p in base_p] + [1.0] * (FAMILY_SELECTION - len(base_p)))[:len(base_p)]  # m=98: qolganlari p=1 deb
    # (qolgan 94 kombinatsiya "yaxshi emas" deb olinadi — konservativ Bonferroni/Holm)
    for (key, d), pa in zip(out.items(), adj):
        sym, tf, sid = key
        s = d["stats"]
        P(f"\n=== {sym} {tf} {sid} ===")
        P(f"Butun davr (net, {d['years']:.1f} yil): {fmt(s)}  t={s.get('t')}  Sharpe/savdo={s.get('sharpe_trade')} "
          f"yillik Sharpe={s.get('sharpe_ann')}  p(bir tomonli)={s['p_one']:.4f}  Holm(m=98) p={pa:.3f}")
        # xarajatsiz va stress
        for mode in ("gross", "stress"):
            tr2 = lab.executed(pickle.load(open(L / f"trades_{sym}_{tf}_{sid}_{mode}.pkl", "rb")))
            P(f"  {mode}: {fmt(lab.stats(tr2))}")
        P("Yillar bo'yicha:")
        yr = defaultdict(list)
        for t in d["trs"]:
            yr[t.ts.year].append(t)
        for y, ts in sorted(yr.items()):
            P(f"  {y}: {fmt(lab.stats(ts))}")
        P("Rejimlar bo'yicha:")
        rg = defaultdict(list)
        for t in d["trs"]:
            rg[t.regime].append(t)
        for r, ts in sorted(rg.items()):
            P(f"  {r}: {fmt(lab.stats(ts))}")
        P("Walk-forward (o'qitish 2 yil -> test 6 oy; parametrlar o'zgarmaydi):")
        wins = []
        for k, (a, b) in enumerate(WINDOWS):
            tr_in = [t for t in d["trs"] if a.replace(year=a.year - 2) <= t.ts < a]
            te = [t for t in d["trs"] if a <= t.ts < b]
            si, st = lab.stats(tr_in), lab.stats(te)
            wins.append(st)
            P(f"  W{k + 1} test {a:%Y-%m}..{b:%Y-%m}: {fmt(st)} | o'qitish oynasi E={si['expectancy']} n={si['n']}")
        pos = sum(1 for w in wins if w["n"] and w["expectancy"] > 0)
        te_all = [t for t in d["trs"] if WINDOWS[0][0] <= t.ts < WINDOWS[-1][1]]
        sa = full_stats(te_all, 3.0)
        P(f"  Test oynalari jami: {fmt(sa)} Sharpe(yillik)={sa.get('sharpe_ann')}; musbat oynalar: {pos}/{len(WINDOWS)}")
        d["wf"] = {"pos": pos, "all": sa, "wins": wins}

    P("\n\n##### FILTRLAR (har biri alohida; bazaviy savdolar o'tgan/rad etilgan guruhlarga bo'lingan) #####")
    fl_rows = []
    for (sym, tf, sid), d in out.items():
        flags = build_flags(sym, tf, d["trs"])
        P(f"\n--- {sym} {tf} {sid}: bazaviy {fmt(d['stats'])}")
        for name, fl in flags.items():
            keep, drop = group(d["trs"], fl)
            sk, sd_ = lab.stats(keep), lab.stats(drop)
            diff, p = welch([t.r for t in keep], [t.r for t in drop])
            fl_rows.append((sym, tf, sid, name, sk, sd_, diff, p))
    adj_f = holm([r[7] for r in fl_rows])
    cur = None
    for (sym, tf, sid, name, sk, sd_, diff, p), pa in zip(fl_rows, adj_f):
        if (sym, tf, sid) != cur:
            cur = (sym, tf, sid)
            P(f"\n{sym} {tf} {sid}")
        base_e = out[cur]["stats"]["expectancy"]
        P(f"  {name:32} o'tgan: {fmt(sk)}\n  {'':32} rad:    {fmt(sd_)}\n  {'':32} farq(o'tgan-rad)={diff:+.3f}R  "
          f"bazaga nisbatan E {sk['expectancy'] - base_e if sk['n'] else float('nan'):+.3f}R  p={p:.3f}  Holm(m={len(fl_rows)}) p={pa:.3f}")

    (L / "wf_report.txt").write_text("\n".join(report), encoding="utf-8")
    print("\n".join(report))


if __name__ == "__main__":
    main()
