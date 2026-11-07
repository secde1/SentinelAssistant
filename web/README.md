# SENTINAL CONTROL CENTER — frontend

Next.js (App Router) + TypeScript + Tailwind CSS, **statik eksport** (`output: "export"`). Server yo'q: `npm run build`
natijasi (`out/`) ni Python server `agent/dashboard/server.py` 127.0.0.1 da tarqatadi va `/api/*` ni o'zi beradi.

```powershell
npm ci
npm run build     # -> out/
npx eslint src
```

Ishlab chiqishda: avval `..\dashboard.cmd --no-browser` (API), keyin build qilib brauzerni yangilang. `next dev`
API'ni proksi qilmaydi — sahifalar `/api/*` ni o'sha manzildan so'raydi.

Tuzilma: `src/app/*` — sahifalar (hammasi klient komponentlar), `src/components` — qobiq, UI va SVG grafiklar
(tashqi kutubxonasiz), `src/lib` — API klient, tiplar, formatlash. Batafsil: loyiha README, 5a-bo'lim.
