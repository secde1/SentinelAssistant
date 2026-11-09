# IMPLEMENTATION-REPORT — ijro quvuri ishonchliligi (V32), 2026-11-09

Maqsad: `EXECUTION-INVESTIGATION-2026-11-09.md` dagi to'rt tavsiyani amalga oshirish (holatlar, SIG pre-tekshiruvi, paper ajratish, ijro jurnali) + veb hisoblagichlar/voronka + regressiya testlari.
**Bu ishonchlilik va hisob-kitob o'zgarishi, strategiya o'zgarishi EMAS.** Ishlab turgan agent/dashboard qayta ishga tushirilmadi, production'ga avtomatik joylanmadi.

## 0. O'zgarmagani (kod bilan tasdiqlangan)
Strategiyalar, kirish shartlari, risk chegaralari (1% / 5% kunlik / 8% minimal lot / max_groups), minimal R/R (1.5), bahs ovoz qoidalari (≥3/4 yoki zona ≥2/4 + DIR-1), lot formulasi (`autotrade.plan_group` — **bitta qatorga ham tegilmadi**), MT5 ijro qoidalari (`DemoTrader.open`, order_check -> order_send, DEMO tekshiruvi). Yagona qo'shimcha MT5 tomondagi o'zgarish: `symbol_spec` natijasiga faqat-o'qiladigan `quote_age_s` maydoni qo'shildi.

## 1. Oldindan: arxitektura, ta'sirlanadigan jadval/API, zaxira
- O'qildi: `EXECUTION-INVESTIGATION-2026-11-09.md`, `agent/trading/signals.py`, `autotrade.py`, `db.py`, `mt5_trade.py`, `agent/zones/trade.py`, `agent/dashboard/desk_api.py`, `server.py`, veb sahifalar.
- Ta'sirlanadigan jadvallar: `signals` (+`exec_status`, +`origin`), `paper_positions` (+`dataset`), yangi `execution_audit`. API: `/api/desk/signals`, `/api/desk/signal`, `/api/desk/positions`, `/api/desk/dashboard` (KPI), yangi `/api/desk/execution`.
- **Zaxira** (o'zgartirishdan oldin): `backups/pre-exec-improve-20261109-184407.safe.db` (SQLite backup API, `integrity_check=ok`, 65 signal) + `backups/pre-exec-improve-code-20261109-184407.zip` (agent, tests, web/src). `backups/` .gitignore'da.

## 2. Nima o'zgardi
| # | Talab | Amalga oshirilishi | Fayl |
|---|---|---|---|
| 1 | Holatlar | Yangi `signals.exec_status` (GENERATED, WATCH, DEBATE_PENDING/APPROVED/REJECTED, RISK_VALIDATION_PENDING, EXECUTION_READY, EXECUTED, EXECUTION_REFUSED, INVALIDATED, EXPIRED) va `origin` (auto / manual / forced_test / test). **EXECUTED faqat MT5 DEMO order_send muvaffaqiyatli bo'lgandan keyin.** Bahs ma'qullashi faqat DEBATE_APPROVED. | `agent/trading/lifecycle.py` (yangi), `signals.py` |
| 1a | Orqaga moslik | Eski `status` ustuni va qiymatlari o'zgarmadi (`ACTIVE_STATES`, zona kodi, eski API iste'molchilari). Faqat YANGI ijro-rad holatida eski `CONFIRMED` o'rniga `REFUSED` yoziladi. Eski qatorlar (exec_status NULL) uchun holat o'qishda `derive_exec_status` bilan hisoblanadi — **tarix bazada qayta yozilmaydi**. | `lifecycle.py`, `desk_api.py` |
| 2 | SIG pre-tekshiruv | `publish()` tugmadan OLDIN `precheck()` -> `_group_plan()` (`_open_group` bilan AYNAN bir xil kod: kunlik zarar, guruhlar, takroriy pozitsiya, korrelyatsiya, balans, **kotirovka yangiligi (yangi)**, SL≥ATR, R/R, spred, minimal lot/maks risk). Rad bo'lsa: tugmasiz xabar + aniq sabab, holat `REFUSED`, jurnal. Ijro paytida (`_confirm_flow`: `revalidate` + `_open_group` -> `_group_plan`) hammasi QAYTA tekshiriladi. | `signals.py` |
| 3 | Paper ajratish | `paper_positions.dataset`: EXECUTABLE / COUNTERFACTUAL / TEST. Rad etilgan ijro -> COUNTERFACTUAL (egasiga natija xabari yuborilmaydi); majburiy sinov va TST -> TEST. `stats()`, dashboard `paper_r`, xodimlar `strategy_stats` faqat EXECUTABLE. MT5 DEMO ijrolari alohida jadvallarda (`demo_groups`/`live_trades`) — aralashmaydi. | `signals.py`, `db.py`, `desk_api.py`, `staff/context.py` |
| 4 | Ijro jurnali | Yangi `execution_audit`: signal, instrument, UTC vaqt, bahs natijasi, risk natijasi, qaror, to'xtagan bosqich, aniq sabab, `mt5_request` (NOT_SENT / CHECK_REJECTED / SENT_OK / SENT_REJECTED / N/A), `mt5_retcode`, kelib chiqish. Rad etilgan zdelka hech qachon order_send deb yozilmaydi (`NOT_SENT`); order_check rad etsa `CHECK_REJECTED`. `signal_events` ham to'ldirilib turadi. | `signals.py`, `db.py` |
| 5 | Dashboard | `/api/desk/execution` (bugun-Toshkent / 7 kun / hammasi): Generated, Debate Approved/Rejected, Risk Approved/Refused, Execution Ready, MT5 Executed, Manual Test Orders, Expired/Invalidated + konversiya voronkasi + "qayerda to'xtadi" + aniq sabablar. Veb: signallar sahifasida "Ijro voronkasi", ijro holati ustuni, signal tafsilotida ijro jurnali; Pozitsiyalarda Paper (ijro) / Counterfactual / Sinov tablari. | `desk_api.py`, `server.py`, `web/src/...` |
| — | Majburiy sinov | `ZoneTrader.execute(force)` endi `auto_confirm(origin="forced_test")`: sinov zdelka "MT5 Executed" ga emas, "Manual Test Orders" ga tushadi. | `agent/zones/trade.py` |

Ijro yo'lidagi tartib o'zgarishi: avval paper ochilar, keyin demo; endi avval demo natijasi, keyin paper (dataset natijaga bog'liq bo'lishi uchun).

## 3. Testlar va tekshiruv natijalari
- **Yangi:** `tests/test_exec_pipeline.py` — 33 test (parametrlar bilan): bahs ma'qullashi ≠ ijro; bahsdan keyingi risk rad (MT5 ga yuborilmaydi); eskirgan kotirovka; spred; minimal lot riski (ikki variant); muddati o'tgan signal; narx siljishi (revalidate); SIG pre-tekshiruv tugmani olib tashlaydi va sababni aytadi, ijro paytida qayta tekshiradi; paper ajratish + statistika; counterfactual xabar yubormaydi; migratsiya (dalilga ko'ra to'ldirish, tarix o'zgarmaydi, idempotent); eski holatlar -> aniq holat (14 hol); qo'lda/avto/majburiy kelib chiqish; ijro jurnali aniqligi (SENT_OK 10009, CHECK_REJECTED 10019, NOT_SENT); takroriy tasdiq (gather bilan parallel) = aniq 1 guruh; ochiq pozitsiya bor simvolga ikkinchi ijro bloklanadi; API hisoblagichlar (majburiy sinov avtomatikka qo'shilmaydi); pozitsiyalar API to'plamlari.
- **To'liq to'plam:** `455 passed, 2 skipped` (oldin 422; +33). `pyflakes agent tests research` toza. Veb: `tsc --noEmit`, `eslint`, `next build` toza. `python -m agent --check`: "hammasi joyida".
- **Baza yaxlitligi (production'ning NUSXASIDA migratsiya, productionga tegilmadi):** `integrity_check=ok`, FK xatosi 0. Tarixiy jadvallar (signals 66, signal_events 182, demo_groups 1, live_trades 8, staff_decisions 13, paper_positions 10, mt5_positions 9, analyses 32, outcomes 11) migratsiyadan oldin va keyin SHA-256 bir xil. Paper to'plami: 7 COUNTERFACTUAL + 3 TEST (ZON-0007 TEST sifatida), eski qatorlarda `exec_status` NULL qoldi.
- **Jonli ma'lumotda API:** nusxada `execution()` bugun uchun: generated 20, debate_rejected 12, debate_approved 0, risk_refused 5, mt5_executed 0, manual_test_orders 1 (ZON-0007), owner_override_after_reject 5 — sizning xulosangiz (avtomatik ijro 0, yagona zdelka majburiy sinov) bilan mos. SIG-0005, ZON-0002/3/4 -> EXECUTION_REFUSED; ZON-0007 -> EXECUTED + forced_test.
- **MT5 ga buyurtma yuborilmadi:** testlarda soxta trader; `mt5_demo_trades.jsonl` 25 qator (o'zgarmadi); mavjud pozitsiyalarga tegilmadi.

### Diqqat: testlardagi o'zgarishlar va kuzatuvlar (yashirilmaydi)
1. **Bitta mavjud test ataylab o'zgartirildi:** `test_demo_refusals_are_reported_and_never_hidden` eski noaniq xulqni (rad etilgan ijro = `CONFIRMED`, paper ochiq) tasdiqlardi; endi `REFUSED` / `EXECUTION_REFUSED` / paper `COUNTERFACTUAL` ni tekshiradi. Xabar matni "MT5 demo ochilmadi" saqlandi.
2. **Oldindan mavjud vaqtga bog'liq test nuqsoni tuzatildi:** `ZoneTrader._cooldown` haqiqiy `datetime.now` ni test soatiga (qotirilgan) solishtirardi; test faqat devor soati 10:00 UTC dan <2 soat o'tganda o'tardi (soat 13:52 UTC da yiqildi). Endi servis soati `sv.svc.clock()` (jonlida — hozirgi vaqt, xulq bir xil).
3. `tests/test_dashboard.py::test_api_requires_session_and_local_host` uchta ketma-ket ishga tushirishda bir marta `ConnectionAbortedError (WinError 10053)` berdi (qolganda o'tdi, to'liq to'plamda o'tdi). Bu o'zgartirishlarga bog'liq emas (qurilma API/DELETE 405 yo'li); alohida o'rganilmagan.

## 4. Joylash (deployment) — sizning qaroringiz
Hech narsa avtomatik joylanmadi. Faol bo'lishi uchun: (a) agentni qayta ishga tushirish (`agentctl`) — birinchi ishga tushishda `TradingDB._migrate()` ustunlarni qo'shadi va `dataset`ni dalilga ko'ra to'ldiradi (zaxira tayyor); (b) dashboardni qayta ishga tushirish (yangi marshrut va veb build `web/out`). Dashboard hozirgi (eski) kod bilan yangi bazani ham o'qiy oladi, lekin `/api/desk/execution` faqat yangisida bor. Orqaga qaytarish: zaxira zip + `.safe.db`.
O'zgarishlar `ui-terminal` branch'ida, commit qilinmagan.

## 5. Qolgan masalalar / cheklovlar
1. **Eski yozuvlarda kelib chiqish va risk natijasi dalilga asoslangan taxmin:** `forced_test` "bahssiz `auto_confirm` + ZON" qoidasi bilan; `risk_approved/refused` eski yozuvlarda `demo_opened/demo_refused` hodisalaridan. Yangi yozuvlarda aniq maydonlar bor.
2. **Kotirovka yoshi** `server_offset` ga bog'liq (MT5 server vaqti - UTC); siljish aniqlanmasa tekshiruv o'tkazib yuboriladi (taxmin qilinmaydi). Yangi sozlama `signals.max_quote_age_s` (standart 600 s) — bu yangi rad sababi (talab bo'yicha), sozlamani qo'lda o'zgartirish mumkin. Kam likvid ekzotik juftlikda tik 10 daqiqadan ko'p kelmasligi mumkin — shunda signal rad etiladi.
3. **Pre-tekshiruv faqat `sizing=risk` va demo yoqilgan** holatda (hozirgi sozlama). Eski qat'iy-lot yo'li (`sizing=fixed`) o'zgarmadi.
4. **Telegram:** ijro qilib bo'lmaydigan SIG signal endi tugmasiz, sabab bilan baribir yuboriladi ("sabab aniq ko'rinsin" talabi). Xabarlar sonini kamaytirish alohida qaror.
5. Zona signallari o'zining `_plan_ok` pre-tekshiruvini ishlatadi (o'zgarmadi); `publish` ularni takroran tekshirmaydi (`buttons=False`).
6. `exec_counters` har sabab turi uchun alohida so'rov bajaradi (hozirgi hajmda — millisekundlar; signallar o'n minglab bo'lganda indeks/umumiy so'rov kerak bo'ladi).
7. Hali kuzatilmagan: debate-ma'qullagan birinchi **avtomatik** zdelka jonli oqimda (ilgari ham 0 edi); yangi kod jonli MT5 bilan ishlab ko'rilmagan (faqat soxta trader va bazaning nusxasi bilan).
8. Oldingi hisobotdagi qolgan tavsiyalar bu ishga kirmadi: zona universumini 51$ balansga moslash va bahs 12/12 rad etishini tahlil qilish (strategiya/universum qarori — sizdan).
