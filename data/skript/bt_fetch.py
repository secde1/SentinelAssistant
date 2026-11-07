"""Tarixiy ma'lumot yuklash (faqat ochiq manbalar). Natija: ish/bt/data/*.csv (UTC, open,high,low,close,volume)."""
import requests, pandas as pd, time, os, sys, io
OUT = r'D:\it-agent\data\ish\bt\data'
os.makedirs(OUT, exist_ok=True)
H = {'User-Agent': 'Mozilla/5.0'}

def binance(sym, interval, start='2021-01-01'):
    ms = int(pd.Timestamp(start, tz='UTC').timestamp() * 1000)
    rows = []
    while True:
        r = requests.get('https://data-api.binance.vision/api/v3/klines',
                         params={'symbol': sym, 'interval': interval, 'startTime': ms, 'limit': 1000}, timeout=30)
        d = r.json()
        if not d: break
        rows += d
        ms = d[-1][0] + 1
        if len(d) < 1000: break
    df = pd.DataFrame(rows).iloc[:, :6]
    df.columns = ['t', 'open', 'high', 'low', 'close', 'volume']
    df['t'] = pd.to_datetime(df['t'], unit='ms', utc=True)
    for c in df.columns[1:]: df[c] = df[c].astype(float)
    return df.drop_duplicates('t').set_index('t')

def yahoo(tk, interval='1h', rng='2y'):
    r = requests.get(f'https://query1.finance.yahoo.com/v8/finance/chart/{tk}',
                     params={'interval': interval, 'range': rng}, headers=H, timeout=30)
    j = r.json()['chart']['result'][0]
    q = j['indicators']['quote'][0]
    df = pd.DataFrame({'t': pd.to_datetime(j['timestamp'], unit='s', utc=True), 'open': q['open'], 'high': q['high'],
                       'low': q['low'], 'close': q['close'], 'volume': q['volume']})
    return df.dropna(subset=['open', 'high', 'low', 'close']).drop_duplicates('t').set_index('t')

if __name__ == '__main__':
    for s in ['BTCUSDT', 'ETHUSDT']:
        d = binance(s, '1h'); d.to_csv(f'{OUT}\\{s}_1h.csv'); print(s, '1h', len(d), d.index[0], d.index[-1])
        d = binance(s, '15m', '2024-11-01'); d.to_csv(f'{OUT}\\{s}_15m.csv'); print(s, '15m', len(d), d.index[0], d.index[-1])
    for name, tk in [('EURUSD', 'EURUSD=X'), ('GBPUSD', 'GBPUSD=X'), ('XAUUSD_GCF', 'GC=F'), ('NAS100_NQF', 'NQ=F'), ('SPX500_ESF', 'ES=F')]:
        try:
            d = yahoo(tk); d.to_csv(f'{OUT}\\Y_{name}_1h.csv'); print(name, 'yahoo 1h', len(d), d.index[0], d.index[-1])
        except Exception as e:
            print(name, 'ERR', e)
