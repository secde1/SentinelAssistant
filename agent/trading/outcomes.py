"""Qog'oz savdo natijasini kuzatish. Tahlil — avtomatik bitim EMAS: kuzatuv faqat gipotetik kirish sharti bajarilgandan
keyin boshlanadi. Asl tahlil (kirish/SL/TP) hech qachon o'zgartirilmaydi.

Holatlar: PENDING -> ACTIVE_SIMULATION -> TP_HIT | SL_HIT | EXPIRED; yoki NOT_TRIGGERED (muddat o'tdi), CANCELLED
(kirishdan oldin bekor qilish sharti), AMBIGUOUS_DATA (bir sham ichida ketma-ketlikni aniqlab bo'lmadi).

Ijro modeli (konservativ):
  • shamlar bid narxi deb olinadi; long kirish/short chiqish ask = bid + spread bilan tekshiriladi;
  • stop-kirish gap bilan o'tib ketsa — ochilish narxida (yomonroq), limit-kirish — o'z darajasida (yaxshilanmaydi);
  • SL gap bilan o'tib ketsa — ochilish narxida chiqiladi (yomonroq);
  • komissiya R dan ayiriladi (cost_r);
  • bir shamda kirish va chiqish/yoki TP va SL ikkalasi bo'lsa — 1 daqiqalik shamlar bilan aniqlanadi; bo'lmasa
    narx uzluksizligidan aniq xulosa chiqmasa — AMBIGUOUS_DATA (hech qachon yutuq deb hisoblanmaydi).
"""
from __future__ import annotations

import copy
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Callable

from .data import TF_SECONDS, Candle, DataUnavailable

log = logging.getLogger(__name__)

PENDING, ACTIVE, NOT_TRIGGERED, TP_HIT, SL_HIT, EXPIRED, CANCELLED, AMBIGUOUS = (
    "PENDING", "ACTIVE_SIMULATION", "NOT_TRIGGERED", "TP_HIT", "SL_HIT", "EXPIRED", "CANCELLED", "AMBIGUOUS_DATA")
FINAL = {NOT_TRIGGERED, TP_HIT, SL_HIT, EXPIRED, CANCELLED, AMBIGUOUS}


@dataclass
class Scenario:
    analysis_id: str
    direction: str
    entry_type: str
    entry: float
    sl: float
    tp: float
    invalidation: dict
    data_end: datetime  # tahlil qilingan oxirgi shamning yopilishi
    published_at: datetime
    valid_until: datetime
    max_hold_bars: int
    timeframe: str
    spread: float
    commission: float

    @property
    def long(self) -> bool:
        return self.direction == "LONG"


@dataclass
class SimState:
    status: str = PENDING
    entry_time: datetime | None = None
    entry_price: float | None = None
    exit_time: datetime | None = None
    exit_price: float | None = None
    r_multiple: float | None = None
    cost_r: float | None = None
    bars_held: int = 0
    last_bar_ts: datetime | None = None
    note: str = ""
    events: list[dict] = field(default_factory=list)

    def move(self, to: str, ts: datetime, price: float | None, detail: str) -> None:
        self.events.append({"from": self.status, "to": to, "ts": ts, "price": price, "detail": detail})
        self.status = to


class _NeedFine(Exception):
    pass


def _entry_hit(sc: Scenario, b: Candle) -> bool:
    s = sc.spread
    return {"buy_stop": b.high + s >= sc.entry, "buy_limit": b.low + s <= sc.entry,
            "sell_stop": b.low <= sc.entry, "sell_limit": b.high >= sc.entry, "next_open": True}[sc.entry_type]


def _fill_price(sc: Scenario, b: Candle) -> float:
    s = sc.spread
    if sc.entry_type == "next_open":
        return b.open + s if sc.long else b.open
    if sc.entry_type == "buy_stop" and b.open + s > sc.entry:
        return b.open + s  # gap — yomonroq narx
    if sc.entry_type == "sell_stop" and b.open < sc.entry:
        return b.open
    return sc.entry


def _exits(sc: Scenario, b: Candle) -> tuple[bool, bool]:
    s = sc.spread
    if sc.long:
        return b.low <= sc.sl, b.high >= sc.tp
    return b.high + s >= sc.sl, b.low + s <= sc.tp


def _invalidated(sc: Scenario, b: Candle) -> bool:
    inv = sc.invalidation or {}
    lvl = inv.get("level")
    if lvl is None:
        return False
    return b.close < lvl if inv.get("type") == "close_below" else b.close > lvl


def _finish(sc: Scenario, st: SimState, status: str, ts: datetime, price: float, detail: str) -> None:
    risk = abs(st.entry_price - sc.sl) if st.entry_price is not None else abs(sc.entry - sc.sl)
    gross = ((price - st.entry_price) if sc.long else (st.entry_price - price)) / risk if risk else 0.0
    cost = sc.commission * (st.entry_price + price) / risk if risk else 0.0
    st.exit_time, st.exit_price = ts, price
    st.r_multiple, st.cost_r = round(gross - cost, 4), round(cost, 4)
    st.move(status, ts, price, detail)


def _exit_price_sl(sc: Scenario, b: Candle) -> float:
    if sc.long and b.open <= sc.sl:
        return b.open  # gap pastga
    if not sc.long and b.open + sc.spread >= sc.sl:
        return b.open + sc.spread
    return sc.sl


def _process_bar(sc: Scenario, st: SimState, b: Candle, fine_level: bool) -> None:
    """Bitta sham. Ketma-ketlik noaniq bo'lsa — _NeedFine (yuqori daraja mayda shamlarga bo'ladi)."""
    if st.status == PENDING:
        if b.ts >= sc.valid_until:
            st.move(NOT_TRIGGERED, sc.valid_until, None, "kirish sharti amal muddati ichida bajarilmadi")
            return
        if not _entry_hit(sc, b):
            if _invalidated(sc, b):
                st.move(CANCELLED, b.end, b.close, f"kirishdan oldin bekor qilish sharti: {sc.invalidation.get('text')}")
            return
        fill = _fill_price(sc, b)
        st.entry_time, st.entry_price = b.ts, fill
        st.move(ACTIVE, b.ts, fill, f"gipotetik kirish sharti bajarildi ({sc.entry_type})")
        sl_hit, tp_hit = _exits(sc, b)
        if not (sl_hit or tp_hit):
            st.bars_held = 1
            return
        gapped = fill != sc.entry or sc.entry_type == "next_open"
        stop_entry = sc.entry_type in ("buy_stop", "sell_stop")
        limit_entry = sc.entry_type in ("buy_limit", "sell_limit")
        # Narx uzluksizligi: stop-kirishda TP kirishdan keyin bo'lishi shart; limit-kirishda SL ham shunday.
        if tp_hit and not sl_hit and (stop_entry or gapped):
            _finish(sc, st, TP_HIT, b.ts, sc.tp, "kirish shamining o'zida TP (ketma-ketlik aniq)")
            return
        if sl_hit and not tp_hit and (limit_entry or gapped):
            _finish(sc, st, SL_HIT, b.ts, _exit_price_sl(sc, b), "kirish shamining o'zida SL (ketma-ketlik aniq)")
            return
        raise _NeedFine("kirish va chiqish bir shamda — ketma-ketlik noaniq")
    if st.status == ACTIVE:
        sl_hit, tp_hit = _exits(sc, b)
        if sl_hit and tp_hit:
            raise _NeedFine("TP va SL bir shamda")
        if sl_hit:
            _finish(sc, st, SL_HIT, b.ts, _exit_price_sl(sc, b), "virtual SL")
            return
        if tp_hit:
            _finish(sc, st, TP_HIT, b.ts, sc.tp, "virtual TP")
            return
        if not fine_level:
            st.bars_held += 1
            if st.bars_held >= sc.max_hold_bars:
                _finish(sc, st, EXPIRED, b.end, b.close, f"{sc.max_hold_bars} sham ichida TP/SL bo'lmadi")


def simulate(sc: Scenario, bars: list[Candle], st: SimState | None = None,
             fine: Callable[[datetime, datetime], list[Candle]] | None = None) -> SimState:
    """bars — tahlildan keyingi YOPILGAN shamlar (o'sish tartibida). Holat bosqichma-bosqich davom ettiriladi."""
    st = st or SimState()
    for b in bars:
        if st.status in FINAL:
            break
        if b.ts < sc.data_end or (st.last_bar_ts is not None and b.ts <= st.last_bar_ts):
            continue
        before = copy.deepcopy(st)
        partial = b.ts < sc.published_at < b.end
        try:
            if partial:
                raise _NeedFine("e'lon vaqti sham ichida — e'londan oldingi harakat hisobga olinmasligi kerak")
            _process_bar(sc, st, b, fine_level=False)
        except _NeedFine as why:
            st = before
            sub = None
            if fine is not None:
                try:
                    sub = fine(max(b.ts, sc.published_at) if partial else b.ts, b.end)
                except DataUnavailable:
                    sub = None
            covered = bool(sub) and sub[-1].end >= b.end - timedelta(seconds=60) and \
                sub[0].ts <= (max(b.ts, sc.published_at) if partial else b.ts) + timedelta(seconds=60)
            if not covered:
                if partial and not _touches(sc, st, b):
                    pass  # e'londan oldingi daqiqalar baribir hech qanday darajaga tegmagan
                else:
                    st.move(AMBIGUOUS, b.ts, None, f"{why}; mayda (1m) ma'lumot yo'q — ketma-ketlik aniqlanmadi")
                    st.last_bar_ts = b.ts
                    break
            else:
                pre = st.status
                try:
                    for fb in sub:
                        if st.status in FINAL:
                            break
                        _process_bar(sc, st, fb, fine_level=True)
                except _NeedFine as why2:
                    st.move(AMBIGUOUS, b.ts, None, f"{why2} (1m shamda ham) — natija noaniq")
                    st.last_bar_ts = b.ts
                    break
                if st.status == ACTIVE:
                    if pre == ACTIVE:
                        st.bars_held += 1
                    else:
                        st.bars_held = 1
                    if st.bars_held >= sc.max_hold_bars:
                        _finish(sc, st, EXPIRED, b.end, b.close, f"{sc.max_hold_bars} sham ichida TP/SL bo'lmadi")
        st.last_bar_ts = b.ts
    return st


def _touches(sc: Scenario, st: SimState, b: Candle) -> bool:
    if st.status == PENDING:
        return _entry_hit(sc, b) or _invalidated(sc, b) or b.ts >= sc.valid_until
    sl_hit, tp_hit = _exits(sc, b)
    return sl_hit or tp_hit


# ------------------------------------------------------------------------------------------------ baza bilan
def scenario_from_row(row: dict, settings, published_at: datetime | None) -> Scenario:
    inv = json.loads(row["invalidation"]) if isinstance(row["invalidation"], str) else (row["invalidation"] or {})
    data_end = datetime.fromisoformat(row["data_ts"])
    return Scenario(row["analysis_id"], row["direction"], row["entry_type"], row["entry"], row["sl"], row["tp"], inv,
                    data_end, published_at or datetime.fromisoformat(row["created_at"]),
                    datetime.fromisoformat(row["valid_until"]), int(row["max_hold_bars"]), row["timeframe"],
                    settings.spread_price(row["symbol"], row["entry"]), settings.commission_rate(row["symbol"]))


def state_from_row(row: dict | None) -> SimState:
    if not row:
        return SimState()

    def dt(x):
        return datetime.fromisoformat(x) if x else None
    note = json.loads(row["note"]) if row.get("note") and row["note"].startswith("{") else {}
    return SimState(row["status"], dt(row["entry_time"]), row["entry_price"], dt(row["exit_time"]), row["exit_price"],
                    row["r_multiple"], row["cost_r"], int(note.get("bars_held", 0)), dt(row["last_bar_ts"]),
                    note.get("text", ""))


def update_one(db, market, settings, row: dict) -> tuple[str | None, str]:
    """Bitta tahlilni yangilaydi. -> (yangi yakuniy/faol holat yoki None, izoh)."""
    pub = db.one("SELECT sent_at FROM publications WHERE ref=? AND kind='analysis' AND status='sent' "
                 "ORDER BY sent_at LIMIT 1", (row["analysis_id"],))
    published_at = datetime.fromisoformat(pub["sent_at"]) if pub and pub.get("sent_at") else None
    sc = scenario_from_row(row, settings, published_at)
    cur = db.outcome(row["analysis_id"])
    st = state_from_row(cur)
    if cur is None:
        db.upsert_outcome(row["analysis_id"], status=PENDING, note=json.dumps({"bars_held": 0}))
        db.add_event(row["analysis_id"], None, PENDING, sc.published_at.isoformat(), None, "kuzatuv boshlandi")
    if st.status in FINAL:
        return None, "yakunlangan"
    start = (st.last_bar_ts + timedelta(seconds=TF_SECONDS[sc.timeframe])) if st.last_bar_ts else sc.data_end
    try:
        bars = market.after(row["symbol"], row["timeframe"], start)
    except DataUnavailable as exc:
        db.warn(row["symbol"], row["timeframe"], "outcome_data", str(exc))
        return None, f"ma'lumot yo'q: {exc}"
    before_status = st.status
    st.events = []
    st = simulate(sc, bars, st, fine=lambda a, b: market.fine(row["symbol"], a, b))
    for ev in st.events:
        db.add_event(row["analysis_id"], ev["from"], ev["to"], ev["ts"].isoformat() if ev["ts"] else None, ev["price"],
                     ev["detail"])
    db.upsert_outcome(row["analysis_id"], status=st.status,
                      entry_time=st.entry_time.isoformat() if st.entry_time else None, entry_price=st.entry_price,
                      exit_time=st.exit_time.isoformat() if st.exit_time else None, exit_price=st.exit_price,
                      r_multiple=st.r_multiple, cost_r=st.cost_r,
                      last_bar_ts=st.last_bar_ts.isoformat() if st.last_bar_ts else None,
                      note=json.dumps({"bars_held": st.bars_held, "text": st.note}, ensure_ascii=False),
                      data_source=market.provider_for(row["symbol"]).name)
    return (st.status if st.status != before_status else None), ""
