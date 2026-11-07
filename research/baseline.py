"""1-bosqich: 7 strategiya x 7 instrument x (1h, 4h), 5 yil. Xarajat: gross (0), net (o'lchangan spred), stress (x2)."""
import json, pickle, sys, time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
import lab, costs

OUT = lab.ROOT / "data" / "trading_memory" / "lab"
MODES = {"gross": 0.0, "net": 1.0, "stress": 2.0}


def work(sym: str) -> dict:
    res = {}
    htf = lab.HTF(lab.load(sym, "4h"))
    for tf in ("1h", "4h"):
        c = lab.load(sym, tf)
        for sid, spec in lab.STRATEGIES.items():
            for mode, mult in MODES.items():
                tr = lab.run_tagged(spec, c, htf if tf == "1h" else None, costs.COSTS[sym], mult=mult)
                cut = int(len(c) * 0.7)
                t_cut = c[cut].ts
                ins = [t for t in tr if t.ts < t_cut]
                oos = [t for t in tr if t.ts >= t_cut]
                res[f"{sym}|{tf}|{sid}|{mode}"] = {"all": lab.stats(tr), "is": lab.stats(ins), "oos": lab.stats(oos)}
                with open(OUT / f"trades_{sym}_{tf}_{sid}_{mode}.pkl", "wb") as f:
                    pickle.dump(tr, f)
    return res


if __name__ == "__main__":
    t0 = time.time()
    allres = {}
    with ProcessPoolExecutor(7) as ex:
        for r in ex.map(work, list(costs.COSTS)):
            allres.update(r)
    (OUT / "baseline.json").write_text(json.dumps(allres, indent=1))
    print("tayyor", len(allres), round(time.time() - t0), "s")
