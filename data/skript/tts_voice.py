"""Matnni ovozga aylantirib Telegram voice (ogg/opus) fayl yaratadi.
Ishlatish: python tts_voice.py "matn" [uz|ru|en] [chiqish.ogg]
Ovozlar: uz=uz-UZ-MadinaNeural, ru=ru-RU-SvetlanaNeural, en=en-US-JennyNeural (edge-tts, internet kerak)."""
import asyncio
import subprocess
import sys
from pathlib import Path

import edge_tts
import imageio_ffmpeg

VOICES = {"uz": "uz-UZ-MadinaNeural", "ru": "ru-RU-SvetlanaNeural", "en": "en-US-JennyNeural"}


async def main(text: str, lang: str, out: Path) -> None:
    mp3 = out.with_suffix(".mp3")
    await edge_tts.Communicate(text, VOICES[lang], rate="-4%").save(str(mp3))
    subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(), "-y", "-i", str(mp3), "-c:a", "libopus", "-b:a", "64k",
                    "-ar", "48000", "-ac", "1", str(out)], check=True, capture_output=True)
    mp3.unlink(missing_ok=True)
    print(out)


if __name__ == "__main__":
    t = sys.argv[1]
    lg = sys.argv[2] if len(sys.argv) > 2 else "ru"
    o = Path(sys.argv[3] if len(sys.argv) > 3 else r"C:\agent\ish\voice.ogg")
    asyncio.run(main(t, lg, o))
