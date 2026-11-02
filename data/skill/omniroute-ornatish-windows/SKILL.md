---
name: omniroute-ornatish-windows
description: Windowsda OmniRoute (AI gateway) ni npm orqali o'rnatish: Node.js, uzun yo'l muammosi, faqat loopback, ishga tushirish va tekshirish.
triggers: omniroute, ai gateway, npm install -g, node.js o'rnatish, TAR_ENTRY_ERROR, long path
yaratilgan: 2026-10-28
yangilangan: 2026-10-28
versiya: 1
---

# omniroute-ornatish-windows

1. Talab: Node.js >=22.22.2 <23 yoki >=24 <27. Tekshiruv: node -v. Yo'q bo'lsa: winget install --id OpenJS.NodeJS.LTS -e --accept-package-agreements --accept-source-agreements
2. Yangi PATH ni sessiyaga yuklash: $env:Path = [Environment]::GetEnvironmentVariable('Path','Machine') + ';' + [Environment]::GetEnvironmentVariable('Path','User')
3. Standart npm install -g omniroute Windowsda TAR_ENTRY_ERROR / ENOENT bilan buzilishi mumkin (LongPathsEnabled=0, bo'sh RAM kam). Buzilgan %APPDATA%\npm\node_modules\omniroute ni o'chiring.
4. Qisqa prefiksga o'rnatish (ishlagan, ~13 daqiqa): $env:NODE_OPTIONS='--max-old-space-size=3072'; cmd /c "npm install -g omniroute --prefix D:\or --no-audit --no-fund --loglevel=error --legacy-peer-deps > log.txt 2>&1"
5. PATH ga D:\or qo'shish (User).
6. Xavfsizlik: sukut bo'yicha 0.0.0.0 da kalitsiz eshitadi. Faqat loopback: OMNIROUTE_SERVER_HOST=127.0.0.1 (User env va sessiyada).
7. Ishga tushirish fonda: Start-Process cmd -ArgumentList '/c','D:\or\omniroute.cmd > log 2>&1' -WindowStyle Hidden ; ~40-60 s kuting.
8. Tekshiruv: Get-NetTCPConnection -LocalPort 20128 -State Listen (LocalAddress 127.0.0.1) va verify http://localhost:20128 -> 200.
9. Keyin: Dashboard -> Providers da provayder qo'shish, Dashboard -> Endpoints dan kalit; API http://localhost:20128/v1, model auto.
Eslatma: avtostart yo'q; serverga ko'chirishda qayta o'rnatiladi (data papkasi alohida ko'chiriladi).
