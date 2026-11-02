"""Ovoz (TTS) va audio trek. Har subtitr bo'lagi alohida o'qiladi — subtitr vaqti ovoz bilan aniq mos keladi.

Dvijoklar:
  azure — Azure AI Speech (rasmiy; bepul tarifda oyiga 500 ming belgi). AZURE_SPEECH_KEY + AZURE_SPEECH_REGION.
  edge  — edge-tts (Microsoft Edge "ovoz chiqarib o'qish" xizmatiga norasmiy ulanish). Sinov uchun; ochiq e'lon
          qilinadigan video uchun litsenziyasi noaniq — tasdiq xabarida ogohlantiriladi.
O'zbekcha neyron ovozlar (uz-UZ-MadinaNeural, uz-UZ-SardorNeural) kirillni o'qimaydi — matn lotinda beriladi.
"""
from __future__ import annotations

import asyncio
import logging
import wave
from dataclasses import dataclass
from pathlib import Path
from xml.sax.saxutils import escape

import numpy as np

log = logging.getLogger(__name__)

SAMPLE_RATE = 44100
LEAD_IN = 0.35       # boshidagi jimlik (s)
SENTENCE_GAP = 0.18  # gaplar orasida
SCENE_GAP = 0.45     # sahnalar orasida
TAIL = 0.9           # oxiridagi jimlik


class TTSError(Exception):
    pass


@dataclass
class Clip:
    scene: int
    text_screen: str  # subtitr (kirill)
    start: float = 0.0
    end: float = 0.0


def pick_engine(mode: str, azure_key: str) -> str:
    if mode == "azure" or (mode == "auto" and azure_key):
        return "azure"
    return "edge"


async def _synth_edge(text: str, voice: str, out: Path, rate: str) -> None:
    import edge_tts

    await edge_tts.Communicate(text, voice, rate=rate).save(str(out))


async def _synth_azure(text: str, voice: str, out: Path, rate: str, key: str, region: str) -> None:
    import httpx

    ssml = (f"<speak version='1.0' xml:lang='uz-UZ'><voice name='{escape(voice)}'>"
            f"<prosody rate='{escape(rate)}'>{escape(text)}</prosody></voice></speak>")
    async with httpx.AsyncClient(timeout=60) as client:
        r = await client.post(f"https://{region}.tts.speech.microsoft.com/cognitiveservices/v1",
                              content=ssml.encode("utf-8"),
                              headers={"Ocp-Apim-Subscription-Key": key, "Content-Type": "application/ssml+xml",
                                       "X-Microsoft-OutputFormat": "audio-24khz-96kbitrate-mono-mp3",
                                       "User-Agent": "sentinal-agent"})
    if r.status_code != 200:
        raise TTSError(f"Azure TTS: HTTP {r.status_code}")  # kalit xato matniga tushmaydi
    out.write_bytes(r.content)


async def synth(text: str, out: Path, engine: str, voice: str, rate: str = "+0%",
                azure_key: str = "", azure_region: str = "", attempts: int = 3) -> None:
    for attempt in range(1, attempts + 1):
        try:
            if engine == "azure":
                await _synth_azure(text, voice, out, rate, azure_key, azure_region)
            else:
                await _synth_edge(text, voice, out, rate)
            if out.exists() and out.stat().st_size > 0:
                return
            raise TTSError("bo'sh audio qaytdi")
        except Exception as exc:  # noqa: BLE001 — tarmoq/xizmat xatosi: qisqa kutib qayta urinamiz
            if attempt == attempts:
                raise TTSError(f"{engine} TTS {attempts} urinishda ishlamadi: {type(exc).__name__}: {exc}") from None
            log.warning("TTS urinish %d xato: %s", attempt, exc)
            await asyncio.sleep(2 * attempt)


def decode(path: Path) -> np.ndarray:
    """mp3 -> float32 mono 44.1 kHz."""
    import av

    chunks = []
    with av.open(str(path)) as container:
        resampler = av.audio.resampler.AudioResampler(format="s16", layout="mono", rate=SAMPLE_RATE)
        for frame in container.decode(audio=0):
            for rs in resampler.resample(frame):
                chunks.append(rs.to_ndarray().reshape(-1))
        for rs in resampler.resample(None):
            chunks.append(rs.to_ndarray().reshape(-1))
    if not chunks:
        raise TTSError(f"{path.name}: audio bo'sh")
    return np.concatenate(chunks).astype(np.float32) / 32768.0


def build_track(clips: list[Clip], audio: list[np.ndarray]) -> tuple[np.ndarray, float]:
    """Bo'laklarni pauzalar bilan bitta trekka yig'adi va har bo'lakka start/end yozadi. -> (trek, davomiylik)."""
    parts = [np.zeros(int(LEAD_IN * SAMPLE_RATE), dtype=np.float32)]
    t = LEAD_IN
    for i, (clip, samples) in enumerate(zip(clips, audio)):
        if i:
            gap = SCENE_GAP if clip.scene != clips[i - 1].scene else SENTENCE_GAP
            parts.append(np.zeros(int(gap * SAMPLE_RATE), dtype=np.float32))
            t += gap
        clip.start = t
        t += len(samples) / SAMPLE_RATE
        clip.end = t
        parts.append(samples)
    parts.append(np.zeros(int(TAIL * SAMPLE_RATE), dtype=np.float32))
    track = np.concatenate(parts)
    return track, len(track) / SAMPLE_RATE


def write_wav(track: np.ndarray, path: Path) -> None:
    pcm = (np.clip(track, -1.0, 1.0) * 32767).astype("<i2")
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SAMPLE_RATE)
        w.writeframes(pcm.tobytes())
