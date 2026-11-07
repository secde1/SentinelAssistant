"""Walk-forward parametr tanlash: har strategiya uchun (rr, sl_scale) setkasi; har test yili uchun faqat OLDINGI yillar bilan tanlanadi (anchored).
Natija: ish/bt/wfa_results.csv, wfa_oos_trades.csv, grid_all.csv"""
import sys
sys.path.insert(0, r'D:\it-agent\data\skript')
import numpy as np, pandas as pd, itertools
import bt_engine as E

RRS = [1.0, 1.5, 2.0, 3.0]
SLS = [0.75, 1.0, 1.5, 2.0]
rows = []
for a in E.SRC:
    h1 = E.load(a)
    for tf in ('1h', '4h'):
        base = h1 if tf == '1h' else E.resample(h1, '4h')
        d = E.prep(base)
        P = E.pivot_state(d.high.values, d.low.values)
        for s in sorted(E.FIXED_RR):
            orders = E.build_orders(d, s, P)
            for rr, sc in itertools.product(RRS, SLS):
                tr = E.simulate(d, s, orders, rr=rr, sl_scale=sc)
                for t in tr:
                    rows.append((a, tf, s, rr, sc, d.index[t['fill_i']], t['gross_R'], E.cost_R(a, t['fill'], t['risk'], 'cfg')))
        print(a, tf, 'ok', len(rows), flush=True)
g = pd.DataFrame(rows, columns=['asset', 'tf', 'strategy', 'rr', 'sl_scale', 'fill_time', 'gross_R', 'cost'])
g['net_R'] = g.gross_R - g.cost
g['year'] = g.fill_time.dt.year
g.to_csv(E.BASE + r'\grid_all.csv', index=False)
# WFA: strategiya x tf bo'yicha, aktivlar birlashtirilgan, parametr bitta
res = []; oos_rows = []
for (s, tf), gg in g.groupby(['strategy', 'tf']):
    years = sorted(gg.year.unique())
    for y in years:
        if y < 2023: continue  # kamida 2 yil train (2021-2022)
        tr = gg[gg.year < y]; te = gg[gg.year == y]
        sc = tr.groupby(['rr', 'sl_scale']).net_R.agg(['mean', 'size'])
        sc = sc[sc['size'] >= 150]
        if sc.empty: continue
        best = sc['mean'].idxmax()
        te_best = te[(te.rr == best[0]) & (te.sl_scale == best[1])]
        te_def = te[(te.rr == 2.0) & (te.sl_scale == 1.0)]
        res.append(dict(strategy=s, tf=tf, test_year=y, best_rr=best[0], best_sl=best[1], train_exp=sc.loc[best, 'mean'],
                        oos_n=len(te_best), oos_exp=te_best.net_R.mean(), oos_exp_gross=te_best.gross_R.mean(),
                        default_oos_exp=te_def.net_R.mean(), default_n=len(te_def)))
pd.DataFrame(res).to_csv(E.BASE + r'\wfa_results.csv', index=False)
print(pd.DataFrame(res).round(3).to_string())
