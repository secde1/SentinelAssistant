"""Signal hayot sikli va ijro holatlari (V32). Sof funksiyalar — tarmoqqa/MT5 ga chiqmaydi.

Eski `signals.status` (NEW/SENT/CONFIRMED/...) orqaga moslik uchun O'ZGARMAS qoladi; ijro ma'nosi alohida `exec_status` da.
"CONFIRMED" = egasi/AUTO tasdig'i, MT5 zdelkasi EMAS. Bahs ma'qullashi hech qachon "ochilgan zdelka" deb o'qilmaydi.
Eski yozuvlarda `exec_status` bo'sh — `derive_exec_status` uni status + signal_events dan hisoblaydi (bazadagi tarix o'zgarmaydi).
"""
from __future__ import annotations

GENERATED = "GENERATED"
WATCH = "WATCH"
DEBATE_PENDING = "DEBATE_PENDING"
DEBATE_APPROVED = "DEBATE_APPROVED"
DEBATE_REJECTED = "DEBATE_REJECTED"
RISK_VALIDATION_PENDING = "RISK_VALIDATION_PENDING"
EXECUTION_READY = "EXECUTION_READY"
EXECUTED = "EXECUTED"
EXECUTION_REFUSED = "EXECUTION_REFUSED"
INVALIDATED = "INVALIDATED"
EXPIRED = "EXPIRED"

EXEC_STATUSES = (GENERATED, WATCH, DEBATE_PENDING, DEBATE_APPROVED, DEBATE_REJECTED, RISK_VALIDATION_PENDING, EXECUTION_READY,
                 EXECUTED, EXECUTION_REFUSED, INVALIDATED, EXPIRED)

# paper_positions.dataset — to'rt turdagi ma'lumot ARALASHTIRILMAYDI (MT5 DEMO ijrolari alohida jadvallarda: demo_groups/live_trades)
DS_EXECUTABLE = "EXECUTABLE"      # ijro qilinadigan (yoki ijroga yaroqli) paper pozitsiya — strategiya statistikasi shundan
DS_COUNTERFACTUAL = "COUNTERFACTUAL"  # rad etilgan signal (bahs/risk/ijro) — faqat "agar ochilganda" tahlili uchun
DS_TEST = "TEST"                  # TEST signallar va egasi bergan majburiy sinov zdelkalari
DATASETS = (DS_EXECUTABLE, DS_COUNTERFACTUAL, DS_TEST)

# ijro urinishi kelib chiqishi
ORIGIN_AUTO = "auto"              # AUTO rejim: bahs ma'qullagan, egasi tugmasiz
ORIGIN_MANUAL = "manual"          # egasi HA tugmasini bosdi
ORIGIN_FORCED = "forced_test"     # egasi buyrug'i bilan majburiy sinov (bahs o'tkazib yuboriladi) — avtomatik zdelka SANALMAYDI
ORIGIN_TEST = "test"              # TST- signal (haqiqiy ordersiz)

# MT5 so'rovi holati (ijro jurnalida): rad etilgan zdelka hech qachon "order_send" deb yozilmaydi
MT5_NOT_SENT = "NOT_SENT"             # MT5 ga hech narsa yuborilmadi (rad MT5 dan oldin)
MT5_CHECK_REJECTED = "CHECK_REJECTED"  # order_check rad etdi (order_send chaqirilmadi)
MT5_SENT_OK = "SENT_OK"               # order_send muvaffaqiyatli
MT5_SENT_REJECTED = "SENT_REJECTED"   # order_send yuborildi, broker rad etdi
MT5_NA = "N/A"                        # MT5 ijrosi bu urinishda ko'zda tutilmagan (paper rejim)


def derive_exec_status(row: dict, kinds: set[str] | list[str]) -> str:
    """Eski (exec_status bo'sh) yozuv uchun ijro holati: signals.status + signal_events turlari. `row` — signals qatori."""
    if row.get("exec_status"):
        return row["exec_status"]
    k = set(kinds)
    st = row.get("status") or ""
    if st == "WATCH":
        return WATCH
    if st == "EXPIRED":
        return EXPIRED
    if st == "REFUSED":
        return EXECUTION_REFUSED
    if st == "INVALIDATED":
        return EXECUTION_REFUSED if "demo_refused" in k else INVALIDATED
    if st == "REJECTED":
        return DEBATE_REJECTED if "staff_reject" in k and not row.get("decided_by") else EXECUTION_REFUSED
    if st == "CONFIRMING":
        return RISK_VALIDATION_PENDING
    if st == "CONFIRMED":
        if "demo_opened" in k:
            return EXECUTED
        if "demo_refused" in k:
            return EXECUTION_REFUSED
        return EXECUTION_READY  # demo o'chiq: faqat paper tasdiq
    if "staff_approve" in k:
        return DEBATE_APPROVED
    if "staff_reject" in k:
        return DEBATE_REJECTED
    return GENERATED


def derive_origin(row: dict, kinds: set[str] | list[str], has_debate: bool) -> str | None:
    """Eski yozuv uchun kelib chiqish. Faqat dalil bo'lsa; aks holda None (taxmin qilinmaydi)."""
    if row.get("origin"):
        return row["origin"]
    sid = row.get("signal_id") or ""
    if sid.startswith("TST-"):
        return ORIGIN_TEST
    k = set(kinds)
    if "auto_confirm" in k:
        # bahssiz AUTO tasdiq (zona signali) = majburiy sinov; bahsdan o'tgani = avtomatik
        return ORIGIN_AUTO if has_debate else (ORIGIN_FORCED if sid.startswith("ZON-") else ORIGIN_AUTO)
    if "confirmed" in k or "demo_refused" in k or "demo_opened" in k:
        return ORIGIN_MANUAL
    return None
