"""V23: yangi nomzodlar (LIQ-SWEEP, TL-BOUNCE, TL-BREAK, SNR-REJ) x 7 instrument x (1h, 4h), 5 yil. gross va net xarajat."""
import json, pickle, sys, time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
import lab, costs

OUT = lab.ROOT / "data" / "trading_memory" / "lab"
NEW = ["LIQ-SWEEP", "TL-BOUNCE", "TL-BREAK", "SNR-REJ"]
MODES = {"gross": 0.0, "net": 1.0, "stress": 2.0}


def work(sym: str) -> dict:
    res = {}
    htf = lab.HTF(lab.load(sym, "4h"))
    for tf in ("1h", "4h"):
        c = lab.load(sym, tf)
        cut = int(len(c) * 0.7)
        for sid in NEW:
            for mode, mult in MODES.items():
                tr = lab.run_tagged(lab.STRATEGIES[sid], c, htf if tf == "1h" else None, costs.COSTS[sym], mult=mult)
                t_cut = c[cut].ts
                res[f"{sym}|{tf}|{sid}|{mode}"] = {"all": lab.stats(tr), "is": lab.stats([t for t in tr if t.ts < t_cut]),
                                                   "oos": lab.stats([t for t in tr if t.ts >= t_cut])}
                with open(OUT / f"trades_{sym}_{tf}_{sid}_{mode}.pkl", "wb") as f:
                    pickle.dump(tr, f)
    return res


if __name__ == "__main__":
    t0 = time.time()
    allres = {}
    with ProcessPoolExecutor(7) as ex:
        for r in ex.map(work, list(costs.COSTS)):
            allres.update(r)
    (OUT / "baseline_v23.json").write_text(json.dumps(allres, indent=1))
    print("tayyor", len(allres), round(time.time() - t0), "s")
