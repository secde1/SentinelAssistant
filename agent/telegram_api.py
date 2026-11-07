"""Telegram Bot API uchun kichik asinxron klient (long polling). Token hech qachon log/xato matniga chiqmaydi."""
from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from typing import Any

import httpx

log = logging.getLogger(__name__)


class TelegramError(Exception):
    pass


class TelegramNetworkError(TelegramError):
    """Telegram'ga umuman yetib bo'lmadi (internet yo'q, DNS, timeout) — token yoki so'rov xatosi emas."""


class TelegramAPI:
    def __init__(self, token: str, client: httpx.AsyncClient | None = None):
        self._base = f"https://api.telegram.org/bot{token}"
        self._file_base = f"https://api.telegram.org/file/bot{token}"
        self.client = client or httpx.AsyncClient(timeout=httpx.Timeout(70.0, connect=15.0))

    async def call(self, method: str, payload: dict | None = None, files: dict | None = None,
                   timeout: float | None = None, retries: int = 4) -> Any:
        extra = {"timeout": timeout} if timeout is not None else {}  # None httpx'da "cheksiz" degani
        for attempt in range(retries + 1):
            try:
                if files:
                    r = await self.client.post(f"{self._base}/{method}", data=payload or {}, files=files, **extra)
                else:
                    r = await self.client.post(f"{self._base}/{method}", json=payload or {}, **extra)
                data = r.json()
            except (httpx.HTTPError, ValueError) as exc:
                # Xato matnida URL (token bilan) bo'lishi mumkin — faqat turini ko'rsatamiz.
                if attempt >= retries:
                    raise TelegramNetworkError(f"{method}: tarmoq xatosi ({type(exc).__name__})") from None
                await asyncio.sleep(min(30, 2 ** attempt))
                continue
            if data.get("ok"):
                return data.get("result")
            retry_after = (data.get("parameters") or {}).get("retry_after")
            if r.status_code == 429 and retry_after is not None and attempt < retries:
                await asyncio.sleep(float(retry_after) + 1)
                continue
            raise TelegramError(f"{method}: {data.get('error_code')} {data.get('description')}")
        raise TelegramError(f"{method}: urinishlar tugadi")

    async def get_me(self) -> dict:
        return await self.call("getMe")

    async def get_updates(self, offset: int | None, timeout: int = 50) -> list[dict]:
        payload: dict = {"timeout": timeout, "allowed_updates": ["message", "callback_query", "my_chat_member", "business_connection", "business_message", "edited_business_message", "deleted_business_messages"]}
        if offset is not None:
            payload["offset"] = offset
        return await self.call("getUpdates", payload, timeout=timeout + 20, retries=0) or []

    async def send_message(self, chat_id: int, text: str, reply_markup: dict | None = None, parse_mode: str | None = None,
                           protect: bool = False, reply_to: int | None = None) -> dict:
        payload: dict = {"chat_id": chat_id, "text": text, "disable_web_page_preview": True}
        if reply_markup:
            payload["reply_markup"] = reply_markup
        if parse_mode:
            payload["parse_mode"] = parse_mode
        if protect:
            payload["protect_content"] = True
        if reply_to:
            payload["reply_parameters"] = {"message_id": reply_to, "allow_sending_without_reply": True}
        return await self.call("sendMessage", payload)

    async def send_business_message(self, connection_id: str, chat_id: int, text: str) -> dict:
        return await self.call("sendMessage", {"business_connection_id": connection_id, "chat_id": chat_id,
                                               "text": text, "disable_web_page_preview": True}, retries=1)

    async def edit_message_text(self, chat_id: int, message_id: int, text: str) -> None:
        try:
            await self.call("editMessageText", {"chat_id": chat_id, "message_id": message_id, "text": text,
                                                "disable_web_page_preview": True})
        except TelegramError as exc:
            if "not modified" not in str(exc):
                log.warning("editMessageText: %s", exc)

    async def answer_callback(self, callback_id: str, text: str = "") -> None:
        try:
            await self.call("answerCallbackQuery", {"callback_query_id": callback_id, "text": text})
        except TelegramError as exc:
            log.warning("answerCallbackQuery: %s", exc)

    async def delete_message(self, chat_id: int, message_id: int) -> bool:
        try:
            await self.call("deleteMessage", {"chat_id": chat_id, "message_id": message_id})
            return True
        except TelegramError as exc:
            log.warning("deleteMessage: %s", exc)
            return False

    async def send_document(self, chat_id: int, path: Path, caption: str = "") -> dict:
        with open(path, "rb") as fh:
            content = fh.read()
        if path.suffix.lower() in (".ogg", ".opus"):
            return await self.call("sendVoice", {"chat_id": str(chat_id), "caption": caption[:1000]},
                                   files={"voice": (path.name, content)}, timeout=120)
        return await self.call("sendDocument", {"chat_id": str(chat_id), "caption": caption[:1000]},
                               files={"document": (path.name, content)}, timeout=120)

    async def send_video(self, chat_id: int, path: Path, caption: str = "", reply_markup: dict | None = None,
                         width: int = 1080, height: int = 1920, duration: int = 0) -> dict:
        with open(path, "rb") as fh:
            content = fh.read()
        payload = {"chat_id": str(chat_id), "caption": caption[:1000], "supports_streaming": "true",
                   "width": str(width), "height": str(height)}
        if duration:
            payload["duration"] = str(duration)
        if reply_markup:
            payload["reply_markup"] = json.dumps(reply_markup)
        return await self.call("sendVideo", payload, files={"video": (path.name, content, "video/mp4")}, timeout=300)

    async def edit_reply_markup(self, chat_id: int, message_id: int, reply_markup: dict | None = None) -> None:
        payload: dict = {"chat_id": chat_id, "message_id": message_id}
        if reply_markup:
            payload["reply_markup"] = reply_markup
        try:
            await self.call("editMessageReplyMarkup", payload)
        except TelegramError as exc:
            if "not modified" not in str(exc):
                log.warning("editMessageReplyMarkup: %s", exc)

    async def send_chat_action(self, chat_id: int, action: str = "typing") -> None:
        try:
            await self.call("sendChatAction", {"chat_id": chat_id, "action": action}, retries=0)
        except TelegramError:
            pass

    async def download(self, file_id: str, dest: Path) -> Path:
        info = await self.call("getFile", {"file_id": file_id})
        try:
            r = await self.client.get(f"{self._file_base}/{info['file_path']}", timeout=120)
            r.raise_for_status()
        except httpx.HTTPError as exc:
            raise TelegramError(f"getFile/download: {type(exc).__name__}") from None
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(r.content)
        return dest

    async def aclose(self) -> None:
        await self.client.aclose()
