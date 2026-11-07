"""MT5 market-data diagnostika (faqat o'qish). Savdo ochmaydi, hisob sozlamasini o'zgartirmaydi.
Ishlatish: python mt5_diag.py <terminal64.exe yo'li> [symbol_qidiruv]
Login/parol kerak emas: terminalda saqlangan sessiya ishlatiladi."""
import sys, json
import MetaTrader5 as mt5

path = sys.argv[1]
q = sys.argv[2] if len(sys.argv) > 2 else "BTC"
out = {}
if not mt5.initialize(path=path, timeout=60000):
    print(json.dumps({"init": False, "error": mt5.last_error()})); sys.exit(2)
ti = mt5.terminal_info()
out["init"] = True
out["terminal"] = {"path": ti.path, "connected": ti.connected, "trade_allowed": ti.trade_allowed, "build": ti.build, "company": ti.company}
ai = mt5.account_info()
if ai:
    out["account"] = {"login_set": True, "server": ai.server, "trade_mode": ai.trade_mode, "currency": ai.currency}
else:
    out["account"] = {"login_set": False, "error": mt5.last_error()}
syms = mt5.symbols_get()
out["symbols_total"] = len(syms) if syms else 0
out["matches"] = [s.name for s in (syms or []) if q.upper() in s.name.upper()][:30]
sym = next((n for n in out["matches"] if n.upper().startswith("BTCUSD")), None)
out["chosen"] = sym
if sym:
    mt5.symbol_select(sym, True)
    t = mt5.symbol_info_tick(sym)
    out["tick"] = {"bid": t.bid, "ask": t.ask, "time": t.time} if t else None
    for name, tf in (("H1", mt5.TIMEFRAME_H1), ("M15", mt5.TIMEFRAME_M15)):
        r = mt5.copy_rates_from_pos(sym, tf, 0, 500)
        if r is None or len(r) == 0:
            out[name] = {"bars": 0, "error": mt5.last_error()}
        else:
            out[name] = {"bars": len(r), "first": int(r[0]["time"]), "last": int(r[-1]["time"]), "last_close": float(r[-1]["close"])}
mt5.shutdown()
print(json.dumps(out, ensure_ascii=False, indent=1))
