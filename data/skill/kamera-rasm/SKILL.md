---
name: kamera-rasm
description: Ноутбук веб-камерасидан расм олиб Jamshidga Telegram орқали юбориш.
triggers: камера, расм, kamera, rasm, фото, webcam, camera photo
yaratilgan: 2026-10-28
yangilangan: 2026-10-28
versiya: 1
---

# kamera-rasm

1. Скрипт: D:\it-agent\data\skript\kamera_rasm.py (cv2.VideoCapture(0, CAP_DSHOW), 25 кадр иситиш, расм D:\it-agent\data\ish\kamera\laptop.jpg га ёзилади).
2. Агар "No module named cv2": 
   $py='D:\it-agent\.venv\Scripts\python.exe'
   & $py -m ensurepip
   & $py -m pip install opencv-python-headless
3. Папка бор эканини таъминла: New-Item -ItemType Directory -Force D:\it-agent\data\ish\kamera
4. Ишга туширинг: & $py D:\it-agent\data\skript\kamera_rasm.py   (чиқиш: "OK (480, 640, 3)")
5. Скриптдаги сақлаш йўли D:\it-agent\data\ish\kamera\laptop.jpg бўлиши шарт (эски C:\ йўли файлни янгиламайди).
6. Текширув: (Get-Item D:\it-agent\data\ish\kamera\laptop.jpg) LastWriteTime — бугунги сана ва Length > 0 (verify method=powershell).
7. Юбориш: notify_owner(file_path="D:\it-agent\data\ish\kamera\laptop.jpg").
Хатолар: OPEN_FAIL (exit 2) — камера банд/ўчиқ; READ_FAIL (exit 3) — кадр ўқилмади. Камера ишлатилганини Jamshidga айт.
