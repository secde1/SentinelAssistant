# IT-agent — avtonom IT-infratuzilma agenti va shaxsiy yordamchi (Telegram + Claude)

Telegramdan topshiriq oladi, Windows serverda va u yerdan ulanadigan qurilmalarda (Windows/AD, Mikrotik,
UniFi, Zabbix, NVR, ESXi/Hyper-V, printerlar) ishni o'zi bajaradi va 5 qatorlik hisobot qaytaradi.
Shaxsiy ishlarni ham bajaradi: Word/Excel/PDF o'qish va yaratish, fayllarni saralash, internetdan qidirish,
hisob-kitob, xat/matn tayyorlash. Brauzer parollari, cookie, `.ssh`, Claude logini kabi joylar gate'da bloklangan.
Takrorlanadigan ishni skillga aylantirib, vaqt o'tgani sari kuchayib boradi.

```
Telegram (faqat ALLOWED_CHAT_ID)
  -> Windows xizmati (NSSM, avtomatik start, yiqilsa qayta ko'tariladi)
  -> Claude: ReAct tool-loop (model tool chaqiradi -> kod bajaradi -> natija -> keyingi qadam)
     standart: Claude Agent SDK -> rasmiy Claude Code CLI -> Claude Pro/Max obuna limiti (API kalit kerak emas)
  -> xavfsizlik-gate (kodda): xavfli amal -> Telegramda "ha"/"yo'q" tasdiq (javob yo'q = YO'Q)
  -> PowerShell 7 / WinRM / SSH (netmiko, paramiko) / HTTP API
  -> jurnal: AGENT_HOME\jurnal\YYYY-MM-DD.md + .jsonl (maxfiy qiymatlar *** bilan)
  -> qisqa hisobot Telegramga ("tekshirilmagan" belgisi kodda qo'yiladi)
```

---

## 1. O'rnatish (Windows Server, administrator)

1. Loyiha papkasini serverga ko'chiring, masalan `C:\it-agent`.
2. `.env` yarating va to'ldiring (`copy .env.example .env`, keyin muharrirda oching):

   | Qiymat | Qayerdan | Holat |
   |---|---|---|
   | `TELEGRAM_BOT_TOKEN` | BotFather → `/revoke` → **yangi** token | **to'ldirish kerak** |
   | `ALLOWED_CHAT_ID` | `871134228` | tayyor |
   | `CLAUDE_CODE_OAUTH_TOKEN` | `claude setup-token` (1a-bo'lim) — xizmat shu bilan Pro obunaga kiradi | **to'ldirish kerak** |
   | `ANTHROPIC_MODEL` | `claude-sonnet-5-5` (qiyin ish: `/opus` → `claude-opus-5-5`) | tayyor |
   | `AGENT_HOME` | `C:\agent` | tayyor |

3. Administrator PowerShell'da:

   ```powershell
   cd C:\it-agent
   powershell -ExecutionPolicy Bypass -File .\install.ps1
   ```

   Skript: `.venv` (yo'q bo'lsa Python 3.12 o'rnatadi) → `requirements.txt` (pip yo'q bo'lsa `ensurepip`) →
   PowerShell 7 → `C:\agent\` papkalari va `.gitignore` → `maxfiy\` va `.env` ga faqat SYSTEM + Administrators huquq →
   `python -m agent --check` → NSSM xizmati `ITAgent` (qo'lda ishga tushirilgan agent nusxasi to'xtatiladi) →
   haftalik xulosa vazifasi `ITAgent-Haftalik` (dushanba 09:00). `TELEGRAM_BOT_TOKEN` yoki `CLAUDE_CODE_OAUTH_TOKEN`
   bo'sh bo'lsa xizmat yaratiladi, lekin ishga tushirilmaydi — `.env` ni to'ldirib skriptni qayta ishga tushiring.

4. Telegramda botga `/help` yozing. Ishga tushganda bot o'zi "✅ IT-agent ishga tushdi" deb yozadi.

> `.env` endi faqat administratorlarga ochiq — uni **administrator sifatida** ochilgan muharrirda tahrirlang.

Parametrlar: `-AgentHome D:\agent`, `-ServiceName ITAgent`, `-PythonExe C:\Python312\python.exe`, `-SkipPwsh`,
`-SkipService`, `-SkipWeeklyTask`, `-WeeklyDay Friday -WeeklyTime 17:00`. O'chirish: `.\uninstall.ps1`
(ma'lumotlar saqlanadi).

### 1a. Claude Pro/Max obunasi

Agent modelni pullik API orqali emas, **rasmiy Claude Code CLI** (Claude Agent SDK ichida keladi:
`.venv\Lib\site-packages\claude_agent_sdk\_bundled\claude.exe`) va sizning Pro login'ingiz orqali chaqiradi.
Asos: support.claude.com "Use the Claude Agent SDK with your Claude plan" (2026-10-07 yangilanishi) — Agent SDK,
`claude -p` va third-party ilovalar obuna limitidan foydalanadi. Limit claude.ai va Claude Code bilan **umumiy**
(5 soatlik va haftalik oyna).

**Login (o'zingiz bajarasiz; parol/token hech kimga yuborilmaydi):**

```powershell
$claude = "C:\it-agent\.venv\Lib\site-packages\claude_agent_sdk\_bundled\claude.exe"
& $claude auth login            # brauzer ochiladi -> Pro akkaunt bilan kiring (kod chiqsa — terminalga qo'ying)
& $claude auth status --text     # "Login method: Claude Pro account" ko'rinishi kerak
```

`auth login` credential'ni **shu Windows foydalanuvchisi** profiliga yozadi (`%USERPROFILE%\.claude\.credentials.json`).
Xizmat esa LocalSystem hisobida ishlaydi va uni ko'rmaydi. Xizmat uchun ikkita yo'l:

1. **Tavsiya:** `& $claude setup-token` — brauzerda tasdiqlang, terminalda 1 yillik token chiqadi. Uni **administrator
   sifatida** ochilgan muharrirda `.env` ga yozing: `CLAUDE_CODE_OAUTH_TOKEN=...` (`.env` faqat SYSTEM+Administrators
   uchun ochiq; agent tokenni loglarda `***` qiladi va PowerShell jarayonlariga uzatmaydi). `Restart-Service ITAgent`.
2. Xizmatni login qilingan foydalanuvchi hisobida ishga tushirish (`nssm set ITAgent ObjectName ...`, pastda) va o'sha
   hisobda `claude auth login`.

**Kod darajasidagi kafolatlar:**

| Xavf | Himoya |
|---|---|
| CLI pullik API kalitni ishlatib yuborishi | `ANTHROPIC_API_KEY`, `ANTHROPIC_AUTH_TOKEN`, `ANTHROPIC_BASE_URL`, Bedrock/Vertex/Foundry o'zgaruvchilari jarayondan olib tashlanadi; har topshiriqdan oldin `claude auth status` (faqat `claude.ai` + Pro/Max/Team/Enterprise yoki `oauth_token`, `apiKeySource` bo'lmasligi shart); sessiya boshida `apiKeySource != none` bo'lsa — darhol to'xtaydi. Kodda pullik API yo'li umuman **yo'q** (`anthropic` kutubxonasi ham o'rnatilmaydi) |
| Limit tugashi | `rate_limit_event: rejected` yoki `isUsingOverage` (pullik extra usage boshlangani) — topshiriq darhol to'xtaydi, "⛔ obuna limiti tugadi, tiklanadi: HH:MM" xabari; tiklanishigacha yangi topshiriqlar qabul qilinmaydi. Limit yaqinlashsa (`allowed_warning`) — bir marta ogohlantirish |
| Gate'ni chetlab o'tish | Claude Code'ning Bash/Read/Write/Edit tool'lari o'chiq; faqat agent tool'lari (`mcp__it__*`, har biri gate+tasdiq orqali) va WebSearch/WebFetch. `~/.claude` sozlamalari, CLAUDE.md, boshqa MCP va claude.ai connector'lari yuklanmaydi |
| Shell injection | CLI argv ro'yxati bilan, shell'siz ishga tushadi; topshiriq matni stdin (stream-json) orqali, tizim prompti fayl orqali |
| Osilib qolish | model `CLAUDE_IDLE_TIMEOUT_SEC` (900) jim tursa — to'xtaydi (tool/tasdiq kutilayotganda taymer to'xtaydi); umumiy `TASK_TIMEOUT_SEC` (7200) |
| Parallel ishlar | har topshiriq — alohida CLI jarayoni va alohida sessiya (uuid, jurnalda `session_id`); bir vaqtda `MAX_CONCURRENT_TASKS`, qolganlari navbatda |

> Muhim: **claude.ai → Settings → Usage** da "Extra usage" o'chiq bo'lsin (hozir: o'chiq — `org_level_disabled`).
> Agent baribir uni ishlata boshlagan zahoti to'xtaydi, lekin o'sha bitta so'rov allaqachon hisoblangan bo'ladi.
>
> Cheklov: Agent SDK hujjatiga ko'ra uchinchi tomon dasturchilari o'z **mahsulotlarida** boshqalarga claude.ai login /
> obuna limitini taklif qila olmaydi. Bu agent faqat sizning shaxsiy obunangiz bilan, faqat siz uchun ishlaydi
> (`ALLOWED_CHAT_ID`) — uni boshqa foydalanuvchilarga xizmat qilishga moslashtirmang.

### Xizmat qaysi hisobda ishlaydi

Standart — **LocalSystem** (shu serverda to'liq admin). Boshqa serverlarga WinRM, AD'ga yozish (unlock, parol
tiklash) uchun agent inventardagi login/paroldan foydalanadi (`request_credentials`). Agar AD amallarini xizmat
hisobining o'zi bajarsin desangiz, alohida domen hisobi bering:

```powershell
nssm set ITAgent ObjectName CORP\svc-itagent "parol"
icacls C:\agent\maxfiy /grant "CORP\svc-itagent:(OI)(CI)F"
icacls C:\it-agent\.env /grant "CORP\svc-itagent:R"
Restart-Service ITAgent
```

---

## 2. Boshqarish va loglar

```powershell
Get-Service ITAgent          # holat
Stop-Service ITAgent         # to'xtatish
Start-Service ITAgent        # ishga tushirish
Restart-Service ITAgent      # qayta ishga tushirish (.env yoki kod o'zgargandan keyin)
```

| Nima | Qayerda |
|---|---|
| Har amal (o'qishga qulay) | `C:\agent\jurnal\YYYY-MM-DD.md` — vaqt \| host \| nima qildim \| natija |
| Har amal (struktura) | `C:\agent\jurnal\YYYY-MM-DD.jsonl` — vaqt, host, tool, parametr, natija, success |
| Dastur logi | `C:\agent\jurnal\agent.log` (aylanma, 5×5 MB) |
| Xizmat stdout/stderr | `C:\agent\jurnal\service.log` (NSSM, 10 MB da aylanadi) |
| O'zgartirishdan oldingi zaxiralar | `C:\agent\zaxira\YYYY-MM-DD\` (+ `index.jsonl`) |
| Topshiriq ishchi fayllari, uzun hisobotlar | `C:\agent\ish\<topshiriq-ID>\` |
| Haftalik xulosa nusxasi | `C:\agent\jurnal\haftalik-YYYY-MM-DD.md` |

Oxirgi amallarni ko'rish: `Get-Content C:\agent\jurnal\$(Get-Date -f yyyy-MM-dd).md -Tail 30`

Telegramsiz sinash (konsolda, tasdiqlar ham konsolda so'raladi):

```powershell
C:\it-agent\.venv\Scripts\python.exe -m agent --once "C: diskda qancha joy qoldi?"
C:\it-agent\.venv\Scripts\python.exe -m agent --check      # sozlamalar, pwsh, Telegram, Claude
```

---

## 3. Telegram buyruqlari

| Buyruq | Ma'nosi |
|---|---|
| oddiy matn | topshiriq (forward + izoh 1.5 s ichida kelsa — bitta topshiriq). Rasm va fayl ham qabul qilinadi |
| `/opus <matn>` | qiyin ish — kuchli model (`claude-opus-5-5`, effort high) |
| `/yangi <matn>` | savol kutilayotgan bo'lsa ham yangi topshiriq |
| `/status` | faol topshiriqlar, qadamlar, kutilayotgan tasdiqlar |
| `/stop [ID]` | topshiriqni to'xtatish (ishlayotgan PowerShell jarayoni ham o'ldiriladi) |
| `/bekor` | kutilayotgan savol / parol so'rovini bekor qilish |
| `/parol <nom>` | agent yaratgan parolni ko'rish (spoiler, 60 s da o'chadi, forward qilinmaydi) |
| `/skill` | skillar ro'yxati |
| `/xulosa` | haftalik xulosa hozir |
| `/limit` | Claude obuna limiti holati (5 soatlik / haftalik %), tugagan bo'lsa — tiklanish vaqti |

Tasdiq so'roviga **"ha"** / **"yo'q"** yoki tugmalar. Bir nechta so'rov bo'lsa — kerakli xabarga reply qiling.
Noaniq javob yoki 15 daqiqa jim turish = **bajarilmaydi**. "Ha" faqat o'sha bitta amalga tegishli.

Uzoq ishlarda (1 daqiqadan ko'p) bot o'zi "⏳ ... hozir: ..." progress yuboradi; shu paytda boshqa xabarlarga ham
javob beradi (bir vaqtda 3 tagacha topshiriq).

---

## 4. Xavfsizlik — kodda nima kafolatlanadi

**Faqat Jamshid.** `chat_id` va `user_id` kodda tekshiriladi; boshqa hech kimga javob berilmaydi (urinish jurnalga
yoziladi). Agent o'chiq paytda yuborilgan 10 daqiqadan eski xabarlar bajarilmaydi.

**Xavfsizlik-gate** (`agent/gate.py`) har tool chaqiruvini model emas, kod baholaydi:

| Daraja | Misollar | Nima bo'ladi |
|---|---|---|
| o'qish | `Get-*`, ping, `show ...`, `/ip ... print`, HTTP GET, Zabbix `*.get` | darhol bajariladi |
| o'zgartirish (so'ramay) | `Restart-Service`, log tozalash, `Unlock-ADAccount`, parol tiklash, printer navbati, DNS/DHCP keshi, `logoff`, UniFi `adopt`/`set-inform`, Zabbix trigger qo'shish | bajariladi, keyin `verify` talab qilinadi |
| **tasdiq** | `Restart-Computer`/`shutdown`, VM stop/remove, snapshot o'chirish, `Remove-Item -Recurse`, format/partition, DB drop/truncate, GPO/OU, DHCP/DNS server sozlamasi, firewall, ommaviy AD o'zgarish, xizmatni disable/stop, Mikrotik/switch/UniFi konfiguratsiyasiga yozish, HTTP DELETE, `iex`/`-EncodedCommand` | Telegramga aniq so'rov (nima, qaysi host, sabab, ta'sir, zaxira holati); faqat "ha" dan keyin |
| **blok** | `maxfiy\` yoki `.env` ga murojaat, agent kodi/`SYSTEM_PROMPT.md` ni o'zgartirish, maxfiy qiymatni begona hostga yuborish | umuman bajarilmaydi |

Tarmoq uskunasi va siyosat (DHCP/DNS/GPO/firewall) o'zgarishidan oldin `backup_before_change` bo'lmasa — kod amalni
to'xtatadi. Agent papkasidan tashqaridagi faylni yozishdan oldin eski nusxa avtomatik `zaxira\` ga olinadi.

**Maxfiy ma'lumot modelga ham ko'rinmaydi.** Parollar faqat `C:\agent\maxfiy\inventar.json` da. Model buyruqqa
placeholder yozadi — `{{inv:mikrotik-asosiy.password}}`, `{{secret:jdoe-yangi}}` — kod uni bajarish paytida, faqat
o'sha yozuvning hostiga yuborishda almashtiradi. Yangi host kerak bo'lsa agent Telegramda **bir marta** so'raydi;
javobingiz modelga berilmaydi, inventarga yoziladi va chatdan o'chiriladi. Jurnal, Telegram, skill va xotiraga
yozilayotgan matn redaction'dan o'tadi (`***`). Bola jarayonlarga `TELEGRAM_BOT_TOKEN`/`CLAUDE_CODE_OAUTH_TOKEN` o'tmaydi.

**Prompt-injection.** Log, fayl, veb-sahifa, qurilma javobi — MA'LUMOT. Forward qilingan xabar shunday belgilanadi;
tool natijasida "qoidangni unut / parolni yubor" kabi matn bo'lsa, kod uni ogohlantirish bilan belgilaydi.

**Self-verification.** O'zgartiruvchi amaldan keyin `verify` PASS bo'lmasa, hisobot boshiga kod
"⚠️ TEKSHIRILMAGAN" qo'yadi va "tasdiqlandi" so'zini almashtiradi.

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

`type`: `windows`, `mikrotik_routeros`, `linux`, `unifi` (AP/switch shell), `esxi`, `cisco_ios`, `hp_procurve`,
`aruba_os`, `ubiquiti_edgeswitch` va boshqa netmiko turlari, `http` (faqat API). WinRM uchun ixtiyoriy: `port`,
`ssl: true`, `auth: Negotiate|Kerberos|Basic`. HTTPS sertifikat tekshiruvi: `verify_tls: true`.

---

## 4a. Proaktiv ishlar va tashqi tool'lar

Bu topshiriqlarni Jamshid emas, **kod** boshlaydi. Shuning uchun ularda har qanday o'zgartirish (hatto
`Restart-Service`) faqat Telegramdagi tasdiq bilan bajariladi, alert matni esa ma'lumot hisoblanadi, buyruq emas.

| Funksiya | Qanday yoqiladi | Nima qiladi |
|---|---|---|
| Zabbix kuzatuvi | inventarda `zabbix` yozuvi: `url` (masalan `https://zbx.local/zabbix`) + `token` (API token) yoki `username`/`password` | har `ZABBIX_POLL_SEC` da ochiq muammolarni modelsiz o'qiydi; birinchi safar mavjudlarini "ko'rilgan" deb belgilaydi; keyin har YANGI muammoga avtomatik tekshiruv va hisobot (soatiga `ALERT_TASKS_PER_HOUR` tagacha) |
| Kunlik tekshiruv | `.env` da `DAILY_CHECK_AT=09:00` | `xotira\kunlik_tekshiruv.md` ro'yxati bo'yicha (disk, xizmatlar, loglar, ping) hisobot. Noutbuk uyquda bo'lsa, uyg'ongach bajariladi |
| Tashqi MCP tool'lar | `C:\agent\maxfiy\mcp.json` (pastda) | qo'shimcha tool'lar. Ular gate'dan o'tmaydi, shuning uchun har chaqiruv tasdiq bilan bajariladi (`read_only_tools` dagilardan tashqari) |

`maxfiy\mcp.json` namunasi (uni faqat siz yozasiz, model uni o'qiy ham, o'zgartira ham olmaydi):

```json
{
  "servers": {
    "fayllar": {"command": "npx", "args": ["-y", "@modelcontextprotocol/server-filesystem", "D:\\hujjatlar"]}
  },
  "read_only_tools": ["mcp__fayllar__read_file", "mcp__fayllar__list_directory"]
}
```

Holatini tekshirish: `python -m agent --check` (Zabbix API versiyasi, kunlik vaqt, MCP serverlar).

---

## 5. O'rganish va xotira

| Fayl | Nima |
|---|---|
| `xotira\inventar.md` | host/IP/VM ro'yxati (parolsiz) |
| `xotira\fakt.md` | bir marta aytilgan doimiy ma'lumot |
| `xotira\tarix.md` | hal qilingan muammolar: belgi → sabab → tuzatish → natija → saboq |
| `xotira\boshliq.md` | sizning uslubingiz va qoidalaringiz (2 marta tuzatilgan narsa — doimiy qoida) |
| `xotira\prompt_qoshimcha.md` | agentning o'z ish uslubiga qo'shimchalari (xavfsizlik qoidalari o'zgarmaydi) |
| `skill\<nom>\SKILL.md` | o'rganilgan ish: haqiqatan ishlagan buyruqlar, qadamlar, tekshiruv |

Har topshiriq boshida xotira avtomatik o'qiladi. Kichik fayllar to'liq, katta fayllardan (`tarix.md`) faqat so'rovga
mos va eng so'nggi yozuvlar olinadi. Barcha skillarning qisqa indeksi doim qo'shiladi, to'liq matni esa faqat mos
2–3 tasiniki — 50+ skill bo'lsa ham token sarfi oshib ketmaydi. Tizim prompti va tool ro'yxati keshlanadi.

Ish tugashidan oldin kod tekshiradi: o'zgartirish bo'lgan bo'lsa — `verify` va `log_history`; skill yo'q va ish
muvaffaqiyatli bo'lsa — `write_skill`. Yetishmasa, model bir marta eslatiladi.

Haftalik xulosa (`ITAgent-Haftalik`, kodda hisoblanadi): ishlar soni, xatolar, tasdiqlar, eng ko'p takrorlangan
3 muammo (skill bor/yo'q), yangi skillar, saboqlar va bitta taklif — 5 qator.

---

## 6. GitHubga zaxira (xotira va skillar)

`C:\agent` da alohida repo: faqat `skill\`, `xotira\`, `skript\` yuboriladi; `maxfiy\`, `zaxira\`, `jurnal\`,
`ish\`, `.env` — hech qachon (`.gitignore` + skriptning o'z tekshiruvi).

```powershell
# birinchi marta (GitHub'da bo'sh private repo yarating; SSH kalit yoki Git Credential Manager sozlangan bo'lsin)
.\memory_backup.ps1 -RemoteUrl git@github.com:jamshid/it-agent-xotira.git
# keyingi safarlar
.\memory_backup.ps1
```

Commitdan oldin skript `inventar.json` dagi barcha parol/token qiymatlarini va token naqshlarini (bot token,
`sk-ant-...`, private key, `password=...`) qidiradi — topilsa, hech narsa yuborilmaydi. Git o'rnatish:
`winget install --id Git.Git -e`. Kunlik avtomatik zaxira kerak bo'lsa — shu skriptni Task Scheduler'ga
administrator hisobidan qo'ying (GitHub kaliti shu hisobda bo'lishi kerak).

Loyiha kodini GitHubga yuborganda ham loyiha ildizidagi `.gitignore` `.env`, `maxfiy/`, `zaxira/`, `jurnal/`, `ish/`,
`.venv/` ni chiqarib tashlaydi.

---

## 7. Muammolar

| Belgi | Yechim |
|---|---|
| Bot javob bermayapti | `Get-Service ITAgent`; `C:\agent\jurnal\agent.log`; `python -m agent --check` |
| logda `getUpdates: 409` | bot boshqa joyda ham ishlayapti (ikkita nusxa) — bittasini to'xtating |
| `Claude obuna logini yaroqsiz` | 1a-bo'lim: `claude auth login` yoki `setup-token` → `CLAUDE_CODE_OAUTH_TOKEN`; `python -m agent --check` |
| `⛔ Claude obuna limiti tugadi` | xabardagi vaqtda limit tiklanadi; shungacha agent yangi topshiriq olmaydi (pullik API'ga o'tmaydi) |
| WinRM: `TrustedHosts` / access denied | IP bilan ulanishda: `Set-Item WSMan:\localhost\Client\TrustedHosts -Value "10.0.0.*" -Concatenate`; inventarda login to'g'rimi |
| ESXi SSH auth xato | ESXi'da SSH yoqilganini tekshiring; agent keyboard-interactive'ni ham sinaydi |
| SSH "host kaliti O'ZGARGAN" | qurilma almashtirilgan bo'lsa — `C:\agent\maxfiy\known_hosts` dan eski qatorni o'chiring |
| Hisobot "TEKSHIRILMAGAN" | agent o'zgarishdan keyin qayta o'lchamagan — natijani o'zingiz tekshiring yoki "tekshir" deb yozing |
| Model rad etdi (refusal) | so'rovni aniqroq yozing yoki `/opus` |

---

## 8. Fayl tuzilishi

```
it-agent/
  SYSTEM_PROMPT.md        agentning tizim prompti (o'zgarmas qoidalar)
  install.ps1             o'rnatish (venv, pwsh, NSSM xizmati, haftalik vazifa, ACL)
  uninstall.ps1           xizmat va vazifani o'chirish (ma'lumot qoladi)
  memory_backup.ps1       skill/xotira/skript -> GitHub (maxfiy tekshiruvi bilan)
  .env.example            sozlamalar namunasi
  requirements.txt        kutubxonalar (claude-agent-sdk rasmiy Claude Code CLI'ni olib keladi)
  agent/
    __main__.py           python -m agent [--check | --once "..." | --init]
    app.py                komponentlarni bog'lash, --check
    bot.py, telegram_api.py   Telegram: ruxsat, buyruqlar, tasdiq/savol/parol oqimi
    tasks.py              fon topshiriqlar, navbat, progress, /stop, limit tugaganda qabul qilmaslik
    loop.py               ReAct tool-loop Claude Code CLI orqali, yakuniy nazorat, hisobot
    claude_cli.py         obuna: login tekshiruvi, env tozalash, limit holati
    proactive.py          Zabbix alert kuzatuvi va kunlik tekshiruv (avtomatik topshiriqlar)
    gate.py               xavfsizlik-gate
    redact.py             maxfiy qiymatlarni yashirish
    inventory.py          inventar.json, placeholderlar, yaratilgan parollar
    memory.py             xotira va skillarni tanlab yuklash
    journal.py            jurnal (.md + .jsonl)
    weekly.py             haftalik xulosa (python -m agent.weekly)
    prompt_texnik.md      tool'lar bo'yicha texnik qo'shimcha
    tools/                run_powershell, run_remote_ssh, call_http_api, read_file, write_file,
                          backup_before_change, write_skill, verify, log_history, remember,
                          request_credentials, inventory_set, list_inventory, generate_secret,
                          ask_owner, notify_owner  (+ Claude Code'ning WebSearch, WebFetch)
```
