"""Backtest dvigateli (faqat tarixiy ma'lumot, real savdo yo'q). 7 ta strategiya registrdagi qoidalar bo'yicha.
Konservativ: bir shamda SL va TP ikkalasi tegsa - SL birinchi. Look-ahead yo'q (pivotlar 3 sham keyin tasdiqlanadi).
Ishlatish: python bt_engine.py [aktiv ...]  -> ish/bt/trades_<aktiv>_<tf>.csv"""
import numpy as np, pandas as pd, os, sys, glob, time

BASE = r'D:\it-agent\data\ish\bt'
D = BASE + r'\data'
K = BASE + r'\duka'
SRC = {
    'BTCUSDT': D + r'\BTCUSDT_1h.csv', 'ETHUSDT': D + r'\ETHUSDT_1h.csv',
    'XAUUSD': K + r'\xauusd-h1-bid-*.csv', 'EURUSD': K + r'\eurusd-h1-bid-*.csv', 'GBPUSD': K + r'\gbpusd-h1-bid-*.csv',
    'NAS100': K + r'\usatechidxusd-h1-bid-*.csv', 'SPX500': K + r'\usa500idxusd-h1-bid-*.csv',
}
# xarajat: pct -> kripto (komissiya har tomonga + spred/slippage bps); abs -> narx birligida (spred+slippage, to'liq aylanma)
COST = {
    'BTCUSDT': ('pct', 0.0010, 1.0, 1.0), 'ETHUSDT': ('pct', 0.0010, 1.5, 1.0),
    'XAUUSD': ('abs', 0.30, 0.10), 'EURUSD': ('abs', 0.00012, 0.00002), 'GBPUSD': ('abs', 0.00015, 0.00002),
    'NAS100': ('abs', 1.0, 0.5), 'SPX500': ('abs', 0.4, 0.2),
}
CRYPTO_LOW_FEE = 0.0004  # fyuchers taker (sezgirlik stsenariysi)
STRATS = ['TF-PULLBACK', 'BRK-RETEST', 'MA-CROSS', 'MS-BOS', 'RSI-MR', 'SR-BOUNCE', 'VOL-BRK']
VALID = {'TF-PULLBACK': 6, 'BRK-RETEST': 6, 'MA-CROSS': 1, 'MS-BOS': 8, 'RSI-MR': 4, 'SR-BOUNCE': 6, 'VOL-BRK': 6}
FIXED_RR = {'TF-PULLBACK', 'BRK-RETEST', 'MA-CROSS', 'MS-BOS', 'VOL-BRK'}
MAXHOLD = 48
WARM = 260


def load(a):
    p = glob.glob(SRC[a])[0]
    if 'duka' in p:
        df = pd.read_csv(p)
        df['t'] = pd.to_datetime(df.timestamp, unit='ms', utc=True)
        df = df.set_index('t')[['open', 'high', 'low', 'close', 'volume']]
    else:
        df = pd.read_csv(p, parse_dates=['t'], index_col='t')
        df = df.iloc[:-1]  # oxirgi (tugamagan) sham
    df = df[~df.index.duplicated()].sort_index()
    return df


def resample(df, rule):
    r = df.resample(rule, origin='epoch').agg({'open': 'first', 'high': 'max', 'low': 'min', 'close': 'last', 'volume': 'sum'})
    return r.dropna(subset=['open'])


def pct_rank(x):
    return (x <= x[-1]).mean() * 100


def prep(df):
    d = df.copy()
    c, h, l = d.close, d.high, d.low
    for s in (9, 12, 20, 21, 26, 50, 200):
        d[f'ema{s}'] = c.ewm(span=s, adjust=False).mean()
    pc = c.shift()
    tr = pd.concat([h - l, (h - pc).abs(), (l - pc).abs()], axis=1).max(axis=1)
    d['atr'] = tr.ewm(alpha=1 / 14, adjust=False).mean()
    delta = c.diff()
    up = delta.clip(lower=0).ewm(alpha=1 / 14, adjust=False).mean()
    dn = (-delta.clip(upper=0)).ewm(alpha=1 / 14, adjust=False).mean()
    d['rsi'] = 100 - 100 / (1 + up / dn.replace(0, np.nan))
    sma = c.rolling(20).mean()
    sd = c.rolling(20).std(ddof=0)
    d['sma20'] = sma
    d['bbu'] = sma + 2 * sd
    d['bbl'] = sma - 2 * sd
    d['bbw'] = 4 * sd / sma
    d['bbw_pct'] = d.bbw.rolling(120).apply(pct_rank, raw=True)
    um, dm = h.diff(), -l.diff()
    pdm = pd.Series(np.where((um > dm) & (um > 0), um, 0.0), index=d.index)
    mdm = pd.Series(np.where((dm > um) & (dm > 0), dm, 0.0), index=d.index)
    pdi = 100 * pdm.ewm(alpha=1 / 14, adjust=False).mean() / d.atr
    mdi = 100 * mdm.ewm(alpha=1 / 14, adjust=False).mean() / d.atr
    dx = 100 * (pdi - mdi).abs() / (pdi + mdi).replace(0, np.nan)
    d['adx'] = dx.ewm(alpha=1 / 14, adjust=False).mean()
    macd = d.ema12 - d.ema26
    d['macdh'] = macd - macd.ewm(span=9, adjust=False).mean()
    d['atrp'] = (d.atr / c).rolling(500, min_periods=100).apply(pct_rank, raw=True)
    d['rh10'] = h.rolling(10).max()
    d['rl10'] = l.rolling(10).min()
    return d


def pivot_state(h, l, k=3):
    n = len(h)
    hm = pd.Series(h).rolling(2 * k + 1, center=True).max().values
    lm = pd.Series(l).rolling(2 * k + 1, center=True).min().values
    isH, isL = (h == hm), (l == lm)
    lsh = np.full(n, np.nan); psh = np.full(n, np.nan); lsl = np.full(n, np.nan); psl = np.full(n, np.nan)
    lshi = np.full(n, -1); lsli = np.full(n, -1)
    a = b = c_ = e = np.nan
    ih = il = -1
    for i in range(n):
        j = i - k
        if j >= k:
            if isH[j]:
                b, a, ih = a, h[j], j
            if isL[j]:
                e, c_, il = c_, l[j], j
        lsh[i], psh[i], lsl[i], psl[i], lshi[i], lsli[i] = a, b, c_, e, ih, il
    js = np.where(isH | isL)[0]
    pconf = js + k
    pprice = np.where(isH[js], h[js], l[js])
    return dict(lsh=lsh, psh=psh, lsl=lsl, psl=psl, lshi=lshi, lsli=lsli, pconf=pconf, pprice=pprice)


def build_orders(d, strat, P):
    n = len(d)
    o_, h_, l_, c_ = d.open.values, d.high.values, d.low.values, d.close.values
    atr, e20, e50, e200, e9, e21 = d.atr.values, d.ema20.values, d.ema50.values, d.ema200.values, d.ema9.values, d.ema21.values
    rsi, adx, bbl, bbu, sma20, bbwp = d.rsi.values, d.adx.values, d.bbl.values, d.bbu.values, d.sma20.values, d.bbw_pct.values
    atrp, rh10, rl10 = d.atrp.values, d.rh10.values, d.rl10.values
    out = {}
    if strat == 'TF-PULLBACK':
        for i in range(WARM, n):
            a = atr[i]
            if not a > 0: continue
            touchL = (l_[i - 2:i + 1] <= e20[i - 2:i + 1]).any()
            touchH = (h_[i - 2:i + 1] >= e20[i - 2:i + 1]).any()
            if e20[i] > e50[i] > e200[i] and touchL and c_[i] > e20[i]:
                px = h_[i] + 0.1 * a
                out[i] = dict(side=1, type='stop', price=px, sl=px - 1.5 * a)
            elif e20[i] < e50[i] < e200[i] and touchH and c_[i] < e20[i]:
                px = l_[i] - 0.1 * a
                out[i] = dict(side=-1, type='stop', price=px, sl=px + 1.5 * a)
    elif strat == 'BRK-RETEST':
        hh = pd.Series(h_).rolling(20).max().shift(1).values
        ll = pd.Series(l_).rolling(20).min().shift(1).values
        for i in range(WARM, n):
            a = atr[i]
            if not a > 0: continue
            done = False
            for b in range(i, i - 5, -1):
                if c_[b] > hh[b] and abs(c_[i] - hh[b]) <= 0.4 * a and c_[i] >= hh[b]:
                    lvl = hh[b]; px = lvl + 0.1 * a
                    out[i] = dict(side=1, type='limit', price=px, sl=lvl - a, cancel=lvl - 0.5 * a); done = True; break
                if c_[b] < ll[b] and abs(c_[i] - ll[b]) <= 0.4 * a and c_[i] <= ll[b]:
                    lvl = ll[b]; px = lvl - 0.1 * a
                    out[i] = dict(side=-1, type='limit', price=px, sl=lvl + a, cancel=lvl + 0.5 * a); done = True; break
    elif strat == 'MA-CROSS':
        for i in range(WARM, n):
            a = atr[i]
            if not a > 0: continue
            up = any(e9[b] > e21[b] and e9[b - 1] <= e21[b - 1] for b in (i, i - 1))
            dn = any(e9[b] < e21[b] and e9[b - 1] >= e21[b - 1] for b in (i, i - 1))
            if up and c_[i] > e200[i] and e9[i] > e21[i]:
                sl = min(l_[i - 9:i + 1].min() - 0.2 * a, c_[i] - a)
                out[i] = dict(side=1, type='market', price=None, sl=sl, ref=c_[i])
            elif dn and c_[i] < e200[i] and e9[i] < e21[i]:
                sl = max(h_[i - 9:i + 1].max() + 0.2 * a, c_[i] + a)
                out[i] = dict(side=-1, type='market', price=None, sl=sl, ref=c_[i])
    elif strat == 'MS-BOS':
        lsh, psh, lsl, psl, lshi, lsli = P['lsh'], P['psh'], P['lsl'], P['psl'], P['lshi'], P['lsli']
        for i in range(WARM, n):
            a = atr[i]
            if not a > 0: continue
            if lsl[i] > psl[i] and lsli[i] > lshi[i] and c_[i] > lsh[i] and c_[i - 1] <= lsh[i]:
                top = h_[lsli[i]:i + 1].max(); hl = lsl[i]
                px = top - 0.5 * (top - hl)
                out[i] = dict(side=1, type='limit', price=px, sl=hl - 0.2 * a)
            elif lsh[i] < psh[i] and lshi[i] > lsli[i] and c_[i] < lsl[i] and c_[i - 1] >= lsl[i]:
                bot = l_[lshi[i]:i + 1].min(); lh = lsh[i]
                px = bot + 0.5 * (lh - bot)
                out[i] = dict(side=-1, type='limit', price=px, sl=lh + 0.2 * a)
    elif strat == 'RSI-MR':
        for i in range(WARM, n):
            a = atr[i]
            if not a > 0: continue
            if not adx[i] < 20 or atrp[i] > 80: continue
            if rsi[i] < 30 and c_[i] < bbl[i]:
                px = c_[i] - 0.2 * a; sl = px - 1.2 * a; tp = sma20[i]
                if tp > px and (tp - px) / (px - sl) >= 1.2:
                    out[i] = dict(side=1, type='limit', price=px, sl=sl, tp=tp)
            elif rsi[i] > 70 and c_[i] > bbu[i]:
                px = c_[i] + 0.2 * a; sl = px + 1.2 * a; tp = sma20[i]
                if tp < px and (px - tp) / (sl - px) >= 1.2:
                    out[i] = dict(side=-1, type='limit', price=px, sl=sl, tp=tp)
    elif strat == 'SR-BOUNCE':
        pconf, pprice = P['pconf'], P['pprice']
        for i in range(WARM, n):
            a = atr[i]
            if not a > 0: continue
            if not (rsi[i] <= 45 or rsi[i] >= 55): continue
            lo = np.searchsorted(pconf, i - 120, 'left'); hi = np.searchsorted(pconf, i, 'right')
            pr = pprice[lo:hi]
            if len(pr) < 4: continue
            tol = 0.3 * a
            cnt = (np.abs(pr[:, None] - pr[None, :]) <= tol).sum(axis=1)
            q = pr[cnt >= 2]
            if len(q) == 0: continue
            if rsi[i] <= 45:
                sup = q[(q < c_[i]) & (c_[i] - q <= 0.5 * a)]
                if len(sup):
                    L = sup.max(); px = L + 0.1 * a; sl = L - 0.8 * a
                    res = q[q > px]
                    if len(res):
                        tp = res.min()
                        if (tp - px) / (px - sl) >= 1.5:
                            out[i] = dict(side=1, type='limit', price=px, sl=sl, tp=tp)
            if i not in out and rsi[i] >= 55:
                res = q[(q > c_[i]) & (q - c_[i] <= 0.5 * a)]
                if len(res):
                    L = res.min(); px = L - 0.1 * a; sl = L + 0.8 * a
                    sup = q[q < px]
                    if len(sup):
                        tp = sup.max()
                        if (px - tp) / (sl - px) >= 1.5:
                            out[i] = dict(side=-1, type='limit', price=px, sl=sl, tp=tp)
    elif strat == 'VOL-BRK':
        for i in range(WARM, n):
            a = atr[i]
            if not a > 0: continue
            if not bbwp[i] <= 20: continue
            if adx[i] >= 25: continue
            if rh10[i] - rl10[i] > 3 * a: continue
            slope = e50[i] - e50[i - 3]
            if slope > 0:
                px = rh10[i] + 0.1 * a
                out[i] = dict(side=1, type='stop', price=px, sl=rl10[i])
            elif slope < 0:
                px = rl10[i] - 0.1 * a
                out[i] = dict(side=-1, type='stop', price=px, sl=rh10[i])
    return out


def simulate(d, strat, orders, rr=2.0, sl_scale=1.0):
    o_, h_, l_, c_ = d.open.values, d.high.values, d.low.values, d.close.values
    n = len(d)
    valid = VALID[strat]
    trades = []
    i = WARM
    keys = sorted(orders)
    ki = 0
    while ki < len(keys):
        i = keys[ki]
        ki += 1
        o = orders[i]
        side, typ = o['side'], o['type']
        fill = None; fpx = None
        for j in range(i + 1, min(i + 1 + valid, n)):
            if typ == 'market':
                fill, fpx = j, o_[j]; break
            if 'cancel' in o:
                if (side == 1 and c_[j - 1] < o['cancel']) or (side == -1 and c_[j - 1] > o['cancel']): break
            px = o['price']
            if typ == 'limit':
                if side == 1 and l_[j] <= px: fill, fpx = j, min(px, o_[j]); break
                if side == -1 and h_[j] >= px: fill, fpx = j, max(px, o_[j]); break
            else:
                if side == 1 and h_[j] >= px: fill, fpx = j, max(px, o_[j]); break
                if side == -1 and l_[j] <= px: fill, fpx = j, min(px, o_[j]); break
        if fill is None: continue
        sl = o['sl']
        if strat in FIXED_RR:
            ref = o['ref'] if typ == 'market' else o['price']
            risk0 = abs(ref - sl) * sl_scale
            sl = fpx - side * risk0
            tp = fpx + side * risk0 * rr
        else:
            tp = o['tp']
        risk = (fpx - sl) * side
        if risk <= 0 or (tp - fpx) * side <= 0: continue
        ex = None
        mfe = 0.0; mae = 0.0
        tp_ok = (typ != 'limit') or (fpx == o_[fill])  # limit: fill barida TP ruxsat yo'q (intrabar tartib noma'lum -> konservativ)
        last = min(fill + MAXHOLD, n - 1)
        for k in range(fill, last + 1):
            if side == 1:
                if l_[k] <= sl: ex, ek, why = min(sl, o_[k]) if k > fill else sl, k, 'SL'; break
                if h_[k] >= tp and (k > fill or tp_ok): ex, ek, why = tp, k, 'TP'; break
                mfe = max(mfe, (h_[k] - fpx) / risk); mae = max(mae, (fpx - l_[k]) / risk)
            else:
                if h_[k] >= sl: ex, ek, why = max(sl, o_[k]) if k > fill else sl, k, 'SL'; break
                if l_[k] <= tp and (k > fill or tp_ok): ex, ek, why = tp, k, 'TP'; break
                mfe = max(mfe, (fpx - l_[k]) / risk); mae = max(mae, (h_[k] - fpx) / risk)
        if ex is None:
            ex, ek, why = c_[last], last, 'TIME'
        gross = (ex - fpx) * side / risk
        trades.append(dict(sig_i=i, fill_i=fill, exit_i=ek, side=side, fill=fpx, sl=sl, tp=tp, exit=ex, why=why, risk=risk, gross_R=gross, mfe=mfe, mae=mae, bars=ek - fill))
        # keyingi signal faqat pozitsiya yopilgandan keyin
        while ki < len(keys) and keys[ki] <= ek:
            ki += 1
    return trades


def cost_R(asset, fill, risk, scen='cfg'):
    c = COST[asset]
    if c[0] == 'pct':
        fee = c[1] if scen == 'cfg' else CRYPTO_LOW_FEE
        cp = fill * (2 * fee + (c[2] + c[3]) * 1e-4)
    else:
        cp = c[1] + c[2]
    return cp / risk


def poc_side(d, idx_list, side_list):
    h, l, c, v = d.high.values, d.low.values, d.close.values, d.volume.values
    res = []
    for i, s in zip(idx_list, side_list):
        a = max(0, i - 199)
        tp = (h[a:i + 1] + l[a:i + 1] + c[a:i + 1]) / 3
        w = v[a:i + 1]
        if w.sum() <= 0: res.append(np.nan); continue
        hist, edges = np.histogram(tp, bins=30, weights=w)
        poc = (edges[hist.argmax()] + edges[hist.argmax() + 1]) / 2
        res.append(1.0 if (c[i] - poc) * s > 0 else 0.0)
    return res


def features(a, tf, d, tr, h4=None, m15=None):
    t = pd.DataFrame(tr)
    if t.empty: return t
    idx = d.index
    i = t.sig_i.values
    t['asset'], t['tf'] = a, tf
    t['sig_time'] = idx[i]
    t['fill_time'] = idx[t.fill_i.values]
    t['cost_cfg'] = [cost_R(a, f, r, 'cfg') for f, r in zip(t.fill, t.risk)]
    t['cost_low'] = [cost_R(a, f, r, 'low') for f, r in zip(t.fill, t.risk)]
    t['net_R'] = t.gross_R - t.cost_cfg
    t['net_R_low'] = t.gross_R - t.cost_low
    adx, e50, e200, atrp = d.adx.values[i], d.ema50.values[i], d.ema200.values[i], d.atrp.values[i]
    t['regime'] = np.where(adx >= 25, np.where(e50 > e200, 'TREND_UP', 'TREND_DOWN'), np.where(adx < 20, 'RANGE', 'TRANSITION'))
    t['vol'] = np.where(atrp > 75, 'HIGH', np.where(atrp < 25, 'LOW', 'NORMAL'))
    t['atrp'] = atrp
    t['with_trend'] = np.where(t.regime == 'RANGE', 'range', np.where(((t.regime == 'TREND_UP') & (t.side == 1)) | ((t.regime == 'TREND_DOWN') & (t.side == -1)), 'with', np.where(t.regime == 'TRANSITION', 'trans', 'against')))
    hr = idx[t.fill_i.values].hour
    t['hour'] = hr
    t['session'] = np.where((hr >= 13) & (hr < 16), 'London+NY', np.where((hr >= 7) & (hr < 13), 'London', np.where((hr >= 16) & (hr < 22), 'NewYork', 'Asia/off')))
    t['macd_ok'] = (np.sign(d.macdh.values[i]) == t.side.values).astype(int)
    o, h, l, c = d.open.values, d.high.values, d.low.values, d.close.values
    rng = np.maximum(h[i] - l[i], 1e-12)
    pos = (c[i] - l[i]) / rng
    body = np.abs(c[i] - o[i])
    lw = np.minimum(c[i], o[i]) - l[i]; uw = h[i] - np.maximum(c[i], o[i])
    bull = ((c[i] > o[i]) & (o[i] <= c[i - 1]) & (c[i] >= o[i - 1]) & (c[i - 1] < o[i - 1])) | ((lw >= 2 * body) & (pos >= 0.6)) | (pos >= 0.67)
    bear = ((c[i] < o[i]) & (o[i] >= c[i - 1]) & (c[i] <= o[i - 1]) & (c[i - 1] > o[i - 1])) | ((uw >= 2 * body) & (pos <= 0.4)) | (pos <= 0.33)
    t['candle_ok'] = np.where(t.side.values == 1, bull, bear).astype(int)
    t['poc_ok'] = poc_side(d, list(i), list(t.side.values))
    t['atr_pct_price'] = d.atr.values[i] / c[i] * 100
    # MTF: H4 trend / H1 struktura / M15
    if h4 is not None:
        tc = idx[i] + pd.Timedelta(hours=1)
        pos4 = np.searchsorted(h4.index.values, tc.values, 'right') - 1
        tr4 = np.where(pos4 >= 0, h4.trend.values[np.maximum(pos4, 0)], 0)
        t['h4_trend'] = tr4
        t['h4_rel'] = np.where(tr4 == 0, 'neutral', np.where(tr4 == t.side.values, 'aligned', 'against'))
    if 'st' in d.columns:
        s = d.st.values[i]
        t['h1_struct'] = s
        t['h1_rel'] = np.where(s == 0, 'mixed', np.where(s == t.side.values, 'aligned', 'against'))
    if m15 is not None:
        tc = idx[i] + pd.Timedelta(hours=1)
        pm = np.searchsorted(m15.index.values, (tc - pd.Timedelta(minutes=15)).values, 'right') - 1
        ok = (pm >= 0) & (tc.values >= m15.index.values[0])
        m = np.where(ok, m15.trend.values[np.maximum(pm, 0)], np.nan)
        t['m15_trend'] = m
        t['m15_rel'] = np.where(np.isnan(m), 'n/a', np.where(m == t.side.values, 'aligned', 'against'))
    return t


def trend_series(df):
    d = df.copy()
    d['ema20'] = d.close.ewm(span=20, adjust=False).mean()
    d['ema50'] = d.close.ewm(span=50, adjust=False).mean()
    d['trend'] = np.where((d.ema20 > d.ema50) & (d.close > d.ema50), 1, np.where((d.ema20 < d.ema50) & (d.close < d.ema50), -1, 0))
    return d


def run_asset(a, tfs=('1h', '4h')):
    t0 = time.time()
    h1 = load(a)
    m15 = None
    if a in ('BTCUSDT', 'ETHUSDT'):
        m = pd.read_csv(D + f'\\{a}_15m.csv', parse_dates=['t'], index_col='t').iloc[:-1]
        m['ema20'] = m.close.ewm(span=20, adjust=False).mean(); m['ema50'] = m.close.ewm(span=50, adjust=False).mean()
        m['trend'] = np.where((m.close > m.ema20) & (m.ema20 > m.ema50), 1, np.where((m.close < m.ema20) & (m.ema20 < m.ema50), -1, 0))
        m.index = m.index + pd.Timedelta(minutes=15)  # bar yopilish vaqti
        m15 = m
    h4 = resample(h1, '4h')
    h4t = trend_series(h4)
    h4t.index = h4t.index + pd.Timedelta(hours=4)  # yopilish vaqti
    res = {}
    for tf in tfs:
        base = h1 if tf == '1h' else h4
        d = prep(base)
        P = pivot_state(d.high.values, d.low.values)
        d['st'] = np.where((P['lsh'] > P['psh']) & (P['lsl'] > P['psl']), 1, np.where((P['lsh'] < P['psh']) & (P['lsl'] < P['psl']), -1, 0))
        allt = []
        for s in STRATS:
            orders = build_orders(d, s, P)
            tr = simulate(d, s, orders)
            f = features(a, tf, d, tr, h4=h4t if tf == '1h' else None, m15=m15 if tf == '1h' else None)
            if not f.empty:
                f['strategy'] = s
                allt.append(f)
            print(a, tf, s, len(orders), 'signals', len(tr), 'trades', round(time.time() - t0), 's', flush=True)
        if allt:
            pd.concat(allt).to_csv(BASE + f'\\trades_{a}_{tf}.csv', index=False)
    print(a, 'done', round(time.time() - t0), 's', flush=True)


if __name__ == '__main__':
    for a in (sys.argv[1:] or list(SRC)):
        run_asset(a)


