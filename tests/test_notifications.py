import json

import pytest

from orel.notifications import Notifications, event_text
from orel.telegram_client import TelegramError

TOKEN = "123456:" + "TEST_ONLY_NOT_A_REAL_TOKEN_" * 2
EVENT = {
    "id": "event1",
    "video_id": "camera1",
    "video_name": "Камера у котла",
    "zone": "Опасный проход",
    "code": "ppe_required",
    "missing": ["helmet"],
    "created_at": "2026-10-22T12:00:00+00:00",
    "severity": "warning",
}


class Client:
    def __init__(self):
        self.calls = []
        self.error = None

    def call(self, method, values, photo=None):
        self.calls.append((method, values, photo.read_bytes() if photo else None))
        if self.error and method.startswith("send"):
            raise self.error
        if method == "getMe":
            return {"is_bot": True, "username": "orel_test_bot"}
        if method == "getUpdates":
            return [
                {"message": {"chat": {"id": 42, "type": "private", "first_name": "Тестовый чат"}}}
            ]
        return {"message_id": len(self.calls)}


@pytest.fixture
def notifications(prepared_store):
    client = Client()
    clock = [1000.0]
    service = Notifications(prepared_store, lambda token: client, lambda: clock[0])
    service.connect(TOKEN)
    service.configure(True, "42")
    return service, client, clock


def test_unconfigured_bot_never_sends_and_never_replays_old_events(prepared_store):
    client = Client()
    service = Notifications(prepared_store, lambda _: client)
    assert service.enqueue(EVENT, b"jpeg") is False
    service.tick()
    assert client.calls == []
    assert service.status()["configured"] is False


def test_confirmed_event_and_red_escalation_are_sent_exactly_once_with_correct_frames(
    notifications,
):
    service, client, _ = notifications
    assert service.enqueue(EVENT, b"confirmed frame")
    assert not service.enqueue(EVENT, b"duplicate")
    service.tick()
    red = {**EVENT, "severity": "critical", "escalated_at": "2026-10-22T12:00:08+00:00"}
    assert service.enqueue(red, b"current red frame")
    service.tick()
    service.tick()
    assert not service.enqueue(red, b"duplicate red")
    sent = [call for call in client.calls if call[0] == "sendPhoto"]
    assert len(sent) == 2
    assert sent[0][2] == b"confirmed frame" and sent[1][2] == b"current red frame"
    assert "Камера у котла" in sent[0][1]["caption"] and "каска" in sent[0][1]["caption"]
    assert "15:00:00" in sent[0][1]["caption"]
    assert "10 секунд" in sent[1][1]["caption"]
    assert all(job["status"] == "sent" for job in service.store.list("notifications"))
    assert list(service.photos.iterdir()) == []


def test_same_zone_reason_cooldown_is_separate_for_red_and_expires(notifications):
    service, _, clock = notifications
    assert service.enqueue(EVENT, b"a")
    service.tick()
    assert not service.enqueue({**EVENT, "id": "track-fragment"}, b"b")
    assert service.enqueue({**EVENT, "id": "red-event", "severity": "critical"}, b"c")
    service.tick()
    clock[0] += 31
    assert service.enqueue({**EVENT, "id": "later-event"}, b"d")


def test_pending_warning_is_superseded_by_red_instead_of_delivered_out_of_order(notifications):
    service, client, _ = notifications
    service.enqueue(EVENT, b"old")
    service.enqueue({**EVENT, "severity": "critical"}, b"new")
    service.tick()
    sent = [call for call in client.calls if call[0] == "sendPhoto"]
    assert len(sent) == 1 and sent[0][2] == b"new"
    assert {job["status"] for job in service.store.list("notifications")} == {"sent", "cancelled"}


def test_rate_limit_retries_after_server_delay_without_duplicate_success(notifications):
    service, client, clock = notifications
    client.error = TelegramError("Rate limited", retry_after=5)
    service.enqueue(EVENT, b"a")
    service.tick()
    assert service.status()["pending"] == 1
    service.tick()
    assert len([call for call in client.calls if call[0] == "sendPhoto"]) == 1
    client.error = None
    clock[0] += 5
    service.tick()
    service.tick()
    assert len([call for call in client.calls if call[0] == "sendPhoto"]) == 2
    assert service.store.list("notifications")[0]["status"] == "sent"


def test_uncertain_delivery_is_not_automatically_resent(notifications):
    service, client, clock = notifications
    client.error = TelegramError("Timeout", uncertain=True)
    service.enqueue(EVENT, b"a")
    service.tick()
    client.error = None
    clock[0] += 40
    service.tick()
    restarted = Notifications(service.store, lambda _: client, lambda: clock[0])
    restarted.recover_inflight()
    restarted.tick()
    assert service.store.list("notifications")[0]["status"] == "uncertain"
    assert len([call for call in client.calls if call[0] == "sendPhoto"]) == 1


def test_crash_during_sending_becomes_uncertain_and_never_changes_recipient(notifications):
    service, client, _ = notifications
    service.enqueue(EVENT, b"a")
    job = service.store.list("notifications")[0]
    job["status"] = "sending"
    service.store.put("notifications", job["id"], job)
    restarted = Notifications(service.store, lambda _: client)
    restarted.recover_inflight()
    restarted.tick()
    assert restarted.store.list("notifications")[0]["status"] == "uncertain"
    assert not [call for call in client.calls if call[0] == "sendPhoto"]


@pytest.mark.parametrize("change", ["disable", "chat", "bot"])
def test_pending_jobs_are_cancelled_when_disabled_or_reconfigured(notifications, change):
    service, client, _ = notifications
    service.enqueue(EVENT, b"a")
    if change == "bot":
        service.connect(TOKEN + "x")
    else:
        service.configure(change != "disable", "99" if change == "chat" else "42")
    service.tick()
    assert service.store.list("notifications")[0]["status"] == "cancelled"
    assert not [call for call in client.calls if call[0] == "sendPhoto"]
    assert list(service.photos.iterdir()) == []


def test_expired_jobs_are_not_sent_after_late_restart(notifications):
    service, client, clock = notifications
    service.enqueue(EVENT, b"a")
    clock[0] += 301
    service.tick()
    assert service.store.list("notifications")[0]["status"] == "expired"
    assert not [call for call in client.calls if call[0] == "sendPhoto"]


def test_secret_is_private_and_never_returned_by_status(notifications):
    service, _, _ = notifications
    assert service.secret.stat().st_mode & 0o777 == 0o600
    assert TOKEN not in json.dumps(service.status())
    assert TOKEN not in service.store.get("configurations", "telegram").values()
    assert service.chats()[0]["id"] == "42"
    service.test()
    assert service.status()["last_test_at"]
    service.configure(False, "99")
    assert service.status()["last_test_at"] is None


def test_danger_zone_message_is_a_review_signal_with_camera_zone_and_time():
    text = event_text({**EVENT, "code": "danger_zone"})
    assert "запрещённой зоне" in text and "Опасный проход" in text and "МСК" in text


def test_lost_secret_disables_delivery_instead_of_claiming_connection(notifications):
    service, client, _ = notifications
    service.enqueue(EVENT, b"a")
    service.secret.unlink()
    service.tick()
    status = service.status()
    assert status["enabled"] is False and status["configured"] is False
    assert status["queue_error"]
    assert not [call for call in client.calls if call[0] == "sendPhoto"]
