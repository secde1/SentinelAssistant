"""Yangi 5 strategiya: BANK-SWEEP (likvidlik yig'ish / stop-hunt), TL-BOUNCE, TL-BREAK (trend chizig'i), SNR-REJ, SNR-FLIP (support/resistance).
bt_engine.py dvigatelidan foydalanadi (simulate/features/xarajat o'sha). Natija: ish/bt/trades_<aktiv>_<tf>_new.csv (eski fayllarga tegmaydi).
Look-ahead yo'q: pivotlar 3 sham keyin tasdiqlanadi, signal sham yopilgach, buyurtma keyingi shamdan. Ishlatish: python bt_new.py [aktiv ...]"""
import sys, time
sys.path.insert(0, r'D:\it-agent\data\skript')
import numpy as np, pandas as pd
import bt_engine as E

NEW = ['BANK-SWEEP', 'TL-BOUNCE', 'TL-BREAK', 'SNR-REJ', 'SNR-FLIP']
E.VALID.update({'BANK-SWEEP': 4, 'TL-BOUNCE': 4, 'TL-BREAK': 6, 'SNR-REJ': 4, 'SNR-FLIP': 4})
E.FIXED_RR.update(NEW)
K = 3


def pivots(h, l, k=K):
    n = len(h)
    hm = pd.Series(h).rolling(2 * k + 1, center=True).max().values
    lm = pd.Series(l).rolling(2 * k + 1, center=True).min().values
    ph = np.where(h == hm)[0]; pl = np.where(l == lm)[0]
    ph = ph[ph >= k]; pl = pl[pl >= k]
    return ph, pl


def levels(pconf, pprice, i, a, lookback=200):
    lo = np.searchsorted(pconf, i - lookback, 'left'); hi = np.searchsorted(pconf, i, 'right')
    pr = pprice[lo:hi]
    if len(pr) < 4: return np.array([])
    cnt = (np.abs(pr[:, None] - pr[None, :]) <= 0.3 * a).sum(axis=1)
    return pr[cnt >= 2]


def build(d, strat, P):
    n = len(d)
    o, h, l, c = d.open.values, d.high.values, d.low.values, d.close.values
    atr, e50, e200 = d.atr.values, d.ema50.values, d.ema200.values
    out = {}
    ph, pl = pivots(h, l)
    if strat == 'BANK-SWEEP':
        lsh, lsl, lshi, lsli = P['lsh'], P['lsl'], P['lshi'], P['lsli']
        for i in range(E.WARM, n):
            a = atr[i]
            if not a > 0: continue
            rng = max(h[i] - l[i], 1e-12)
            # yuqoridagi likvidlik (swing high stop'lari) yig'ildi -> SHORT
            if h[i] > lsh[i] + 0.05 * a and c[i] < lsh[i] and c[i - 1] <= lsh[i] and lshi[i] <= i - 6 and (h[i] - max(c[i], o[i])) >= 0.4 * rng:
                px = l[i] - 0.1 * a
                out[i] = dict(side=-1, type='stop', price=px, sl=h[i] + 0.1 * a)
            elif l[i] < lsl[i] - 0.05 * a and c[i] > lsl[i] and c[i - 1] >= lsl[i] and lsli[i] <= i - 6 and (min(c[i], o[i]) - l[i]) >= 0.4 * rng:
                px = h[i] + 0.1 * a
                out[i] = dict(side=1, type='stop', price=px, sl=l[i] - 0.1 * a)
    elif strat in ('TL-BOUNCE', 'TL-BREAK'):
        pcl, pch = pl + K, ph + K
        for i in range(E.WARM, n):
            a = atr[i]
            if not a > 0: continue
            # o'suvchi qo'llab-quvvatlash chizig'i (2 ta oxirgi pivot low)
            m = np.searchsorted(pcl, i, 'right')
            up = None
            if m >= 2:
                A, B = pl[m - 2], pl[m - 1]
                if B - A >= 6 and l[B] > l[A] and i - B <= 80:
                    s = (l[B] - l[A]) / (B - A); up = (B, l[B], s)
            m2 = np.searchsorted(pch, i, 'right')
            dn = None
            if m2 >= 2:
                A, B = ph[m2 - 2], ph[m2 - 1]
                if B - A >= 6 and h[B] < h[A] and i - B <= 80:
                    s = (h[B] - h[A]) / (B - A); dn = (B, h[B], s)
            if strat == 'TL-BOUNCE':
                if up and e50[i] > e200[i]:
                    B, pb, s = up; ln = pb + s * (i - B)
                    if c[i - 3:i + 1].min() > pb + s * (i - 3 - B) - 0.2 * a and l[i] <= ln + 0.25 * a and c[i] > ln and c[i] > o[i]:
                        px = h[i] + 0.1 * a
                        out[i] = dict(side=1, type='stop', price=px, sl=min(l[i], ln) - 0.3 * a)
                elif dn and e50[i] < e200[i]:
                    B, pb, s = dn; ln = pb + s * (i - B)
                    if c[i - 3:i + 1].max() < pb + s * (i - 3 - B) + 0.2 * a and h[i] >= ln - 0.25 * a and c[i] < ln and c[i] < o[i]:
                        px = l[i] - 0.1 * a
                        out[i] = dict(side=-1, type='stop', price=px, sl=max(h[i], ln) + 0.3 * a)
            else:
                if dn:  # pasayuvchi chiziq yuqoriga yorildi -> LONG, retest
                    B, pb, s = dn; ln = pb + s * (i - B); ln1 = pb + s * (i - 1 - B)
                    if c[i] > ln + 0.1 * a and c[i - 1] <= ln1 and (c[i - 6:i] <= pb + s * (np.arange(i - 6, i) - B) + 0.2 * a).all():
                        px = ln + s + 0.3 * a
                        out[i] = dict(side=1, type='limit', price=px, sl=ln + s - 0.8 * a, cancel=ln + s - 0.5 * a)
                if i not in out and up:
                    B, pb, s = up; ln = pb + s * (i - B); ln1 = pb + s * (i - 1 - B)
                    if c[i] < ln - 0.1 * a and c[i - 1] >= ln1 and (c[i - 6:i] >= pb + s * (np.arange(i - 6, i) - B) - 0.2 * a).all():
                        px = ln + s - 0.3 * a
                        out[i] = dict(side=-1, type='limit', price=px, sl=ln + s + 0.8 * a, cancel=ln + s + 0.5 * a)
    elif strat in ('SNR-REJ', 'SNR-FLIP'):
        idx = np.concatenate([ph, pl]); conf = idx + K
        price = np.concatenate([h[ph], l[pl]])
        order = np.argsort(conf); conf = conf[order]; price = price[order]
        for i in range(E.WARM, n):
            a = atr[i]
            if not a > 0: continue
            rng = max(h[i] - l[i], 1e-12); body = abs(c[i] - o[i])
            lw = min(c[i], o[i]) - l[i]; uw = h[i] - max(c[i], o[i])
            bull = c[i] > o[i] and (lw >= 0.4 * rng or lw >= 2 * body)
            bear = c[i] < o[i] and (uw >= 0.4 * rng or uw >= 2 * body)
            if not (bull or bear): continue
            q = levels(conf, price, i, a)
            if len(q) == 0: continue
            if strat == 'SNR-REJ':
                if bull:
                    s_ = q[(np.abs(l[i] - q) <= 0.3 * a) & (c[i] > q)]
                    if len(s_):
                        L = s_.max(); out[i] = dict(side=1, type='stop', price=h[i] + 0.1 * a, sl=min(l[i], L) - 0.2 * a)
                elif bear:
                    r_ = q[(np.abs(h[i] - q) <= 0.3 * a) & (c[i] < q)]
                    if len(r_):
                        L = r_.min(); out[i] = dict(side=-1, type='stop', price=l[i] - 0.1 * a, sl=max(h[i], L) + 0.2 * a)
            else:
                if bull:  # eski qarshilik -> yangi qo'llab-quvvatlash
                    s_ = q[(l[i] <= q + 0.25 * a) & (c[i] > q) & (l[i] >= q - 0.5 * a)]
                    for L in sorted(s_, reverse=True):
                        win = c[i - 10:i]
                        br = np.where((win[1:] > L + 0.3 * a) & (win[:-1] <= L))[0]
                        if len(br) and (win[br[0] + 1:] > L - 0.2 * a).all():
                            out[i] = dict(side=1, type='stop', price=h[i] + 0.1 * a, sl=min(l[i], L) - 0.3 * a); break
                elif bear:
                    r_ = q[(h[i] >= q - 0.25 * a) & (c[i] < q) & (h[i] <= q + 0.5 * a)]
                    for L in sorted(r_):
                        win = c[i - 10:i]
                        br = np.where((win[1:] < L - 0.3 * a) & (win[:-1] >= L))[0]
                        if len(br) and (win[br[0] + 1:] < L + 0.2 * a).all():
                            out[i] = dict(side=-1, type='stop', price=l[i] - 0.1 * a, sl=max(h[i], L) + 0.3 * a); break
    return out


def run(a, tfs=('1h', '4h')):
    t0 = time.time()
    h1 = E.load(a); m15 = None
    if a in ('BTCUSDT', 'ETHUSDT'):
        m = pd.read_csv(E.D + f'\\{a}_15m.csv', parse_dates=['t'], index_col='t').iloc[:-1]
        m['ema20'] = m.close.ewm(span=20, adjust=False).mean(); m['ema50'] = m.close.ewm(span=50, adjust=False).mean()
        m['trend'] = np.where((m.close > m.ema20) & (m.ema20 > m.ema50), 1, np.where((m.close < m.ema20) & (m.ema20 < m.ema50), -1, 0))
        m.index = m.index + pd.Timedelta(minutes=15); m15 = m
    h4 = E.resample(h1, '4h'); h4t = E.trend_series(h4); h4t.index = h4t.index + pd.Timedelta(hours=4)
    for tf in tfs:
        base = h1 if tf == '1h' else h4
        d = E.prep(base); P = E.pivot_state(d.high.values, d.low.values)
        d['st'] = np.where((P['lsh'] > P['psh']) & (P['lsl'] > P['psl']), 1, np.where((P['lsh'] < P['psh']) & (P['lsl'] < P['psl']), -1, 0))
        allt = []
        for s in NEW:
            orders = build(d, s, P)
            tr = E.simulate(d, s, orders)
            f = E.features(a, tf, d, tr, h4=h4t if tf == '1h' else None, m15=m15 if tf == '1h' else None)
            if not f.empty:
                f['strategy'] = s; allt.append(f)
            print(a, tf, s, len(orders), 'signals', len(tr), 'trades', round(time.time() - t0), 's', flush=True)
        if allt:
            pd.concat(allt).to_csv(E.BASE + f'\\trades_{a}_{tf}_new.csv', index=False)


if __name__ == '__main__':
    for a in (sys.argv[1:] or list(E.SRC)):
        run(a)
