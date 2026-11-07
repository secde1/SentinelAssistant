import sys, glob
sys.path.insert(0, r'D:\it-agent\data\skript')
import numpy as np, pandas as pd
from math import sqrt, erf
import bt_engine as E

B = E.BASE
T = pd.concat([pd.read_csv(f, parse_dates=['sig_time', 'fill_time']) for f in glob.glob(B + r'\trades_*.csv')], ignore_index=True)
T['year'] = T.fill_time.dt.year
t0, t1 = T.fill_time.min(), T.fill_time.max()
SPLIT = t0 + (t1 - t0) * 0.7
T['part'] = np.where(T.fill_time < SPLIT, 'IS', 'OOS')
print('trades', len(T), 'split', SPLIT)


def ncdf(z): return 0.5 * (1 + erf(z / sqrt(2)))


def stats(x, col='net_R'):
    r = x[col].values
    n = len(r)
    if n == 0: return {}
    w = r[r > 0]; l = r[r <= 0]
    m = r.mean(); sd = r.std(ddof=1) if n > 1 else np.nan
    se = sd / sqrt(n) if n > 1 else np.nan
    z = m / se if se and se > 0 else np.nan
    cs = np.cumsum(r[np.argsort(x.fill_time.values)])
    dd = (np.maximum.accumulate(np.concatenate([[0], cs]))[1:] - cs).max() if n else 0
    gp, gl = w.sum(), -l.sum()
    p = 1 - ncdf(z) if z == z else np.nan  # bir tomonlama: mean<=0 gipotezasi
    wr = (r > 0).mean()
    wil = (wr + 1.96 ** 2 / (2 * n) - 1.96 * sqrt(wr * (1 - wr) / n + 1.96 ** 2 / (4 * n * n))) / (1 + 1.96 ** 2 / n)
    wih = (wr + 1.96 ** 2 / (2 * n) + 1.96 * sqrt(wr * (1 - wr) / n + 1.96 ** 2 / (4 * n * n))) / (1 + 1.96 ** 2 / n)
    return dict(n=n, WR=round(wr * 100, 1), WR_lo=round(wil * 100, 1), WR_hi=round(wih * 100, 1),
                avgW=round(w.mean(), 3) if len(w) else 0, avgL=round(l.mean(), 3) if len(l) else 0,
                PF=round(gp / gl, 3) if gl > 0 else np.nan, exp_gross=round(x.gross_R.mean(), 3), exp_net=round(m, 3),
                exp_net_lowfee=round(x.net_R_low.mean(), 3), ci_lo=round(m - 1.96 * se, 3) if se == se else np.nan,
                ci_hi=round(m + 1.96 * se, 3) if se == se else np.nan, p_pos=round(p, 4) if p == p else np.nan,
                maxDD_R=round(dd, 1), total_R=round(r.sum(), 1))


def tab(df, keys, **kw):
    rows = []
    for k, g in df.groupby(keys):
        k = k if isinstance(k, tuple) else (k,)
        s = stats(g, **kw)
        if s: rows.append({**dict(zip(keys if isinstance(keys, list) else [keys], k)), **s})
    return pd.DataFrame(rows)


out = {}
out['1_Strategiya_umumiy'] = tab(T, ['tf', 'strategy'])
out['2_Aktiv_kesimi'] = tab(T, ['strategy', 'tf', 'asset'])
# IS / OOS
iso = []
for (s, tf), g in T.groupby(['strategy', 'tf']):
    a, b = stats(g[g.part == 'IS']), stats(g[g.part == 'OOS'])
    iso.append(dict(strategy=s, tf=tf, IS_n=a['n'], IS_exp_net=a['exp_net'], IS_exp_gross=a['exp_gross'], IS_PF=a['PF'],
                    OOS_n=b['n'], OOS_exp_net=b['exp_net'], OOS_exp_gross=b['exp_gross'], OOS_PF=b['PF'], OOS_ci_lo=b['ci_lo'], OOS_ci_hi=b['ci_hi'], OOS_p_pos=b['p_pos'], OOS_maxDD=b['maxDD_R']))
out['3_IS_OOS'] = pd.DataFrame(iso)
# yillik (walk-forward, qat'iy parametr)
yr = T.groupby(['strategy', 'tf', 'year']).net_R.agg(['size', 'mean']).reset_index().pivot_table(index=['strategy', 'tf'], columns='year', values='mean').round(3)
yr['yillar_musbat'] = (yr > 0).sum(axis=1)
out['4_Yillik_folds'] = yr.reset_index()
wfa = pd.read_csv(B + r'\wfa_results.csv')
ws = wfa.groupby(['strategy', 'tf']).apply(lambda g: pd.Series(dict(
    folds=len(g), oos_n=g.oos_n.sum(), WFA_exp_net=round(np.average(g.oos_exp, weights=g.oos_n), 3),
    WFA_exp_gross=round(np.average(g.oos_exp_gross, weights=g.oos_n), 3),
    default_exp_net=round(np.average(g.default_oos_exp, weights=g.default_n), 3), pos_folds=int((g.oos_exp > 0).sum())))).reset_index()
out['5_WFA_parametr'] = ws
out['5b_WFA_detail'] = wfa.round(3)
# rejim
out['6_Rejim'] = tab(T, ['strategy', 'tf', 'regime'])
out['6b_Trend_bilan'] = tab(T, ['strategy', 'tf', 'with_trend'])
out['6c_Volatillik'] = tab(T, ['strategy', 'tf', 'vol'])
out['6d_Sessiya'] = tab(T, ['strategy', 'tf', 'session'])
# MTF (1h)
H = T[T.tf == '1h']
out['7_MTF_H4'] = tab(H, ['strategy', 'h4_rel'])
out['7b_MTF_H1struktura'] = tab(H, ['strategy', 'h1_rel'])
M = H[H.m15_rel.notna() & (H.m15_rel != 'n/a')]
out['7c_MTF_M15_kripto'] = tab(M, ['strategy', 'm15_rel'])
H2 = H[(H.h4_rel == 'aligned') & (H.h1_rel == 'aligned')]
out['7d_H4+H1_birga'] = tab(H2, ['strategy'])
# filtrlar
FIL = {
    'MACD yo`nalishda': lambda g: g.macd_ok == 1,
    'Sham modeli': lambda g: g.candle_ok == 1,
    'Volume Profile POC tomoni': lambda g: g.poc_ok == 1,
    'London/NY sessiya': lambda g: g.session != 'Asia/off',
    'Volatillik NORMAL': lambda g: g.vol == 'NORMAL',
    'Spred/xarajat<=15% R': lambda g: g.cost_cfg <= 0.15,
    'H4 trend mos': lambda g: g.h4_rel == 'aligned',
    'H1 struktura mos': lambda g: g.h1_rel == 'aligned',
}
fr = []
for (s, tf), g in T.groupby(['strategy', 'tf']):
    bi, bo = stats(g[g.part == 'IS']), stats(g[g.part == 'OOS'])
    for fn, f in FIL.items():
        if tf == '4h' and fn in ('H4 trend mos',): continue
        m = f(g).fillna(False)
        gi, go = g[m & (g.part == 'IS')], g[m & (g.part == 'OOS')]
        if len(gi) < 30 or len(go) < 30: continue
        si, so = stats(gi), stats(go)
        keep = (si['exp_net'] - bi['exp_net'] >= 0.02) and (so['exp_net'] - bo['exp_net'] >= 0.02) and len(go) >= 100 and len(gi) >= 0.3 * bi['n']
        fr.append(dict(strategy=s, tf=tf, filter=fn, base_IS=bi['exp_net'], filt_IS=si['exp_net'], n_IS=si['n'], base_OOS=bo['exp_net'], filt_OOS=so['exp_net'], n_OOS=so['n'],
                       OOS_ci_lo=so['ci_lo'], OOS_ci_hi=so['ci_hi'], OOS_p_pos=so['p_pos'], yaxshilaydi=bool(keep), OOS_net_musbat=bool(so['exp_net'] > 0)))
out['8_Filtrlar'] = pd.DataFrame(fr)
# zarar tahlili
la = []
for (s, tf), g in T.groupby(['strategy', 'tf']):
    st = stats(g)
    sl = g[g.why == 'SL']
    la.append(dict(strategy=s, tf=tf, n=st['n'], WR=st['WR'], breakeven_WR_net=round(-st['avgL'] / (st['avgW'] - st['avgL']) * 100, 1), avgW_net=st['avgW'], avgL_net=st['avgL'],
                   gross_exp=st['exp_gross'], cost_drag_R=round(g.cost_cfg.mean(), 3), net_exp=st['exp_net'],
                   pct_SL=round((g.why == 'SL').mean() * 100, 1), pct_TP=round((g.why == 'TP').mean() * 100, 1), pct_TIME=round((g.why == 'TIME').mean() * 100, 1),
                   SL_lekin_MFE_1R_dan_yuqori=round((sl.mfe >= 1.0).mean() * 100, 1), median_ushlash_sham=g.bars.median(), TIME_avgR=round(g[g.why == 'TIME'].gross_R.mean(), 3)))
out['9_Zarar_tahlili'] = pd.DataFrame(la)
# grid
G = pd.read_csv(B + r'\grid_all.csv')
gp = G.groupby(['strategy', 'tf', 'rr', 'sl_scale']).agg(n=('net_R', 'size'), gross=('gross_R', 'mean'), net=('net_R', 'mean')).round(3).reset_index()
out['10_Grid_rr_sl'] = gp
# nomzodlar
cand = []
nt = T.groupby(['strategy', 'tf', 'asset']).ngroups
for (s, tf, a), g in T.groupby(['strategy', 'tf', 'asset']):
    si, so, sa = stats(g[g.part == 'IS']), stats(g[g.part == 'OOS']), stats(g)
    if not si or not so: continue
    ys = g.groupby('year').net_R.mean()
    cand.append(dict(strategy=s, tf=tf, asset=a, n=sa['n'], exp_net=sa['exp_net'], ci_lo=sa['ci_lo'], p_pos=sa['p_pos'], IS=si['exp_net'], OOS=so['exp_net'], OOS_n=so['n'],
                     musbat_yil=int((ys > 0).sum()), yillar=len(ys), bonferroni_p=round(min(1, sa['p_pos'] * nt), 3), PF=sa['PF'], maxDD=sa['maxDD_R']))
C = pd.DataFrame(cand).sort_values('exp_net', ascending=False)
C['IS_OOS_ikkalasi_musbat'] = (C.IS > 0) & (C.OOS > 0)
out['11_Nomzodlar'] = C
# korrelyatsiya
dr = {}
for a in E.SRC:
    d = E.load(a).close.resample('1D').last().dropna()
    dr[a] = d.pct_change()
R = pd.DataFrame(dr).dropna()
out['12_Korrelyatsiya_kunlik'] = R.corr().round(2).reset_index()
ov = []
for (s, tf), g in T.groupby(['strategy', 'tf']):
    b = g[g.asset == 'BTCUSDT']; e = g[g.asset == 'ETHUSDT']
    if b.empty or e.empty: continue
    be = b.assign(end=b.fill_time + pd.to_timedelta(b.bars * (1 if tf == '1h' else 4), unit='h'))
    ee = e.assign(end=e.fill_time + pd.to_timedelta(e.bars * (1 if tf == '1h' else 4), unit='h'))
    same = 0; opp = 0
    for _, r in be.iterrows():
        m = ee[(ee.fill_time <= r.end) & (ee.end >= r.fill_time)]
        if len(m):
            if (m.side == r.side).any(): same += 1
            else: opp += 1
    rho = R.loc[:, ['BTCUSDT', 'ETHUSDT']].corr().iloc[0, 1]
    ov.append(dict(strategy=s, tf=tf, btc_trades=len(be), eth_bilan_bir_vaqtda_bir_yonalish_pct=round(same / len(be) * 100, 1), qarama_qarshi_pct=round(opp / len(be) * 100, 1), kunlik_rho=round(rho, 2),
                   birga_risk_x=round(sqrt(2 + 2 * rho), 2)))
out['13_BTC_ETH_bir_vaqtda_risk'] = pd.DataFrame(ov)

with pd.ExcelWriter(B + r'\Strategiya_tadqiqot.xlsx', engine='openpyxl') as w:
    for k, v in out.items():
        v.to_excel(w, sheet_name=k[:31], index=False)
        ws_ = w.sheets[k[:31]]
        for col in ws_.columns:
            ws_.column_dimensions[col[0].column_letter].width = min(28, max(10, max(len(str(c.value)) for c in col[:50] if c.value is not None) + 2))
        ws_.freeze_panes = 'A2'
        from openpyxl.styles import Font
        for c in ws_[1]: c.font = Font(bold=True)
import pickle
pickle.dump(out, open(B + r'\out.pkl', 'wb'))
pd.set_option('display.width', 250); pd.set_option('display.max_columns', 30)
for k in ['1_Strategiya_umumiy', '3_IS_OOS', '5_WFA_parametr', '9_Zarar_tahlili']:
    print('==', k); print(out[k].to_string(index=False))
