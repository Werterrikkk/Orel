"""Local Telegram configuration and durable, bounded event delivery.

Inference only enqueues jobs. Network I/O runs in the application's background
worker. Ambiguous delivery is never automatically repeated.
"""

import hashlib
import json
import os
import re
import threading
import time
import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from orel.storage import Store
from orel.telegram_client import TelegramClient, TelegramError

COOLDOWN_SECONDS = 30
TTL_SECONDS = 300


def event_text(event: dict) -> str:
    critical = event["severity"] == "critical"
    level = "🔴 Красный сигнал" if critical else "🟡 Подтверждённый сигнал"
    if event["code"] == "camera_obscured":
        reason = "Камера закрыта или изображение неразличимо. Проверьте объектив и освещение."
    elif event["code"] == "danger_zone":
        reason = "Человек находится в запрещённой зоне. Покиньте опасную зону."
    else:
        missing = ", ".join(
            {"helmet": "каска", "vest": "жилет"}[kind]
            for kind in event.get("missing", [])
            if kind in {"helmet", "vest"}
        )
        reason = f"Не обнаружены СИЗ: {missing or 'обязательная экипировка'}. Требуется проверка."
    stamp = event.get("escalated_at") if critical else event["created_at"]
    moment = datetime.fromisoformat(stamp or event["created_at"]).astimezone(
        ZoneInfo("Europe/Moscow")
    )
    lines = [
        f"{level} · orel",
        reason,
        f"Камера: {event['video_name'][:100]}",
        f"Зона: {event['zone'][:100]}",
        f"Время: {moment:%d.%m.%Y %H:%M:%S} МСК",
    ]
    if critical and event["code"] != "camera_obscured":
        lines.append("Сигнал сохраняется не менее 10 секунд.")
    lines.extend(["Снимок подтверждающего кадра.", f"Событие: {event['id'][:12]}"])
    return "\n".join(lines)[:1000]


class Notifications:
    def __init__(
        self,
        store: Store,
        client_factory: Callable = TelegramClient,
        clock: Callable[[], float] = time.time,
    ):
        self.store, self.client_factory, self.clock = store, client_factory, clock
        self.lock = threading.RLock()
        self.secret = store.root / "telegram-secret.json"
        self.photos = store.root / "notification-photos"
        self.photos.mkdir(exist_ok=True)
        self.queue_error: str | None = None

    def recover_inflight(self):
        # A process may have stopped after Telegram accepted a sending job.
        for job in self.store.list("notifications"):
            if job["status"] == "sending":
                job.update(
                    status="uncertain", error="Отправка прервалась; результат не подтверждён."
                )
                self.store.put("notifications", job["id"], job)
                self._remove_photo(job)

    def _configuration(self) -> dict:
        return self.store.get("configurations", "telegram") or {
            "enabled": False,
            "chat_id": "",
            "bot_username": "",
            "bot_fingerprint": "",
        }

    def _token(self) -> str:
        try:
            return json.loads(self.secret.read_text())["token"]
        except (OSError, ValueError, KeyError, TypeError):
            return ""

    def _client(self):
        token = self._token()
        if not token:
            raise ValueError("Сначала подключите бота.")
        return self.client_factory(token)

    def status(self) -> dict:
        with self.lock:
            config = self._configuration()
            configured = bool(self._token())
            jobs = self.store.list("notifications")
            recent = [
                {
                    key: job.get(key)
                    for key in (
                        "id",
                        "status",
                        "error",
                        "severity",
                        "created_at",
                        "sent_at",
                        "zone",
                    )
                }
                for job in jobs[:5]
            ]
            return {
                "configured": configured,
                "enabled": config["enabled"] and configured,
                "bot_username": config["bot_username"],
                "chat_id": config["chat_id"],
                "pending": sum(job["status"] in {"pending", "sending"} for job in jobs),
                "deliveries": recent,
                "last_test_at": config.get("last_test_at"),
                "cooldown_seconds": COOLDOWN_SECONDS,
                "queue_error": self.queue_error
                or (
                    "Токен недоступен. Подключите бота повторно."
                    if config["enabled"] and not configured
                    else None
                ),
            }

    def connect(self, token: str) -> dict:
        if not re.fullmatch(r"[0-9]{5,16}:[A-Za-z0-9_-]{20,200}", token):
            raise ValueError("Проверьте формат токена из BotFather.")
        bot = self.client_factory(token).call("getMe", {})
        if (
            not isinstance(bot, dict)
            or not bot.get("is_bot")
            or not re.fullmatch(r"[A-Za-z0-9_]{5,64}", str(bot.get("username", "")))
        ):
            raise ValueError("Telegram не подтвердил учётную запись бота.")
        temporary = self.secret.with_name(f".telegram-{uuid.uuid4().hex}.tmp")
        with self.lock:
            try:
                descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                with os.fdopen(descriptor, "w") as output:
                    json.dump({"token": token}, output)
                os.replace(temporary, self.secret)
            finally:
                temporary.unlink(missing_ok=True)
            self._cancel_pending()
            self.store.put(
                "configurations",
                "telegram",
                {
                    "enabled": False,
                    "chat_id": "",
                    "bot_username": bot["username"],
                    "bot_fingerprint": hashlib.sha256(token.encode()).hexdigest(),
                },
            )
        return self.status()

    def chats(self) -> list[dict]:
        with self.lock:
            client = self._client()
        updates = client.call(
            "getUpdates",
            {"timeout": 0, "limit": 100, "allowed_updates": ["message", "my_chat_member"]},
        )
        chats = {}
        for update in updates if isinstance(updates, list) else []:
            message = update.get("message") or update.get("my_chat_member") or {}
            chat = message.get("chat") or {}
            if chat.get("id") and chat.get("type") in {"private", "group", "supergroup", "channel"}:
                chats[str(chat["id"])] = {
                    "id": str(chat["id"]),
                    "type": chat["type"],
                    "title": str(
                        chat.get("title")
                        or chat.get("first_name")
                        or chat.get("username")
                        or chat["id"]
                    )[:100],
                }
        return list(chats.values())[-20:]

    def configure(self, enabled: bool, chat_id: str) -> dict:
        if chat_id and not re.fullmatch(r"-?[0-9]{1,20}|@[A-Za-z0-9_]{5,64}", chat_id):
            raise ValueError("Укажите числовой ID чата или @имя канала.")
        with self.lock:
            config = self._configuration()
            if enabled and (not self._token() or not chat_id):
                raise ValueError("Сначала подключите бота и выберите чат.")
            if not enabled or chat_id != config["chat_id"]:
                self._cancel_pending()
            if chat_id != config["chat_id"]:
                config["last_test_at"] = None
            config.update(enabled=enabled, chat_id=chat_id)
            self.store.put("configurations", "telegram", config)
        return self.status()

    def test(self) -> dict:
        with self.lock:
            config, client = self._configuration(), self._client()
        if not config["chat_id"]:
            raise ValueError("Сначала сохраните чат для уведомлений.")
        result = client.call(
            "sendMessage",
            {
                "chat_id": config["chat_id"],
                "text": (
                    "orel · Тестовое сообщение\nУведомления подключены. "
                    "Это проверка связи, не событие безопасности."
                ),
            },
        )
        if not isinstance(result, dict) or not isinstance(result.get("message_id"), int):
            raise TelegramError("Telegram не подтвердил тестовую доставку.", uncertain=True)
        with self.lock:
            # A concurrent bot/chat change must not acquire the previous test's result.
            current = self._configuration()
            if self._target(current) == self._target(config):
                current["last_test_at"] = datetime.now(UTC).isoformat()
                self.store.put("configurations", "telegram", current)
        return self.status()

    @staticmethod
    def _target(config: dict) -> str:
        return f"{config['bot_fingerprint']}:{config['chat_id']}"

    def enqueue(self, event: dict, jpeg: bytes) -> bool:
        with self.lock:
            self.queue_error = None
            config = self._configuration()
            if not config["enabled"] or not self._token():
                return False
            severity = event.get("severity")
            if severity not in {"warning", "critical"}:
                return False
            target = self._target(config)
            key = hashlib.sha256(f"{target}:{event['id']}:{severity}".encode()).hexdigest()
            if self.store.get("notifications", key):
                return False
            now = self.clock()
            group = (event["video_id"], event["zone"], event["code"], severity)
            for job in self.store.list("notifications"):
                if (
                    job["target"] == target
                    and tuple(job["group"]) == group
                    and now - job["queued_at"] < COOLDOWN_SECONDS
                    and job["status"] not in {"cancelled", "expired"}
                ):
                    return False
            if severity == "critical":
                warning_key = hashlib.sha256(f"{target}:{event['id']}:warning".encode()).hexdigest()
                warning = self.store.get("notifications", warning_key)
                if warning and warning["status"] == "pending":
                    warning.update(status="cancelled", error="Заменено красным сигналом.")
                    self.store.put("notifications", warning_key, warning)
                    self._remove_photo(warning)
            photo = self.photos / f"{key}.jpg"
            photo.write_bytes(jpeg)
            try:
                self.store.put(
                    "notifications",
                    key,
                    {
                        "id": key,
                        "target": target,
                        "chat_id": config["chat_id"],
                        "event_id": event["id"],
                        "severity": severity,
                        "zone": event["zone"],
                        "group": group,
                        "text": event_text(event),
                        "status": "pending",
                        "attempts": 0,
                        "queued_at": now,
                        "next_attempt": now,
                        "created_at": datetime.now(UTC).isoformat(),
                        "error": None,
                    },
                )
            except Exception:
                photo.unlink(missing_ok=True)
                raise
            return True

    def _remove_photo(self, job: dict):
        (self.photos / f"{job['id']}.jpg").unlink(missing_ok=True)

    def _cancel_pending(self):
        for job in self.store.list("notifications"):
            if job["status"] == "pending":
                job.update(status="cancelled", error=None)
                self.store.put("notifications", job["id"], job)
                self._remove_photo(job)

    def tick(self):
        with self.lock:
            config = self._configuration()
            if not config["enabled"] or not self._token():
                return
            now = self.clock()
            pending = [
                job
                for job in reversed(self.store.list("notifications"))
                if job["status"] == "pending"
            ]
            selected = None
            for job in pending:
                if now - job["queued_at"] >= TTL_SECONDS or job["target"] != self._target(config):
                    job.update(
                        status="expired" if now - job["queued_at"] >= TTL_SECONDS else "cancelled"
                    )
                    self.store.put("notifications", job["id"], job)
                    self._remove_photo(job)
                elif selected is None and job["next_attempt"] <= now:
                    selected = job
            if selected is None:
                return
            job = selected
            client = self._client()
            job.update(status="sending", attempts=job["attempts"] + 1)
            self.store.put("notifications", job["id"], job)
        try:
            result = client.call(
                "sendPhoto",
                {"chat_id": job["chat_id"], "caption": job["text"]},
                photo=self.photos / f"{job['id']}.jpg",
            )
            if not isinstance(result, dict) or not isinstance(result.get("message_id"), int):
                raise TelegramError("Telegram не подтвердил доставку.", uncertain=True)
        except TelegramError as error:
            if error.uncertain:
                job.update(status="uncertain", error=str(error))
            elif error.retry_after is not None and job["attempts"] < 3:
                job.update(
                    status="pending",
                    error=str(error),
                    next_attempt=self.clock() + error.retry_after,
                )
            else:
                job.update(status="failed", error=str(error))
        except OSError:
            job.update(status="failed", error="Не удалось прочитать кадр уведомления.")
        except Exception:
            job.update(status="uncertain", error="Результат отправки не подтверждён.")
        else:
            job.update(
                status="sent",
                error=None,
                message_id=result["message_id"],
                sent_at=datetime.now(UTC).isoformat(),
            )
        with self.lock:
            self.store.put("notifications", job["id"], job)
            if job["status"] != "pending":
                self._remove_photo(job)
