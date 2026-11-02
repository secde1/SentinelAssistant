"""Ovozli xabarni matnga aylantirish (faster-whisper) — pullik API'siz, kompyuterning o'zida, ovoz tashqariga chiqmaydi.

Telegram ovozli xabari OGG/Opus. Audio avval ffmpeg bilan tozalanib (shovqin, jimlik) 16 kHz mono'ga o'tkaziladi;
ffmpeg bo'lmasa PyAV (faster-whisper bilan keladi) ishlatiladi. Model — AGENT_HOME/modellar/<STT_MODEL> dagi
CTranslate2 o'zbekcha whisper (standart: univoice-stt-uz-ct2). Model birinchi ovozli xabarda yuklanadi va xotirada
qoladi; hisob CPU'ni band qiladi — shuning uchun to_thread'da ishlaydi, bot hodisa sikli bloklanmaydi.
Natijadagi IT atamalari IT_GLOSSARY bilan to'g'rilanadi.
"""
from __future__ import annotations

import asyncio
import logging
import os
import re
import subprocess
import tempfile
import wave
from contextlib import suppress
from datetime import datetime
from pathlib import Path

log = logging.getLogger(__name__)

os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")

FFMPEG_BASE = "highpass=f=80,lowpass=f=8000,loudnorm"
_TRIM = "silenceremove=start_periods=1:start_threshold=-45dB:start_silence=0.15"
FFMPEG_FILTER = _TRIM + ",areverse," + _TRIM + ",areverse," + FFMPEG_BASE  # boshi/oxiridagi jimlik kesiladi

# IT atamalari: STT xato yozgan shakl -> to'g'ri shakl (regex, so'z chegarasida).
# Umumiy so'zlarni (masalan "eski server") qo'shmang — noto'g'ri almashtiradi.
IT_GLOSSARY = [
    (r"\bunifi\s+(tantrol\w*|kontrol\w*|controller\w*)", "UniFi controller"),
    (r"\bzabih\w*", "Zabbix"),
    (r"\bzabbiks\w*", "Zabbix"),
    (r"\bspoyler\w*", "Spooler"),
    (r"\bspooler\b", "Spooler"),
    (r"\bmikrotik\b", "Mikrotik"),
    (r"\bunifi\b", "UniFi"),
    (r"\badob\b", "adopt"),
    (r"\bvintovs\b", "Windows"),
]


def _clean_with_ffmpeg(path: Path):
    """ffmpeg: 16 kHz mono + shovqin/balandlik tozalash -> float32 massiv. ffmpeg yo'q yoki xato bo'lsa None."""
    import numpy as np

    try:
        import imageio_ffmpeg

        exe = imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:  # noqa: BLE001 — ffmpeg ixtiyoriy
        return None
    tmp = Path(tempfile.gettempdir()) / (Path(path).stem + "_clean.wav")
    try:
        for flt in (FFMPEG_FILTER, FFMPEG_BASE):
            r = subprocess.run([exe, "-y", "-i", str(path), "-ar", "16000", "-ac", "1", "-af", flt, str(tmp)],
                               capture_output=True, timeout=120)
            if r.returncode != 0 or not tmp.exists():
                continue
            with wave.open(str(tmp), "rb") as w:
                raw = w.readframes(w.getnframes())
            arr = np.frombuffer(raw, dtype=np.int16).astype("float32") / 32768.0
            if arr.size >= 16000 * 0.3 or flt == FFMPEG_BASE:  # jimlik kesish hammasini yeb qo'ysa — oddiy filtr
                return arr
        return None
    except Exception as exc:  # noqa: BLE001
        log.warning("ffmpeg tozalash ishlamadi: %s", exc)
        return None
    finally:
        with suppress(OSError):
            tmp.unlink(missing_ok=True)


def decode_16k_mono(path: Path):
    """OGG/Opus/boshqa audio -> 16 kHz mono float32 numpy massiv (avval ffmpeg bilan tozalanadi)."""
    cleaned = _clean_with_ffmpeg(path)
    if cleaned is not None and cleaned.size:
        return cleaned
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


def apply_glossary(text: str) -> str:
    for pat, rep in IT_GLOSSARY:
        text = re.sub(pat, rep, text, flags=re.IGNORECASE)
    return text


class Transcriber:
    def __init__(self, model: str, language: str, download_root: Path):
        self.model_path = Path(download_root) / model
        # Qat'iy til: avtoaniqlash o'zbekchani ru/en deb o'qirdi.
        self.language = (language or "").strip() or "uz"
        self._model = None
        self._lock = asyncio.Lock()

    @property
    def runtime_log(self) -> Path:
        # AGENT_HOME .env dan keladi — papka ko'chsa ham yo'l to'g'ri qoladi.
        return Path(os.environ.get("AGENT_HOME") or r"C:\agent") / "jurnal" / "stt_runtime.log"

    def _rlog(self, msg: str) -> None:
        try:
            with open(self.runtime_log, "a", encoding="utf-8") as f:
                f.write(f"{datetime.now():%Y-%m-%d %H:%M:%S} | {msg}\n")
        except OSError:
            pass

    def _load(self):
        from faster_whisper import WhisperModel

        log.info("STT modeli yuklanmoqda: %s", self.model_path)
        return WhisperModel(str(self.model_path), device="cpu", compute_type="int8")

    def _run(self, audio) -> str:
        """Prompt va timestamp YO'Q — univoice model kartasi talabi. Xato bo'lsa bo'sh satr (bot matn so'raydi)."""
        try:
            if self._model is None:
                self._model = self._load()
            segments, _info = self._model.transcribe(audio, language=self.language, task="transcribe", beam_size=5,
                                                     without_timestamps=True, condition_on_previous_text=False,
                                                     temperature=0, vad_filter=True)
            segs = list(segments)
            text = " ".join(s.text.strip() for s in segs).strip()
            logprob = sum(s.avg_logprob for s in segs) / len(segs) if segs else -9.0
            self._rlog(f"model={self.model_path.name} language={self.language} logprob={logprob:.2f} raw={text!r}")
            return text
        except Exception as exc:  # noqa: BLE001
            self._rlog(f"XATO ({self.model_path.name}): {exc!r}")
            return ""

    async def transcribe(self, path: Path) -> str:
        """Ovozli fayl -> matn. Bo'sh/jim bo'lsa bo'sh satr."""
        audio = await asyncio.to_thread(decode_16k_mono, path)
        if getattr(audio, "size", 0) == 0:
            return ""
        async with self._lock:
            return apply_glossary(await asyncio.to_thread(self._run, audio))
