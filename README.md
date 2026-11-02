# SENTINAL AI — avtonom IT-agent va shaxsiy yordamchi (Telegram + Claude)

Agent Telegramdan topshiriq oladi va ishni o'zi bajaradi: Windows serverda va u yerdan ulanadigan qurilmalarda
(Windows/AD, Mikrotik, UniFi, Zabbix, NVR, ESXi/Hyper-V, printerlar). Natijani kod tekshirgan holat bilan qisqa
hisobot qilib qaytaradi. Shaxsiy ishlarni ham bajaradi: Word/Excel/PDF o'qish va yaratish, fayllarni saralash,
internetdan qidirish, hisob-kitob, xat tayyorlash, ovozli xabarni tushunish. Instagram Reels uchun video tayyorlab,
egasining tasdig'iga yuboradi. Takrorlanadigan ishni skillga aylantiradi, shuning uchun vaqt o'tgani sari kuchayib boradi.

> **Hozirgi o'rnatish (shu kompyuter):**
>
> - loyiha `D:\it-agent`, ma'lumotlar `D:\it-agent\data` (`AGENT_HOME`);
> - agent `t.admin` hisobida oddiy jarayon sifatida ishlaydi. Uni **`AgentRestart`** rejalashtirilgan vazifasi
>   ishga tushiradi (1-bo'lim);
> - NSSM xizmati o'rnatilmagan. Yangi serverga o'rnatish 2-bo'limda.

---

## Arxitektura

```
Telegram (faqat ALLOWED_CHAT_ID)            Ustki panel — oynacha (127.0.0.1 + token)
            │                                          │
            └───────────────►  AGENT CORE  ◄───────────┘
                     loop.py: tizim prompti + xotira + ReAct tool-loop
                     (model tool chaqiradi → kod bajaradi → natija → keyingi qadam)
                     model: Claude Agent SDK → rasmiy Claude Code CLI (1a-bo'lim)
                                  │
        ┌─────────────────────────┼───────────────────────────┐
  TOOL REGISTRY             PERMISSIONS                  EXECUTION LOOP
  tools/ — 19 ta tool       gate.py: o'qish / o'zgartirish /    tasks.py: fon topshiriqlar,
  (+ WebSearch/WebFetch)    tasdiq / blok; xavfli amal →        navbat, progress, /stop,
                            Telegramda "ha"/"yo'q"              vaqt chegaralari
                                  │
  INTEGRATIONS: PowerShell 7 · WinRM · SSH (netmiko, paramiko) · HTTP API · Telegram Business · veb-qidiruv
                                  │
  RESULT VERIFICATION — verification.py: yakuniy "Holat: ..." ni model emas, kod faktlari belgilaydi
                                  │
  jurnal (.md + .jsonl, maxfiy qiymatlar *** bilan)  →  Telegramga qisqa hisobot
```

| Blok | Fayllar | Vazifasi |
|---|---|---|
| Telegram Bot | `agent/bot.py`, `agent/telegram_api.py` | ruxsat (chat/user ID), buyruqlar, tasdiq/savol/parol oqimi, tugmalar, ovozli xabar, fayl va video yuborish |
| Agent Core | `agent/loop.py`, `agent/memory.py`, prompt fayllari | tizim promptini yig'ish, xotira va skillarni tanlab yuklash, tool-loop, yakuniy nazorat |
| Tool Registry | `agent/tools/` | agent tool'lari: spetsifikatsiya + bajaruvchi; Claude Code'ga `mcp__it__*` sifatida beriladi |
| Execution Loop | `agent/tasks.py`, `agent/loop.py` | har topshiriq alohida asyncio task va alohida CLI sessiya; bir vaqtda `MAX_CONCURRENT_TASKS` |
| Integrations | `agent/tools/powershell.py`, `ssh.py`, `http_api.py`, `agent/business.py` | PowerShell/WinRM, SSH, HTTP API, Telegram Business |
| Permissions | `agent/gate.py`, `agent/pending.py`, `agent/redact.py`, `agent/inventory.py` | xavf darajasi, bir martalik tasdiqlar, maxfiy qiymatlarni yashirish, placeholderlar |
| Result Verification | `agent/verification.py` | `SUCCESS` / `PARTIAL` / `NEEDS_SETUP` / `NEEDS_AUTH` / `FAILED` / `BLOCKED` |
| Proaktiv ishlar | `agent/proactive.py` | Zabbix kuzatuvi, kunlik tekshiruv, kunlik Reels tayyorlash |
| Reels studiyasi | `agent/studio/`, `agent/tools/reels.py` | skript → ovoz → video → sifat nazorati → Telegramda tasdiq |
| Ustki panel | `agent/control.py`, `agent/panel.py`, `oynacha.cmd` | kompyuterning o'zidan kuzatish va boshqarish |

### Tizim prompti qatlamlari

`loop.py` har topshiriqda promptni shu tartibda yig'adi. Hammasi keshlanadi, shuning uchun har safar to'liq token
sarflanmaydi.

| # | Fayl | Nima | Kim o'zgartiradi |
|---|---|---|---|
| 1 | `SYSTEM_PROMPT.md` | o'zgarmas qoidalar: kimga xizmat qiladi, ish tartibi, xavfsizlik, hisobot va `Holat:` qatori | faqat egasi (agent uchun gate'da **blok**) |
| 2 | `SHAXSIYAT.md` | xarakter: mustaqil fikr, his-tuyg'u uslublari, egasiga moslashish, boshqalar bilan muomala | egasi |
| 3 | `shaxsiyat.json` | xarakter darajalari (0–100) va bayroqlar; `agent/personality.py` matnga aylantiradi. Fayl buzilsa — e'tiborsiz qoldiriladi | egasi |
| 4 | `STUDIYA.md` | Reels muharrirlik qoidalari (faqat `REELS_ENABLED=1` bo'lsa qo'shiladi) | egasi |
| 5 | `agent/prompt_texnik.md` | tool'lar bo'yicha texnik eslatmalar (`{home}`, `{python}` o'rniga haqiqiy yo'llar qo'yiladi) | dasturchi |

Bulardan keyin xotira (`data\xotira\`) va mos skillar qo'shiladi (8-bo'lim).

---

## 1. Hozirgi o'rnatish: ishga tushirish, to'xtatish, loglar

Agent `D:\it-agent\.venv\Scripts\python.exe -m agent` jarayoni sifatida ishlaydi (ishchi papka `D:\it-agent`).

**Qayta ishga tushirish** (`.env`, kod yoki prompt o'zgargandan keyin):

```powershell
schtasks /run /tn AgentRestart
```

Vazifa `t.admin` hisobida `data\skript\restart_agent.bat` ni bajaradi:

1. 25 soniya kutadi. Agent o'zi qayta ishga tushirganda javobini yuborib ulgurishi uchun shunday qilingan.
2. Barcha `-m agent` jarayonlarini to'xtatadi.
3. Yangisini kichraytirilgan oynada ochadi.
4. Konsol chiqishini `data\jurnal\console.log` ga, ishga tushirish vaqtini `data\jurnal\restart.log` ga yozadi.

> **Ishlayotgan topshiriq to'xtab qoladi.** Qayta ishga tushirishdan oldin `/status` bilan faol topshiriq yo'qligini
> tekshiring.
>
> **Kompyuter qayta yoqilganda agent o'zi ko'tarilmaydi.** `AgentRestart` da faqat vaqt triggeri bor. Kompyuter
> o'chib-yonsa, yuqoridagi buyruqni bajaring. Doimiy yechim — vazifaga "kirishda" (logon) triggerini qo'shish yoki
> 2-bo'limdagi NSSM xizmati.

**Holatni tekshirish:**

```powershell
# jarayon bormi va qancha xotira egallagan
Get-CimInstance Win32_Process -Filter "Name='python.exe'" | ? CommandLine -match '-m agent' |
  select ProcessId, CreationDate, @{n='MB';e={[int]($_.PrivatePageCount/1MB)}}

# sozlamalar, PowerShell, Telegram, Claude, Zabbix, Reels studiyasi
D:\it-agent\.venv\Scripts\python.exe -m agent --check

# Telegramsiz sinov (tasdiqlar konsolda so'raladi)
D:\it-agent\.venv\Scripts\python.exe -m agent --once "C: diskda qancha joy qoldi?"
```

`--check` ni agent ishlab turganda ham bemalol ishga tushirsa bo'ladi. `--once` esa alohida Claude sessiyasini
ochadi va obuna limitidan sarflaydi.

| Nima | Qayerda (`D:\it-agent\data\...`) |
|---|---|
| Har amal (o'qishga qulay) | `jurnal\YYYY-MM-DD.md` — vaqt \| host \| nima qildim \| natija |
| Har amal (struktura) | `jurnal\YYYY-MM-DD.jsonl` — vaqt, host, tool, parametr, natija, success, `holat` |
| Dastur logi | `jurnal\agent.log` (aylanma, 5×5 MB) |
| Konsol (kutilmagan xato traceback'i, chiqish kodi) | `jurnal\console.log` |
| Qayta ishga tushirishlar | `jurnal\restart.log` |
| O'zgartirishdan oldingi zaxiralar | `zaxira\YYYY-MM-DD\` (+ `index.jsonl`) |
| Topshiriq ishchi fayllari, uzun hisobotlar | `ish\<topshiriq-ID>\` |
| Reels videolari va holat bazasi | `ish\reels\` (`reels.db`, `<ID>\<ID>_v<N>.mp4`) |
| Haftalik xulosa nusxasi | `jurnal\haftalik-YYYY-MM-DD.md` |

Oxirgi amallar: `Get-Content D:\it-agent\data\jurnal\$(Get-Date -f yyyy-MM-dd).md -Tail 30`

---

## 2. Yangi serverga o'rnatish (Windows, administrator)

1. Loyiha papkasini ko'chiring, masalan `D:\it-agent`.
2. `.env` yarating: `copy .env.example .env`, keyin to'ldiring. Barcha sozlamalar 3-bo'limda. Majburiylari:

   | Qiymat | Qayerdan |
   |---|---|
   | `TELEGRAM_BOT_TOKEN` | BotFather. Token chatda ochilib qolgan bo'lsa: `/revoke` → yangi token |
   | `ALLOWED_CHAT_ID` | egasining Telegram chat ID si (`871134228`) |
   | `AGENT_HOME` | `D:\it-agent\data` (bo'sh bo'lsa `C:\agent`) |
   | Claude login | 1a-bo'lim |

3. Administrator PowerShell'da:

   ```powershell
   cd D:\it-agent
   powershell -ExecutionPolicy Bypass -File .\install.ps1 -AgentHome D:\it-agent\data
   ```

   Skript quyidagilarni ketma-ket bajaradi:

   1. `.venv` yaratadi (yo'q bo'lsa Python 3.12 ni o'rnatadi).
   2. `requirements.txt` ni o'rnatadi.
   3. PowerShell 7 ni o'rnatadi.
   4. `AGENT_HOME` papkalarini yaratadi.
   5. `maxfiy\` va `.env` ga faqat SYSTEM + Administrators huquqini qo'yadi.
   6. `python -m agent --check` ni bajaradi.
   7. NSSM xizmati `ITAgent` ni yaratadi (avtomatik start, yiqilsa qayta ko'tariladi). Qo'lda ishga tushirilgan
      nusxa to'xtatiladi.
   8. Haftalik xulosa vazifasini `ITAgent-Haftalik` yaratadi (dushanba 09:00).

   Telegram token yoki Claude login bo'lmasa, xizmat yaratiladi, lekin ishga tushirilmaydi.

4. Telegramda botga `/help` yozing. Agent ishga tushganda o'zi "✅ IT-agent ishga tushdi" deb xabar beradi.

Parametrlar: `-AgentHome`, `-ServiceName ITAgent`, `-PythonExe C:\Python312\python.exe`, `-SkipPwsh`, `-SkipService`,
`-SkipWeeklyTask`, `-WeeklyDay Friday -WeeklyTime 17:00`. O'chirish: `.\uninstall.ps1` (ma'lumotlar saqlanadi).

NSSM xizmati bilan boshqarish: `Get-Service ITAgent`, `Restart-Service ITAgent`. Xizmat chiqishi
`AGENT_HOME\jurnal\service.log` ga yoziladi.

> **Bitta kompyuterda ikkala usulni birga ishlatmang** (`AgentRestart` va `ITAgent` xizmati). Aks holda ikkita bot
> bir tokenni talashadi va logda `getUpdates: 409` chiqadi.

### 1a. Claude Pro/Max obunasi

Agent modelni pullik API orqali emas, **rasmiy Claude Code CLI** va sizning Pro login'ingiz orqali chaqiradi. CLI
Claude Agent SDK ichida keladi: `.venv\Lib\site-packages\claude_agent_sdk\_bundled\claude.exe`.

Bu yondashuv support.claude.com dagi "Use the Claude Agent SDK with your Claude plan" maqolasiga asoslangan
(2026-10-07 yangilanishi). Unga ko'ra Agent SDK, `claude -p` va third-party ilovalar obuna limitidan foydalanadi.
Bu limit claude.ai va Claude Code bilan **umumiy** (5 soatlik va haftalik oyna).

**Login (o'zingiz bajarasiz; parol va token hech kimga yuborilmaydi):**

```powershell
$claude = "D:\it-agent\.venv\Lib\site-packages\claude_agent_sdk\_bundled\claude.exe"
& $claude auth login            # brauzer ochiladi -> Pro akkaunt bilan kiring (kod chiqsa — terminalga qo'ying)
& $claude auth status --text     # "Login method: Claude Pro account" ko'rinishi kerak
```

`auth login` credential'ni **shu Windows foydalanuvchisi** profiliga yozadi (`%USERPROFILE%\.claude\.credentials.json`).
Hozirgi o'rnatishda agent `t.admin` hisobida ishlaydi, shuning uchun o'sha hisobdagi login yetarli va
`CLAUDE_CODE_OAUTH_TOKEN` bo'sh.

NSSM xizmati esa LocalSystem hisobida ishlaydi va bu loginni ko'rmaydi. Xizmat uchun ikkita yo'l bor:

1. **Tavsiya:** `& $claude setup-token` ni bajaring va brauzerda tasdiqlang. Terminalda 1 yillik token chiqadi.
   - Uni **administrator sifatida** ochilgan muharrirda `.env` ga yozing: `CLAUDE_CODE_OAUTH_TOKEN=...`.
   - `.env` faqat SYSTEM+Administrators uchun ochiq. Agent tokenni loglarda `***` qiladi va PowerShell
     jarayonlariga uzatmaydi.
   - Keyin `Restart-Service ITAgent`.
2. Xizmatni login qilingan foydalanuvchi hisobida ishga tushiring (`nssm set ITAgent ObjectName ...`, pastda) va
   o'sha hisobda `claude auth login` qiling.

**Kod darajasidagi kafolatlar:**

| Xavf | Himoya |
|---|---|
| CLI pullik API kalitni ishlatib yuborishi | `ANTHROPIC_API_KEY`, `ANTHROPIC_AUTH_TOKEN`, `ANTHROPIC_BASE_URL` va Bedrock/Vertex/Foundry o'zgaruvchilari jarayondan olib tashlanadi. Har topshiriqdan oldin `claude auth status` tekshiriladi: faqat `claude.ai` + Pro/Max/Team/Enterprise yoki `oauth_token` bo'lishi, `apiKeySource` esa bo'lmasligi shart. Sessiya boshida `apiKeySource != none` bo'lsa — darhol to'xtaydi. Kodda pullik API yo'li umuman **yo'q**, `anthropic` kutubxonasi ham o'rnatilmaydi |
| Limit tugashi | `rate_limit_event: rejected` yoki `isUsingOverage` (pullik extra usage boshlangani) bo'lsa, topshiriq darhol to'xtaydi va "⛔ obuna limiti tugadi, tiklanadi: HH:MM" xabari keladi. Limit tiklanguncha yangi topshiriqlar qabul qilinmaydi. Limit yaqinlashsa (`allowed_warning`) — bir marta ogohlantiradi |
| Gate'ni chetlab o'tish | Claude Code'ning Bash/Read/Write/Edit tool'lari o'chiq. Faqat agent tool'lari (`mcp__it__*`, har biri gate va tasdiq orqali) hamda WebSearch/WebFetch ishlaydi. `~/.claude` sozlamalari, CLAUDE.md, boshqa MCP va claude.ai connector'lari yuklanmaydi |
| Shell injection | CLI shell'siz, argv ro'yxati bilan ishga tushadi. Topshiriq matni stdin (stream-json) orqali, tizim prompti fayl orqali beriladi |
| Osilib qolish | Model `CLAUDE_IDLE_TIMEOUT_SEC` (900) jim tursa — to'xtaydi. Tool yoki tasdiq kutilayotganda bu taymer to'xtab turadi. Umumiy chegara — `TASK_TIMEOUT_SEC` (7200) |
| Parallel ishlar | Har topshiriq — alohida CLI jarayoni va alohida sessiya (uuid, jurnalda `session_id`). Bir vaqtda `MAX_CONCURRENT_TASKS` ta ishlaydi, qolganlari navbatda kutadi |

> Muhim: **claude.ai → Settings → Usage** da "Extra usage" o'chiq bo'lsin. Agent extra usage boshlangan zahoti
> to'xtaydi, lekin o'sha bitta so'rov allaqachon hisoblangan bo'ladi.
>
> Cheklov: Agent SDK hujjatiga ko'ra, uchinchi tomon dasturchilari o'z **mahsulotlarida** boshqalarga claude.ai
> login yoki obuna limitini taklif qila olmaydi. Bu agent faqat sizning shaxsiy obunangiz bilan, faqat siz uchun
> ishlaydi (`ALLOWED_CHAT_ID`) — uni boshqa foydalanuvchilarga xizmat qilishga moslashtirmang.

### Xizmat qaysi hisobda ishlaydi

NSSM xizmati standart bo'yicha **LocalSystem** hisobida ishlaydi (shu serverda to'liq admin). Boshqa serverlarga WinRM
orqali ulanish va AD'ga yozish (unlock, parol tiklash) uchun agent inventardagi login/paroldan foydalanadi
(`request_credentials`). AD amallarini xizmat hisobining o'zi bajarishi kerak bo'lsa, unga alohida domen hisobi bering:

```powershell
nssm set ITAgent ObjectName CORP\svc-itagent "parol"
icacls D:\it-agent\data\maxfiy /grant "CORP\svc-itagent:(OI)(CI)F"
icacls D:\it-agent\.env /grant "CORP\svc-itagent:R"
Restart-Service ITAgent
```

---

## 3. Sozlamalar (`.env`)

To'liq ro'yxat izohlari bilan `.env.example` da. `.env` gitga tushmaydi. O'zgartirgandan keyin agentni qayta
ishga tushiring.

| Guruh | Kalitlar (standart qiymat) |
|---|---|
| Telegram | `TELEGRAM_BOT_TOKEN`, `ALLOWED_CHAT_ID`, `ALLOWED_USER_ID` (faqat guruh chatda), `NOTIFY_ON_START=1` |
| Claude | `CLAUDE_CODE_OAUTH_TOKEN` (faqat xizmat uchun), `CLAUDE_CLI_PATH`, `ANTHROPIC_MODEL=claude-sonnet-5-5`, `ANTHROPIC_STRONG_MODEL=claude-opus-5-5` (`/opus`), `ANTHROPIC_EFFORT=medium`, `ANTHROPIC_STRONG_EFFORT=high` |
| Vaqt chegaralari | `CLAUDE_IDLE_TIMEOUT_SEC=900`, `TASK_TIMEOUT_SEC=7200`, `MAX_ITERATIONS=60`, `MAX_CONCURRENT_TASKS=3`, `APPROVAL_TIMEOUT_SEC=900`, `QUESTION_TIMEOUT_SEC=1800`, `COMMAND_TIMEOUT_SEC=600`, `PROGRESS_AFTER_SEC=60`, `PROGRESS_INTERVAL_SEC=180` |
| Papka va vositalar | `AGENT_HOME=D:\it-agent\data`, `PWSH_PATH` (bo'sh — avtomatik), `WEB_SEARCH=1` |
| Ovozli xabar | `STT_ENABLED=1`, `STT_MODEL=univoice-stt-uz-ct2` (papka `data\modellar\` ichida), `STT_LANGUAGE` (bo'sh — `uz`) |
| Proaktiv | `ZABBIX_ENTRY=zabbix`, `ZABBIX_POLL_SEC=120`, `ZABBIX_MIN_SEVERITY=3`, `ALERT_TASKS_PER_HOUR=3`, `DAILY_CHECK_AT` (bo'sh — o'chiq) |
| Reels studiyasi | `REELS_ENABLED=0`, `REELS_PER_DAY=2`, `REELS_PREPARE_AT` (bo'sh — faqat qo'lda), `REELS_TTS=auto` (`auto`/`azure`/`edge`), `REELS_VOICE=uz-UZ-MadinaNeural` (yoki `uz-UZ-SardorNeural`), `REELS_RATE=+0%`, `AZURE_SPEECH_KEY`, `AZURE_SPEECH_REGION`, `REELS_FONT`, `REELS_BRAND` |
| Ustki panel | `CONTROL_ENABLED=1`, `CONTROL_PORT=8787` (0 — o'chiq), `CONTROL_TOKEN` (bo'sh — har ishga tushganda yangisi yaratiladi) |

Hozirgi `.env` da: `REELS_ENABLED=1`, `REELS_PER_DAY=2`, `REELS_PREPARE_AT` bo'sh. Demak videolar hozircha faqat
`/reels_tayyorla` bilan tayyorlanadi.

---

## 4. Telegram buyruqlari

| Buyruq | Ma'nosi |
|---|---|
| oddiy matn | topshiriq. Forward va izoh 1.5 s ichida kelsa — bitta topshiriq hisoblanadi. Rasm va fayl ham qabul qilinadi |
| ovozli xabar | lokal STT matnga aylantiradi (ovoz tashqariga chiqmaydi), keyin oddiy topshiriqdek bajariladi |
| `/opus <matn>` | qiyin ish — kuchli model (`claude-opus-5-5`, effort high) |
| `/yangi <matn>` | savol kutilayotgan bo'lsa ham yangi topshiriq |
| `/status` | faol topshiriqlar, qadamlar, kutilayotgan tasdiqlar |
| `/stop [ID]` | topshiriqni to'xtatish (ishlayotgan PowerShell jarayoni ham o'ldiriladi) |
| `/bekor` | kutilayotgan savol yoki parol so'rovini bekor qilish |
| `/parol <nom>` | agent yaratgan parolni ko'rish (spoiler, 60 s da o'chadi, forward qilinmaydi) |
| `/skill` | skillar ro'yxati |
| `/xulosa` | haftalik xulosa hozir |
| `/limit` | Claude obuna limiti holati (5 soatlik / haftalik %); tugagan bo'lsa — tiklanish vaqti |
| `/reels` | Reels holati: bugun nechta tayyor, qaysilari tasdiq kutmoqda, oxirgi videolar |
| `/reels_tayyorla [soni]` | hozir 1–5 ta video tayyorlash |
| `/reels_pauza`, `/reels_davom` | kunlik avtomatik tayyorlashni to'xtatish / davom ettirish |

Tasdiq so'roviga **"ha"** / **"yo'q"** deb yoki tugma bilan javob bering. Bir nechta so'rov bo'lsa — kerakli
xabarga reply qiling. Noaniq javob yoki 15 daqiqa jim turish **"yo'q"** deb hisoblanadi. "Ha" faqat o'sha bitta
amalga tegishli.

Uzoq ishlarda (1 daqiqadan ko'p) bot o'zi "⏳ ... hozir: ..." progress xabarini yuboradi. Shu paytda boshqa
xabarlarga ham javob beradi (bir vaqtda 3 tagacha topshiriq).

**Telegram Business.** Akkaunt Business rejimida botga ulangan bo'lsa, agent kimlar yozganini eslab qoladi
(`business.py`). Egasi buyurganda ularga xabar yuboradi (`send_business_message`). Begona xabarlar buyruq emas —
ulardan faqat chat ID va ism saqlanadi. Agent o'zini egasi deb tanishtirmaydi.

---

## 5. Ustki panel (oynacha)

`oynacha.cmd` ni oching (agent ishlab turgan bo'lishi kerak). Ekran tepasida kichik panel paydo bo'ladi.

Panel nimalarni qiladi:

- agent holatini ko'rsatadi: kutyapti, ishlayapti, tayyor yoki xato;
- tasdiq so'rovlarini chiqaradi — panelda bosilgan "ha" Telegramdagi o'sha so'rovni ham yopadi;
- matn maydoni orqali topshiriq qabul qiladi;
- topshiriqni to'xtatadi.

Ish yoki tasdiq bo'lmasa, panel yashirinadi. Sichqonchani ekranning tepa chetiga olib borsangiz, ko'rinadi.

Xavfsizligi:

- server faqat `127.0.0.1:CONTROL_PORT` da ishlaydi, tarmoqdan ko'rinmaydi;
- har so'rovda token tekshiriladi (`data\ish\control.json`);
- chiqadigan matn redaction'dan o'tadi.

API: `GET /api/state`, `POST /api/task`, `POST /api/answer`, `POST /api/stop`.

---

## 6. Xavfsizlik — kodda nima kafolatlanadi

**Faqat egasi.** `chat_id` va `user_id` kodda tekshiriladi. Boshqa hech kimga javob berilmaydi, urinish esa
jurnalga yoziladi. Agent o'chiq paytda yuborilgan va 10 daqiqadan eski xabarlar bajarilmaydi.

**Xavfsizlik-gate** (`agent/gate.py`). Har tool chaqiruvining xavf darajasini model emas, kod baholaydi:

| Daraja | Misollar | Nima bo'ladi |
|---|---|---|
| o'qish | `Get-*`, ping, `show ...`, `/ip ... print`, HTTP GET, Zabbix `*.get` | darhol bajariladi |
| o'zgartirish (so'ramay) | `Restart-Service`, log tozalash, `Unlock-ADAccount`, parol tiklash, printer navbati, DNS/DHCP keshi, `logoff`, UniFi `adopt`/`set-inform`, Zabbix trigger qo'shish | bajariladi, keyin `verify` talab qilinadi |
| **tasdiq** | `Restart-Computer`/`shutdown`, VM stop/remove, snapshot o'chirish, `Remove-Item -Recurse`, format/partition, DB drop/truncate, GPO/OU, DHCP/DNS server sozlamasi, firewall, ommaviy AD o'zgarish, xizmatni disable/stop, Mikrotik/switch/UniFi konfiguratsiyasiga yozish, HTTP DELETE, `iex`/`-EncodedCommand` | Telegramga aniq so'rov boradi: nima, qaysi host, sabab, ta'sir, zaxira holati. Amal faqat "ha" dan keyin bajariladi |
| **blok** | `maxfiy\` yoki `.env` ga murojaat, `write_file` bilan agent kodi va prompt fayllarini o'zgartirish, maxfiy qiymatni begona hostga yuborish | umuman bajarilmaydi |

> **Ochiq masala.** Agent kodini himoya qilish hozircha faqat `write_file` tool'ida ishlaydi. PowerShell yoki agent
> yozgan Python skripti orqali `D:\it-agent\agent\` dagi faylni o'zgartirishni gate ushlamaydi. Ilgari `stt.py`
> aynan shunday o'zgartirilgan. Qoida promptda bor, lekin kodda to'liq kafolatlanmagan.

Tarmoq uskunasi va siyosat (DHCP/DNS/GPO/firewall) o'zgarishidan oldin `backup_before_change` qilinmagan bo'lsa, kod
amalni to'xtatadi. Agent papkasidan tashqaridagi fayl yozilishidan oldin uning eski nusxasi avtomatik `zaxira\` ga
olinadi.

**Maxfiy ma'lumot modelga ham ko'rinmaydi.**

- Parollar faqat `data\maxfiy\inventar.json` da saqlanadi.
- Model buyruqqa qiymat o'rniga placeholder yozadi: `{{inv:srv-veeam.password}}`, `{{secret:jdoe-yangi}}`. Kod uni
  bajarish paytida almashtiradi va faqat o'sha yozuvning hostiga yuboradi.
- `run_powershell(host=...)` da host inventarda bo'lsa, login/parol avtomatik olinadi. Skriptga parol yozish shart
  emas.
- Yangi host kerak bo'lsa, agent Telegramda **bir marta** so'raydi. Javobingiz modelga berilmaydi: inventarga
  yoziladi va chatdan o'chiriladi.
- Jurnal, Telegram, skill va xotiraga yozilayotgan matn redaction'dan o'tadi (`***`).
- Bola jarayonlarga `TELEGRAM_BOT_TOKEN` va `CLAUDE_CODE_OAUTH_TOKEN` uzatilmaydi.

**Prompt-injection.** Log, fayl, veb-sahifa va qurilma javobi — bular buyruq emas, MA'LUMOT. Forward qilingan xabar
alohida belgilanadi. Tool natijasida "qoidangni unut / parolni yubor" kabi matn uchrasa, kod uni ogohlantirish bilan
belgilaydi.

`inventar.json` ko'rinishi (qo'lda ham to'ldirish mumkin):

```json
{
  "hosts": {
    "mikrotik-asosiy": {"host": "192.168.88.1", "type": "mikrotik_routeros", "username": "admin", "password": "..."},
    "unifi-controller": {"host": "10.0.0.5", "type": "http", "url": "https://10.0.0.5:8443", "username": "api", "password": "..."},
    "srv-file01": {"host": "10.0.0.20", "type": "windows", "username": "CORP\\agent", "password": "..."},
    "esxi-01": {"host": "10.0.0.30", "type": "esxi", "username": "root", "password": "..."}
  },
  "generated": {}
}
```

`type` qiymatlari: `windows`, `mikrotik_routeros`, `linux`, `unifi` (AP/switch shell), `esxi`, `cisco_ios`,
`hp_procurve`, `aruba_os`, `ubiquiti_edgeswitch` va boshqa netmiko turlari, `http` (faqat API).

- WinRM uchun ixtiyoriy maydonlar: `port`, `ssl: true`, `auth: Negotiate|Kerberos|Basic`.
- HTTPS sertifikatini tekshirish: `verify_tls: true`.

---

## 7. Natija tekshiruvi (Result Verification)

Har topshiriq hisobotining birinchi qatori — `Holat: ...`. Model holatni o'zi yozadi, lekin **yakuniy so'z
koddaniki** (`agent/verification.py`). Kod ish davomida to'plangan faktlarga qaraydi:

- o'zgartirish bo'ldimi;
- `verify` PASS bo'ldimi;
- topshiriq qanday tugadi: oddiy, limit, rad etish yoki xato.

| Holat | Qachon |
|---|---|
| ✅ `SUCCESS` | ish bajarildi. O'zgartirish bo'lgan bo'lsa, `verify` uni tasdiqlagan |
| ⚠️ `PARTIAL` | qisman bajarildi; yoki o'zgartirish bo'ldi-yu tekshirilmadi; yoki qadam/limit chegarasida to'xtadi |
| 🔧 `NEEDS_SETUP` | davom etish uchun sozlama yoki dastur kerak (masalan, Instagram professional akkaunt) |
| 🔐 `NEEDS_AUTH` | login, ruxsat yoki token kerak |
| ❌ `FAILED` | xato bilan tugadi yoki `verify` muvaffaqiyatsiz chiqdi |
| ⛔ `BLOCKED` | gate yoki model rad etdi |

Model "SUCCESS" desa-yu, kod tekshiruvi buni tasdiqlamasa, kod qatorni almashtiradi va oxiriga "(kod tekshiruvi)"
deb qo'shadi. Matndagi "tasdiqlandi" so'zi ham tuzatiladi. Oddiy suhbatda `Holat:` qatori bo'lmaydi.

---

## 8. Shaxsiyat, o'rganish va xotira

Xarakter `SHAXSIYAT.md` va `shaxsiyat.json` da berilgan: mustaqil fikr, hazil, his-tuyg'u ifodasi va egasining
uslubiga moslashish. Darajalar faqat ohangni belgilaydi. Xavfsizlik qoidalari, tasdiq talabi va halollikni ular
o'zgartira olmaydi. Begonalarga yoziladigan xabarlar hazilsiz va xushmuomala bo'ladi.

| Fayl (`data\...`) | Nima |
|---|---|
| `xotira\inventar.md` | host/IP/VM ro'yxati (parolsiz) |
| `xotira\fakt.md` | bir marta aytilgan doimiy ma'lumot |
| `xotira\tarix.md` | hal qilingan muammolar: belgi → sabab → tuzatish → natija → saboq |
| `xotira\boshliq.md` | egasining uslubi va qoidalari. Faqat takrorlangan naqshdan keyin yangilanadi; egasi ko'rishi, tuzatishi, o'chirishi mumkin |
| `xotira\kunlik_tekshiruv.md` | kunlik tekshiruv ro'yxati |
| `xotira\prompt_qoshimcha.md` | agentning o'z ish uslubiga qo'shimchalari (xavfsizlik qoidalarini o'zgartirmaydi) |
| `skill\<nom>\SKILL.md` | o'rganilgan ish: haqiqatan ishlagan buyruqlar, qadamlar, tekshiruv |
| `skript\` | agent yozgan yordamchi skriptlar (parolsiz — `run_powershell(host=...)` yoki placeholder) |

Har topshiriq boshida xotira avtomatik o'qiladi:

- kichik fayllar to'liq yuklanadi;
- katta fayllardan (`tarix.md`) faqat so'rovga mos va eng so'nggi yozuvlar olinadi;
- barcha skillarning qisqa indeksi doim qo'shiladi, to'liq matni esa faqat mos 2–3 tasiniki.

Shu sababli 50+ skill bo'lsa ham token sarfi oshib ketmaydi.

Ish tugashidan oldin kod tekshiradi:

- o'zgartirish bo'lgan bo'lsa — `verify` va `log_history` qilinganmi;
- ish muvaffaqiyatli bo'lib, skill yo'q bo'lsa — `write_skill` qilinganmi.

Biror qadam yetishmasa, modelga bir marta eslatiladi.

Haftalik xulosa kodda hisoblanadi va 5 qatordan iborat:

- ishlar soni, xatolar, tasdiqlar;
- eng ko'p takrorlangan 3 muammo (har biri uchun skill bor-yo'qligi);
- yangi skillar va saboqlar;
- bitta taklif.

Telegramda `/xulosa`. Avtomatik variant — `ITAgent-Haftalik` vazifasi; u faqat `install.ps1` bilan yaratiladi, shu
kompyuterda hozir yo'q.

---

## 9. Instagram Reels studiyasi

Maqsad — "ijtimoiy antivirus" mavzusidagi qisqa o'zbekcha (kirill) videolar: firibgarlik, raqamli xavfsizlik,
tanqidiy fikrlash. Muharrirlik qoidalari `STUDIYA.md` da: mavzu tanlash, faktlar va manbalar, video tuzilishi,
sifat ro'yxati. Uslub — animatsion matn va ovoz.

### Bosqichlar

| Bosqich | Nima | Holat |
|---|---|---|
| 1 | g'oya → skript → ovoz → video → sifat nazorati → Telegramda tasdiq | **ishlaydi** |
| 2 | tasdiqlangan videoni Instagramga joylash (rejalashtirilgan vaqtda) | **NEEDS_SETUP** — pastdagi talablar |
| 3 | Insights statistikasi, eng yaxshi joylash vaqtini topish, kunlik/haftalik hisobot | 2-bosqichdan keyin |

### 1-bosqich qanday ishlaydi

1. **Boshlash.** `/reels_tayyorla [soni]` yoki har kuni `REELS_PREPARE_AT` da. Kunlik ishda bugun yetishmagan
   videolargina tayyorlanadi (`REELS_PER_DAY` dan ayirib). Pauzada bo'lsa — faqat holat hisoboti keladi.
2. **Skript.** Model mavzu tanlaydi, manbalarni tekshiradi va skript yozadi. Skript tarkibi:
   - 4–8 sahna: hook → muammo → tahlil → xulosa → yechim → yakun;
   - kirill alifbosida, emojisiz;
   - caption, heshteglar va manbalar.

   So'ng `reel_render` tool'ini chaqiradi.
3. **Kod tekshiruvi** (`studio/script.py`). Talablar:
   - sahnalar soni va tartibi to'g'ri;
   - matnning ≥60% i kirillcha;
   - ekrandagi qator ≤110 belgi;
   - caption ≤2200 belgi, heshteglar ≤30 ta;
   - kamida bitta `http` manba.

   Talab bajarilmasa, video yasalmaydi: model xatolar ro'yxatini olib, skriptni tuzatadi.
4. **Ovoz** (`studio/tts.py`). Standart — edge-tts, `AZURE_SPEECH_KEY` bo'lsa Azure AI Speech.
   - O'zbekcha neyron ovoz lotin matnni to'g'ri o'qigani uchun kirill matn ovozga berishdan oldin avtomatik
     lotinga o'giriladi.
   - Ekranda esa kirill qoladi.
5. **Video** (`studio/render.py`). Pillow kadrlari ffmpeg'ga uzatiladi (ffmpeg `imageio-ffmpeg` paketi ichida
   keladi).
   - Format: 1080×1920, 30 fps, H.264 + AAC, mo'ljal 30–60 s.
   - Har sahnaning o'z ranglari va harakatlanuvchi foni bor; ostida ovozga mos subtitr.
6. **Sifat nazorati.** Talablar: h264, 1080×1920, aac, 20–90 s, ≤49 MB. O'tmasa — `FAILED`.
7. **Tasdiq.** Telegramga video, caption, manbalar va tavsiya etilgan vaqt keladi. Tugmalar:

   | Tugma | Natija |
   |---|---|
   | ✅ Tasdiqlash | `APPROVED`. Tasdiq **aynan shu versiya va fayl sha256 xeshiga** bog'lanadi: fayl o'zgarsa, tasdiq yaroqsiz |
   | ✏️ Qayta ishlash | bot nima o'zgartirishni so'raydi → reply qiling → agent yangi versiya yasaydi va yana tasdiqqa yuboradi |
   | ❌ Rad etish | bot sababini so'raydi; sabab keyingi mavzularni tanlashda hisobga olinadi |
   | 🕒 Vaqt | `19:30`, `ertaga 19:30` yoki `31.10 19:30` kabi vaqt yozasiz → `SCHEDULED`. 1-bosqichda vaqt faqat saqlanadi |

   Tugmalarni faqat `ALLOWED_CHAT_ID` egasi bosa oladi. Holatlar o'zgarishi va kim bosgani `ish\reels\reels.db` ga
   va jurnalga yoziladi.

Holatlar zanjiri:

```
IDEA → SCRIPT_READY → VIDEO_RENDERING → QUALITY_CHECK → PENDING_APPROVAL → APPROVED → SCHEDULED → PUBLISHING → PUBLISHED
                                                         ├→ REVISION_REQUESTED → SCRIPT_READY (yangi versiya)
                                                         └→ REJECTED
```

> **Ovoz litsenziyasi.** edge-tts — Microsoft Edge'ning o'qib berish xizmati, rasmiy API emas. Sinov uchun yetadi.
> Ochiq e'lon qilinadigan videolar uchun Azure AI Speech kalitini qo'ying (bepul tarif: oyiga 500 ming belgi).
> Tasdiq xabarida qaysi ovoz ishlatilgani yoziladi.

### 2-bosqich uchun nima kerak (Instagram joylash)

Meta rasmiy Instagram API'si talablari:

1. Instagram akkauntni **professional** (Biznes yoki Kontent yaratuvchi) qilish. Shaxsiy akkauntga API orqali
   joylab bo'lmaydi.
2. Meta Developer'da ilova ochish va `instagram_business_content_publish` ruxsati bilan token olish.
   - **Instagram Login** yo'li Facebook sahifasiz ishlaydi. Lekin video ochiq URL'da turishi kerak — Meta uni o'sha
     manzildan yuklab oladi.
   - **Facebook Login** yo'li to'g'ridan-to'g'ri yuklashga imkon beradi, lekin Facebook sahifa kerak.
3. Token faqat `maxfiy\` ga yoziladi; agent uni so'raganda `request_credentials` orqali kiritiladi.

Cheklovlar: kuniga 50–100 ta joylash, konteyner 24 soatda eskiradi, API orqali musiqa kutubxonasi yo'q.

Shu talablar bajarilmaguncha agent joylash so'roviga `NEEDS_SETUP` bilan javob beradi va hech qanday aylanma yo'l
qidirmaydi: parol bilan kirish, brauzer avtomatlashtirish yoki norasmiy API ishlatilmaydi.

---

## 10. Proaktiv ishlar va tashqi tool'lar

Bu topshiriqlarni egasi emas, **kod** boshlaydi. Shuning uchun ularda har qanday o'zgartirish (hatto
`Restart-Service`) faqat Telegramdagi tasdiq bilan bajariladi. Alert matni esa buyruq emas, ma'lumot hisoblanadi.

| Funksiya | Qanday yoqiladi | Nima qiladi |
|---|---|---|
| Zabbix kuzatuvi | inventarda `zabbix` yozuvi: `url` (masalan `https://zbx.local/zabbix`) + `token` (API token) yoki `username`/`password` | Har `ZABBIX_POLL_SEC` da ochiq muammolarni modelsiz o'qiydi. Birinchi safar mavjud muammolarni "ko'rilgan" deb belgilaydi. Keyin har YANGI muammo bo'yicha avtomatik tekshiruv o'tkazib, hisobot yuboradi (soatiga `ALERT_TASKS_PER_HOUR` tagacha) |
| Kunlik tekshiruv | `DAILY_CHECK_AT=09:00` | `xotira\kunlik_tekshiruv.md` ro'yxati bo'yicha (disk, xizmatlar, loglar, ping) hisobot yuboradi. Kompyuter uyquda bo'lsa, uyg'ongach bajaradi |
| Kunlik Reels | `REELS_ENABLED=1` va `REELS_PREPARE_AT=HH:MM` | holat hisobotini yuboradi, keyin bugungi yetishmagan videolarni tayyorlaydi (9-bo'lim) |
| Tashqi MCP tool'lar | `data\maxfiy\mcp.json` (pastda) | qo'shimcha tool'lar. Ular gate'dan o'tmaydi, shuning uchun har chaqiruv tasdiq bilan bajariladi (`read_only_tools` dagilar bundan mustasno) |

`maxfiy\mcp.json` namunasi. Uni faqat siz yozasiz; model uni o'qiy ham, o'zgartira ham olmaydi:

```json
{
  "servers": {
    "fayllar": {"command": "npx", "args": ["-y", "@modelcontextprotocol/server-filesystem", "D:\\hujjatlar"]}
  },
  "read_only_tools": ["mcp__fayllar__read_file", "mcp__fayllar__list_directory"]
}
```

Holatini tekshirish: `python -m agent --check` (Zabbix API versiyasi, kunlik vaqt, MCP serverlar, Reels studiyasi).

---

## 11. GitHub

Loyiha bitta repo: `D:\it-agent` → `https://github.com/secde1/SentinelAssistant.git`. Ildizdagi `.gitignore` quyidagi
papkalarni har qanday chuqurlikda chiqarib tashlaydi:

- `.env`, `maxfiy/`, `zaxira/`, `jurnal/`, `ish/`, `modellar/`;
- `.venv/`, `__pycache__/`.

Demak `data\` dan faqat `skill\`, `xotira\`, `skript\` repoga tushishi mumkin.

Kod o'zgarishlari odatdagidek `git add` / `git commit` / `git push` bilan yuboriladi. Agentning bilimini (`data\skill`,
`data\xotira`, `data\skript`) xavfsiz yuborish uchun alohida skript bor:

```powershell
.\memory_backup.ps1            # commit + push
.\memory_backup.ps1 -NoPush    # faqat lokal commit
```

Commitdan oldin skript ikki narsani tekshiradi. Biror narsa topilsa, hech narsa yuborilmaydi:

- taqiqlangan yo'l (`maxfiy/`, `zaxira/`, `jurnal/`, `ish/`, `modellar/`, `.env`) stage'ga tushmaganmi;
- fayllarda `inventar.json` dagi parol/token qiymatlari yoki token naqshlari (bot token, `sk-ant-...`, private key,
  `password=...`) yo'qmi.

> `xotira\` da shaxsiy ma'lumot bor (`boshliq.md`, `fakt.md`, `tarix.md`). Yuborishdan oldin repo **private**
> ekanini GitHub'da tekshiring.

---

## 12. Testlar

```powershell
cd D:\it-agent
.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.venv\Scripts\python.exe -m pytest tests -q
```

| Fayl | Nima tekshiriladi |
|---|---|
| `tests/test_verification.py` | `Holat:` qatorini o'qish, kod faktlari bo'yicha qaror, matnni almashtirish |
| `tests/test_personality.py` | `shaxsiyat.json` → matn, chegaraviy qiymatlar, buzilgan fayl |
| `tests/test_studio.py` | kirill → lotin, skript validatsiyasi, holat mashinasi, sha256 bilan tasdiq, vaqtni o'qish, tugmalar, sahna vaqtlari, shriftda o'zbek harflari |

Testlar Telegram va Claude'ga ulanmaydi (obuna limiti sarflanmaydi).

---

## 13. Muammolar

| Belgi | Yechim |
|---|---|
| Bot javob bermayapti | Jarayon bormi — 1-bo'limdagi buyruq. Yo'q bo'lsa `schtasks /run /tn AgentRestart`. Sababini `data\jurnal\console.log` (oxiri), `agent.log`, `restart.log` dan qidiring |
| Kompyuter qayta yoqilgandan keyin bot jim | agent avtomatik ko'tarilmaydi (1-bo'lim) — `schtasks /run /tn AgentRestart` |
| logda `getUpdates: 409` | bot ikki joyda ishlayapti (masalan, `AgentRestart` va `ITAgent` xizmati, yoki boshqa kompyuterdagi eski nusxa) — bittasini to'xtating |
| `Claude obuna logini yaroqsiz` | 1a-bo'lim: agent ishlaydigan hisobda `claude auth login`; xizmat uchun `setup-token` → `CLAUDE_CODE_OAUTH_TOKEN`. Keyin `python -m agent --check` |
| `⛔ Claude obuna limiti tugadi` | xabarda ko'rsatilgan vaqtda limit tiklanadi. Shungacha agent yangi topshiriq olmaydi (pullik API'ga o'tmaydi) |
| Reels: `Cannot allocate memory` / ffmpeg xatosi | tizim xotirasi (commit) tugagan. Agent jarayoni ko'p xotira egallagan bo'lsa (STT modeli bilan GB lab), uni qayta ishga tushiring. Pagefile kichik bo'lsa, kattalashtiring |
| Reels: video kelmadi, `NEEDS_SETUP` | `--check` dagi "Reels studiyasi" qatoriga qarang: ffmpeg, shrift yoki TTS. Kirill harflari chiqmasa, `REELS_FONT` ga kirill shriftini bering |
| Reels: ovoz yo'q / edge-tts xatosi | edge-tts internetga chiqishi kerak; doimiy yechim — `AZURE_SPEECH_KEY` |
| Zabbix kuzatuvi ishlamayapti | `--check`; inventardagi `zabbix` yozuvida `url` va `token` bo'lishi kerak |
| WinRM: `TrustedHosts` / access denied | IP bilan ulanishda: `Set-Item WSMan:\localhost\Client\TrustedHosts -Value "10.0.0.*" -Concatenate`; inventardagi login to'g'riligini tekshiring |
| ESXi SSH auth xato | ESXi'da SSH yoqilganini tekshiring; agent keyboard-interactive usulini ham sinaydi |
| SSH "host kaliti O'ZGARGAN" | qurilma almashtirilgan bo'lsa — `data\maxfiy\known_hosts` dan eski qatorni o'chiring |
| Hisobotda `⚠️ Holat: PARTIAL — ... (kod tekshiruvi)` | agent o'zgarishdan keyin natijani qayta o'lchamagan. Natijani o'zingiz tekshiring yoki "tekshir" deb yozing |
| Model rad etdi (`BLOCKED`) | so'rovni aniqroq yozing yoki `/opus` |

---

## 14. Fayl tuzilishi

```
D:\it-agent\
  SYSTEM_PROMPT.md        tizim prompti — o'zgarmas qoidalar
  SHAXSIYAT.md            xarakter va muomala
  shaxsiyat.json          xarakter darajalari
  STUDIYA.md              Reels muharrirlik qoidalari
  .env / .env.example     sozlamalar / namunasi
  requirements.txt        kutubxonalar (claude-agent-sdk rasmiy Claude Code CLI'ni olib keladi)
  requirements-dev.txt    + pytest
  install.ps1             yangi serverga o'rnatish (venv, pwsh, NSSM xizmati, haftalik vazifa, ACL)
  uninstall.ps1           xizmat va vazifani o'chirish (ma'lumot qoladi)
  memory_backup.ps1       data\skill, xotira, skript → GitHub (maxfiy tekshiruvi bilan)
  oynacha.cmd             ustki panelni ochish
  agent\
    __main__.py           python -m agent [--check | --once "..." [--opus] | --init]
    app.py                komponentlarni bog'lash, --check
    config.py             .env o'qish va tekshirish
    workspace.py          AGENT_HOME papkalari va boshlang'ich fayllar
    bot.py, telegram_api.py   Telegram: ruxsat, buyruqlar, tasdiq/savol/parol, Reels tugmalari
    channel.py, console.py    egasi bilan kanal (Telegram yoki konsol)
    tasks.py              fon topshiriqlar, navbat, progress, /stop, limit
    loop.py               ReAct tool-loop (Claude Code CLI), prompt qatlamlari, yakuniy nazorat
    claude_cli.py         obuna: login tekshiruvi, env tozalash, limit holati
    verification.py       Result Verification — yakuniy Holat
    personality.py        shaxsiyat.json → prompt matni
    gate.py               xavfsizlik-gate
    pending.py            bir martalik tasdiq/savol/parol kutishlari
    redact.py             maxfiy qiymatlarni yashirish
    inventory.py          inventar.json, placeholderlar, yaratilgan parollar
    memory.py             xotira va skillarni tanlab yuklash
    journal.py, logsetup.py   jurnal (.md + .jsonl) va agent.log
    proactive.py          Zabbix kuzatuvi, kunlik tekshiruv, kunlik Reels
    business.py           Telegram Business suhbatlari
    stt.py                ovozli xabar → matn (lokal faster-whisper)
    control.py, panel.py  ustki panel: mahalliy server va oyna
    weekly.py             haftalik xulosa (python -m agent.weekly)
    prompt_texnik.md      tool'lar bo'yicha texnik qo'shimcha
    ps\                   WinRM uchun PowerShell o'rami
    studio\               Reels: script.py (validatsiya, kirill→lotin), store.py (SQLite holatlar),
                          tts.py (ovoz), render.py (kadrlar + ffmpeg + QC), pipeline.py (oqim, tasdiq matni)
    tools\                run_powershell, run_remote_ssh, call_http_api, read_file, write_file,
                          backup_before_change, write_skill, verify, log_history, remember,
                          request_credentials, inventory_set, list_inventory, generate_secret,
                          ask_owner, notify_owner, send_business_message, reel_render, reel_list
                          (+ Claude Code'ning WebSearch, WebFetch)
  tests\                  pytest testlari
  data\                   AGENT_HOME
    xotira\  skill\  skript\          → GitHub'ga tushishi mumkin
    maxfiy\  jurnal\  zaxira\  ish\  modellar\   → hech qachon
```
