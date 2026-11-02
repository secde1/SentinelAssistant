---
name: omniroute-ornatish
description: Windows'da OmniRoute (AI gateway, npm paketi omniroute) ni o'rnatish va localhost:20128 da ishga tushirish.
triggers: omniroute, ai gateway, npm global, node, 20128
yaratilgan: 2026-10-28
yangilangan: 2026-10-28
versiya: 1
---

# omniroute-ornatish

1. PATH yangilash (sessiyada node ko'rinmasa): $env:Path = [Environment]::GetEnvironmentVariable('Path','Machine') + ';' + [Environment]::GetEnvironmentVariable('Path','User'); node -v (kerak: >=22.22.2 <23 yoki >=24).
2. Node yo'q bo'lsa: winget install --id OpenJS.NodeJS.LTS --silent --accept-package-agreements --accept-source-agreements
3. Neytral papkadan o'rnatish (agent papkasidan EMAS): Set-Location $env:TEMP; npm install -g omniroute --legacy-peer-deps --no-audit --no-fund --maxsockets=1 (~12-18 daqiqa, timeout_sec katta qo'y).
4. Tekshiruv: Test-Path $env:APPDATA\npm\node_modules\omniroute\node_modules\zod\package.json va ...\dist. Agar zod yo'q / "Cannot find package" bo'lsa: npm uninstall -g omniroute, keyin 3-qadamni qayta.
5. Ishga tushirish (sessiyadan ajratib, C:\omniroute-run da): Invoke-CimMethod -ClassName Win32_Process -MethodName Create -Arguments @{CommandLine='cmd.exe /c omniroute > D:\it-agent\data\ish\omniroute.log 2>&1'; CurrentDirectory='C:\omniroute-run'}
   Start-Process bilan ishga tushirsa sessiya tugagach o'ladi.
6. Verify: (Invoke-WebRequest http://localhost:20128/dashboard -UseBasicParsing).StatusCode = 200. /v1/models ochiq 401 beradi (kalit kerak) — bu normal.
Xatolar: ENOENT/TAR_ENTRY_ERROR — qayta urinish; EADDRINUSE — server allaqachon ishlayapti (portni tekshir); cwd da .env bo'lsa omniroute uni o'qiydi, shuning uchun agent papkasidan ishga tushirma. Avtostart sozlanmagan (kerak bo'lsa schtasks).
