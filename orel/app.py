"""Local HTTP API. Run one API instance; inference has its own single worker."""

import asyncio
import csv
import hashlib
import io
import json
import logging
import multiprocessing
import os
import signal
import threading
import time
import uuid
from concurrent.futures import ProcessPoolExecutor
from concurrent.futures.process import BrokenProcessPool
from contextlib import asynccontextmanager
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query, Request, UploadFile
from fastapi.exception_handlers import request_validation_exception_handler
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from orel.live import LiveMonitor
from orel.monitoring import Monitor
from orel.notifications import Notifications
from orel.schemas import (
    AnalysisInput,
    CameraSettings,
    Configuration,
    EventReview,
    PlaybackInput,
    TelegramConfiguration,
    TelegramTokenInput,
)
from orel.sources import LAPTOP, RUBETEK
from orel.storage import Store
from orel.telegram_client import TelegramClient, TelegramError
from orel.vision import ROOT, analyze_frame, analyze_video, inspect_video, model_catalog

logger = logging.getLogger(__name__)
MAX_UPLOAD = 200 * 1024 * 1024
MAX_CAMERA_FRAME = 1024 * 1024


def create_app(
    data_root: Path | None = None,
    enable_worker: bool = True,
    telegram_client_factory=TelegramClient,
) -> FastAPI:
    root = (data_root or Path(os.environ.get("OREL_DATA_DIR", ROOT / "data/runtime"))).resolve()
    store = Store(root)
    monitor = Monitor(store)
    live = LiveMonitor(store)
    notifications = Notifications(store, client_factory=telegram_client_factory)
    executor = None
    camera_future = None
    analysis_lock = threading.RLock()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        nonlocal executor
        for video in store.list("videos"):
            if video["status"] == "processing":
                video.update(
                    status="failed", error="Сервер был перезапущен. Запустите анализ повторно."
                )
                store.put("videos", video["id"], video)
        notifications.recover_inflight()
        stopping = asyncio.Event()

        async def deliver_notifications():
            while not stopping.is_set():
                try:
                    await asyncio.to_thread(notifications.tick)
                except Exception:
                    logger.error(
                        "Notification worker failed; delivery state remains in the journal"
                    )
                try:
                    await asyncio.wait_for(stopping.wait(), timeout=0.5)
                except TimeoutError:
                    pass

        delivery = asyncio.create_task(deliver_notifications())
        yield
        stopping.set()
        await delivery
        with analysis_lock:
            live.session = None
            pool = executor
        if pool:
            for video in store.list("videos"):
                if video["status"] == "processing":
                    (root / "results" / f"{video['id']}.cancel").touch()
            await asyncio.to_thread(pool.shutdown, wait=True, cancel_futures=True)

    app = FastAPI(title="orel", version="0.1.0", lifespan=lifespan)
    app.state.store = store
    app.state.monitor = monitor
    app.state.live = live
    app.state.notifications = notifications

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, exc: RequestValidationError):
        if request.url.path.startswith("/api/telegram"):
            return JSONResponse(
                status_code=422, content={"detail": "Проверьте поля настройки Telegram."}
            )
        return await request_validation_exception_handler(request, exc)

    def ensure_executor():
        nonlocal executor
        if executor is None:
            executor = ProcessPoolExecutor(
                max_workers=1,
                mp_context=multiprocessing.get_context("spawn"),
                initializer=signal.signal,
                initargs=(signal.SIGINT, signal.SIG_IGN),
            )
        return executor

    def require_video(video_id: str) -> dict:
        video = store.get("videos", video_id)
        if not video:
            raise HTTPException(404, "Видео не найдено.")
        return video

    def require_file(path: Path, message: str) -> Path:
        if not path.is_file():
            raise HTTPException(404, message)
        return path

    def register_video(stream, name: str, provenance: str | None = None) -> dict:
        suffix = Path(name).suffix.lower()
        if suffix not in {".mp4", ".mov", ".webm", ".m4v"}:
            raise HTTPException(
                415, "Выберите MP4, MOV или WebM. Для браузера рекомендуем MP4 H.264."
            )
        video_id = uuid.uuid4().hex
        path = root / "uploads" / f"{video_id}{suffix}"
        preview = root / "previews" / f"{video_id}.jpg"
        digest = hashlib.sha256()
        size = 0
        try:
            with path.open("wb") as output:
                while chunk := stream.read(1024 * 1024):
                    size += len(chunk)
                    if size > MAX_UPLOAD:
                        raise HTTPException(413, "Размер видео должен быть не более 200 МБ.")
                    digest.update(chunk)
                    output.write(chunk)
            metadata = inspect_video(path, preview)
        except Exception as exc:
            path.unlink(missing_ok=True)
            preview.unlink(missing_ok=True)
            if isinstance(exc, HTTPException):
                raise
            raise HTTPException(422, str(exc)) from exc
        video = {
            "id": video_id,
            "name": Path(name).name[:200],
            "file": path.name,
            "sha256": digest.hexdigest(),
            "bytes": size,
            **metadata,
            "created_at": datetime.now(UTC).isoformat(),
            "status": "uploaded",
            "progress": 0,
            "error": None,
            "provenance": provenance,
            "media_url": f"/api/videos/{video_id}/media",
            "preview_url": f"/api/videos/{video_id}/preview",
        }
        store.put("videos", video_id, video)
        store.put("configurations", video_id, {"video_id": video_id, "zone": None, "permit": None})
        return video

    @app.get("/api/health")
    def health():
        return {"status": "ok", "mode": "local", "version": "0.1.0"}

    @app.get("/api/bootstrap")
    def bootstrap():
        models = {
            key: {k: v for k, v in value.items() if k != "path"}
            for key, value in model_catalog().items()
        }
        return {
            "videos": store.list("videos"),
            "models": models,
            "demo_available": (ROOT / "data/demo.mp4").is_file()
            and (ROOT / "data/demo.json").is_file(),
            "server_time": datetime.now(UTC).isoformat(),
        }

    @app.post("/api/videos", status_code=201)
    def upload_video(file: UploadFile):
        try:
            return register_video(file.file, file.filename or "video.mp4")
        finally:
            file.file.close()

    @app.post("/api/demo", status_code=201)
    def open_demo():
        demo = ROOT / "data/demo.mp4"
        metadata = ROOT / "data/demo.json"
        if not demo.is_file() or not metadata.is_file():
            raise HTTPException(404, "Учебный ролик пока не подготовлен.")
        for video in store.list("videos"):
            if video.get("provenance") and video["name"] == "Учебный ролик · Construction-PPE.mp4":
                return video
        with demo.open("rb") as source:
            return register_video(
                source,
                "Учебный ролик · Construction-PPE.mp4",
                json.loads(metadata.read_text())["description"],
            )

    @app.get("/api/videos/{video_id}")
    def get_video(video_id: str):
        return require_video(video_id)

    @app.get("/api/videos/{video_id}/media")
    def video_media(video_id: str):
        video = require_video(video_id)
        return FileResponse(require_file(root / "uploads" / video["file"], "Файл видео не найден."))

    @app.get("/api/videos/{video_id}/preview")
    def video_preview(video_id: str):
        require_video(video_id)
        return FileResponse(
            require_file(root / "previews" / f"{video_id}.jpg", "Превью не найдено."),
            media_type="image/jpeg",
        )

    @app.post("/api/videos/{video_id}/analysis", status_code=202)
    def start_analysis(video_id: str, request: AnalysisInput):
        nonlocal executor
        with analysis_lock:
            if live.active() or (camera_future is not None and not camera_future.done()):
                raise HTTPException(409, "Остановите камеру перед анализом записи.")
            video = require_video(video_id)
            require_file(
                root / "uploads" / video["file"], "Файл видео не найден. Загрузите его заново."
            )
            if any(v["status"] == "processing" for v in store.list("videos")):
                raise HTTPException(409, "Дождитесь завершения текущего анализа.")
            spec = model_catalog()[request.model]
            if not spec["available"]:
                raise HTTPException(
                    409,
                    "Модель СИЗ ещё не подготовлена. Доступен отдельный режим обнаружения людей.",
                )
            if not enable_worker:
                raise HTTPException(503, "Рабочий процесс отключён.")
            ensure_executor()
            video.update(status="processing", progress=0, error=None)
            (root / "results" / f"{video_id}.cancel").unlink(missing_ok=True)
            store.put("videos", video_id, video)

            def completed(future):
                nonlocal executor
                error = None if future.cancelled() else future.exception()
                if future.cancelled() or error is not None:
                    with analysis_lock:
                        current = store.get("videos", video_id)
                        if current and current["status"] == "processing":
                            current.update(
                                status="failed",
                                error="Рабочий процесс прерван. Запустите анализ повторно.",
                            )
                            store.put("videos", video_id, current)
                        if isinstance(error, BrokenProcessPool) and executor is not None:
                            executor.shutdown(wait=False, cancel_futures=True)
                            executor = None

            try:
                future = executor.submit(analyze_video, str(root), video_id, spec)
                future.add_done_callback(completed)
            except RuntimeError as exc:
                video.update(status="failed", error="Не удалось запустить рабочий процесс.")
                store.put("videos", video_id, video)
                executor.shutdown(wait=False, cancel_futures=True)
                executor = None
                raise HTTPException(503, video["error"]) from exc
        return video

    @app.get("/api/camera/configuration")
    def camera_configuration():
        with analysis_lock:
            return live.settings()

    @app.get("/api/sources")
    def sources():
        return [asdict(source) for source in (LAPTOP, RUBETEK)]

    @app.get("/api/telegram")
    def telegram_status():
        return notifications.status()

    @app.post("/api/telegram/bot")
    def connect_telegram(request: TelegramTokenInput):
        try:
            return notifications.connect(request.token.get_secret_value())
        except (ValueError, TelegramError) as exc:
            raise HTTPException(400, str(exc)) from None

    @app.post("/api/telegram/chats")
    def telegram_chats():
        try:
            return notifications.chats()
        except (ValueError, TelegramError) as exc:
            raise HTTPException(400, str(exc)) from None

    @app.put("/api/telegram")
    def configure_telegram(request: TelegramConfiguration):
        try:
            return notifications.configure(request.enabled, request.chat_id)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from None

    @app.post("/api/telegram/test")
    def test_telegram():
        try:
            return notifications.test()
        except (ValueError, TelegramError) as exc:
            raise HTTPException(400, str(exc)) from None

    @app.put("/api/camera/configuration")
    def save_camera_configuration(request: CameraSettings):
        with analysis_lock:
            return live.save_settings(request)

    @app.post("/api/camera/sessions", status_code=201)
    def start_camera():
        with analysis_lock:
            if any(v["status"] == "processing" for v in store.list("videos")):
                raise HTTPException(409, "Дождитесь завершения анализа записи.")
            spec = model_catalog()["ppe"]
            if not spec["available"]:
                raise HTTPException(
                    409, "Обученная модель СИЗ не найдена. Подключите сохранённые веса."
                )
            if not enable_worker:
                raise HTTPException(503, "Рабочий процесс отключён.")
            try:
                return live.start(spec)
            except ValueError as exc:
                raise HTTPException(409, str(exc)) from exc

    @app.delete("/api/camera/sessions/{session_id}", status_code=204)
    def stop_camera(session_id: str):
        with analysis_lock:
            live.stop(session_id)

    @app.post("/api/camera/sessions/{session_id}/frames")
    async def camera_frame(session_id: str, file: UploadFile, sequence: int = Query(ge=0)):
        nonlocal camera_future, executor
        try:
            jpeg = await file.read(MAX_CAMERA_FRAME + 1)
        finally:
            await file.close()
        if len(jpeg) > MAX_CAMERA_FRAME:
            raise HTTPException(413, "Кадр камеры должен быть не более 1 МБ.")
        if not jpeg.startswith(b"\xff\xd8"):
            raise HTTPException(415, "Ожидается JPEG-кадр камеры.")
        received_at, received_utc = time.monotonic(), datetime.now(UTC)
        with analysis_lock:
            try:
                session = live.require(session_id)
            except ValueError as exc:
                raise HTTPException(409, str(exc)) from exc
            if camera_future is not None and not camera_future.done():
                raise HTTPException(429, "Предыдущий кадр ещё обрабатывается.")
            if sequence <= session.sequence:
                raise HTTPException(409, "Этот кадр уже обработан.")
            session.updated_at = received_at
            session.sequence = sequence
            try:
                future = ensure_executor().submit(analyze_frame, jpeg, session.model)
                camera_future = future
            except RuntimeError as exc:
                if executor is not None:
                    executor.shutdown(wait=False, cancel_futures=True)
                    executor = None
                raise HTTPException(503, "Не удалось запустить обработку камеры.") from exc
        try:
            # Disconnecting a browser cannot release admission while the worker still runs.
            data = await asyncio.wait_for(asyncio.shield(asyncio.wrap_future(future)), timeout=15)
            with analysis_lock:
                observation = live.observe(
                    session_id, sequence, jpeg, data, received_at, received_utc
                )
                for event in observation["new_events"]:
                    try:
                        notifications.enqueue(event, jpeg)
                    except Exception:
                        notifications.queue_error = (
                            "Событие сохранено, но поставить уведомление в очередь не удалось."
                        )
                        logger.error("Could not enqueue event notification")
                return observation
        except BrokenProcessPool as exc:
            with analysis_lock:
                if executor is not None:
                    executor.shutdown(wait=False, cancel_futures=True)
                    executor = None
                live.stop(session_id)
            raise HTTPException(
                503, "Обработка камеры прервана. Включите камеру повторно."
            ) from exc
        except TimeoutError as exc:
            raise HTTPException(
                503, "Модель не ответила вовремя. Остановите камеру и повторите запуск."
            ) from exc
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc
        except OSError as exc:
            logger.exception("Camera evidence failed")
            raise HTTPException(503, "Не удалось сохранить событие камеры.") from exc

    @app.get("/api/videos/{video_id}/detections")
    def detections(video_id: str):
        video = require_video(video_id)
        if video["status"] != "ready":
            raise HTTPException(409, "Анализ ещё не готов.")
        try:
            data, _ = monitor.results(video_id)
        except (OSError, ValueError, KeyError, TypeError) as exc:
            raise HTTPException(409, "Результаты недоступны. Запустите анализ повторно.") from exc
        return data

    @app.get("/api/videos/{video_id}/configuration")
    def configuration(video_id: str):
        require_video(video_id)
        return store.get("configurations", video_id) or {
            "video_id": video_id,
            "zone": None,
            "permit": None,
        }

    @app.put("/api/videos/{video_id}/configuration")
    def save_configuration(video_id: str, request: Configuration):
        require_video(video_id)
        if request.video_id != video_id:
            raise HTTPException(422, "Настройки относятся к другому видео.")
        data = request.model_dump(mode="json")
        with monitor.lock:
            store.put("configurations", video_id, data)
        return data

    @app.post("/api/playback")
    def playback(request: PlaybackInput):
        try:
            return monitor.observe(request)
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc
        except (OSError, KeyError, TypeError, IndexError) as exc:
            logger.exception("Playback evidence or result read failed")
            raise HTTPException(503, "Не удалось прочитать анализ или сохранить событие.") from exc

    @app.get("/api/events")
    def events():
        return store.list("events")

    @app.get("/api/events.csv")
    def export_events():
        buffer = io.StringIO()
        writer = csv.writer(buffer)
        writer.writerow(
            [
                "Время UTC",
                "Источник",
                "Позиция в записи, с",
                "Зона",
                "Наряд",
                "Причина",
                "Проверено",
                "Уровень",
                "Эскалация UTC",
            ]
        )
        for event in store.list("events"):
            values = [
                event["created_at"],
                event["video_name"],
                "" if event.get("source_type") == "camera" else event["position"],
                event["zone"],
                event["permit_number"] or "",
                event["reason"],
                event["reviewed"],
                event.get("severity", ""),
                event.get("escalated_at", ""),
            ]
            writer.writerow(
                [
                    "'" + value
                    if isinstance(value, str)
                    and value.lstrip(" \t\r\n").startswith(("=", "+", "-", "@"))
                    else value
                    for value in values
                ]
            )
        return Response(
            "\ufeff" + buffer.getvalue(),
            media_type="text/csv",
            headers={"Content-Disposition": 'attachment; filename="orel-events.csv"'},
        )

    @app.patch("/api/events/{event_id}")
    def review_event(event_id: str, request: EventReview):
        with analysis_lock:
            event = store.get("events", event_id)
            if not event:
                raise HTTPException(404, "Событие не найдено.")
            event["reviewed"] = request.reviewed
            event["reviewed_at"] = datetime.now(UTC).isoformat() if request.reviewed else None
            store.put("events", event_id, event)
            return event

    @app.get("/api/events/{event_id}/snapshot")
    def snapshot(event_id: str):
        if not store.get("events", event_id):
            raise HTTPException(404, "Событие не найдено.")
        return FileResponse(
            require_file(root / "snapshots" / f"{event_id}.jpg", "Кадр события не найден."),
            media_type="image/jpeg",
        )

    frontend = ROOT / "frontend/dist"
    if frontend.is_dir():
        app.mount("/", StaticFiles(directory=frontend, html=True), name="frontend")
    return app


app = create_app()
