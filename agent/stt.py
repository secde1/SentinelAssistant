"""Ovozli xabarni matnga aylantirish (faster-whisper) — pullik API'siz, kompyuterning o'zida, ovoz tashqariga chiqmaydi.

Telegram ovozli xabari OGG/Opus. Audio PyAV (faster-whisper bilan keladi) bilan 16 kHz mono'ga dekodlanadi va
modelga numpy massiv sifatida beriladi — bu faster-whisper'ning o'z dekoderidagi versiya nomuvofiqligini chetlab o'tadi.
Model birinchi ovozli xabarda yuklanadi (xizmat ishga tushishini sekinlashtirmasin); keyin xotirada qoladi.
Model va hisob CPU'ni band qiladi — shuning uchun to_thread'da ishlaydi, bot hodisa sikli bloklanmaydi.
"""
from __future__ import annotations

import asyncio
import logging
import os
from pathlib import Path

log = logging.getLogger(__name__)

os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")


def decode_16k_mono(path: Path):
    """OGG/Opus/boshqa audio -> 16 kHz mono float32 numpy massiv."""
    import av
    import numpy as np

    container = av.open(str(path), mode="r")
    try:
        if not container.streams.audio:
            return np.zeros(0, dtype=np.float32)
        stream = container.streams.audio[0]
        resampler = av.audio.resampler.AudioResampler(format="s16", layout="mono", rate=16000)
        chunks = []
        for frame in container.decode(stream):
            frame.pts = None
            for rs in resampler.resample(frame):
                chunks.append(rs.to_ndarray().reshape(-1))
    finally:
        container.close()
    if not chunks:
        return np.zeros(0, dtype=np.float32)
    return np.concatenate(chunks).astype("float32") / 32768.0


class Transcriber:
    def __init__(self, model: str, language: str, download_root: Path):
        # small o'zbekchani yomon taniydi -> kamida large-v3-turbo
        self.model_name = model if model and model not in ("tiny", "base", "small") else "large-v3-turbo"
        self.language = (language or "").strip() or None  # None = avtomatik aniqlash (uz/ru)
        self.download_root = Path(download_root)
        self._model = None
        self._lock = asyncio.Lock()

    def _load(self):
        from faster_whisper import WhisperModel

        self.download_root.mkdir(parents=True, exist_ok=True)
        log.info("STT modeli yuklanmoqda: %s (birinchi marta internetdan tushadi)", self.model_name)
        return WhisperModel(self.model_name, device="cpu", compute_type="int8",
                            download_root=str(self.download_root))

    def _run(self, audio) -> str:
        lang = self.language
        if lang is None:
            lang = self._pick_language(audio)
        segments, _info = self._model.transcribe(
            audio, language=lang, vad_filter=True, beam_size=5, condition_on_previous_text=False)
        return " ".join(s.text.strip() for s in segments).strip()

    def _pick_language(self, audio) -> str:
        """Faqat uz/ru/en orasidan tanlaydi. Turkiy tillar (kk, tr, az, tk, ky, tt, ba) uz ga qo'shiladi."""
        try:
            _l, _p, probs = self._model.detect_language(audio[: 16000 * 30])
            pr = dict(probs)
        except Exception:
            return "uz"
        uz = pr.get("uz", 0.0) + sum(pr.get(k, 0.0) for k in ("kk", "tr", "az", "tk", "ky", "tt", "ba"))
        ru = pr.get("ru", 0.0)
        en = pr.get("en", 0.0)
        best = max((uz, "uz"), (ru, "ru"), (en, "en"))
        return best[1]

    async def transcribe(self, path: Path) -> str:
        """Ovozli fayl -> matn. Bo'sh/jim bo'lsa bo'sh satr. Xato ko'tarilsa chaqiruvchi ushlaydi."""
        audio = await asyncio.to_thread(decode_16k_mono, path)
        if getattr(audio, "size", 0) == 0:
            return ""
        async with self._lock:
            if self._model is None:
                self._model = await asyncio.to_thread(self._load)
        return await asyncio.to_thread(self._run, audio)
