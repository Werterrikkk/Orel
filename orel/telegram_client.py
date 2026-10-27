"""Small Telegram Bot API transport. Never log URLs or raw network exceptions."""

import json
import uuid
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


class TelegramError(Exception):
    def __init__(self, message: str, *, retry_after: float | None = None, uncertain: bool = False):
        super().__init__(message)
        self.retry_after = retry_after
        self.uncertain = uncertain


class TelegramClient:
    def __init__(self, token: str):
        self.token = token

    def call(self, method: str, values: dict, photo: Path | None = None):
        if photo:
            boundary = uuid.uuid4().hex
            parts = []
            for key, value in values.items():
                parts.append(
                    (
                        f"--{boundary}\r\nContent-Disposition: form-data; "
                        f'name="{key}"\r\n\r\n{value}\r\n'
                    ).encode()
                )
            parts.extend(
                [
                    (
                        f'--{boundary}\r\nContent-Disposition: form-data; name="photo"; '
                        'filename="event.jpg"\r\nContent-Type: image/jpeg\r\n\r\n'
                    ).encode(),
                    photo.read_bytes(),
                    f"\r\n--{boundary}--\r\n".encode(),
                ]
            )
            body = b"".join(parts)
            content_type = f"multipart/form-data; boundary={boundary}"
        else:
            body = json.dumps(values).encode()
            content_type = "application/json"
        request = Request(
            f"https://api.telegram.org/bot{self.token}/{method}",
            data=body,
            headers={"Content-Type": content_type},
            method="POST",
        )
        try:
            try:
                with urlopen(request, timeout=8) as response:
                    data = json.loads(response.read(1024 * 1024))
            except HTTPError as error:
                try:
                    data = json.loads(error.read(1024 * 1024))
                except (ValueError, OSError):
                    data = {"ok": False, "error_code": error.code}
        except (URLError, OSError, TimeoutError, ValueError):
            raise TelegramError(
                "Нет подтверждения от Telegram. Проверьте соединение.",
                uncertain=method.startswith("send"),
            ) from None
        if not isinstance(data, dict):
            raise TelegramError(
                "Telegram вернул непонятный ответ.", uncertain=method.startswith("send")
            )
        if not data.get("ok"):
            code = data.get("error_code", 0)
            if code == 429:
                delay = min(
                    3600, max(1, float((data.get("parameters") or {}).get("retry_after", 30)))
                )
                raise TelegramError("Telegram ограничил частоту сообщений.", retry_after=delay)
            if isinstance(code, int) and code >= 500:
                raise TelegramError("Telegram временно недоступен.", retry_after=5)
            messages = {
                401: "Токен бота не принят. Проверьте его в BotFather.",
                403: "Бот не может написать в чат. Нажмите Start или проверьте права бота.",
                409: (
                    "Бот используется другой программой или webhook. "
                    "Для демо создайте отдельного бота."
                ),
                400: "Telegram отклонил запрос. Проверьте ID чата и доступ бота.",
                404: "Бот не найден. Проверьте токен в BotFather.",
            }
            raise TelegramError(
                messages.get(code, "Telegram отклонил запрос. Проверьте подключение.")
            )
        return data.get("result")
