from datetime import UTC, datetime

import cv2
import numpy as np
import pytest

from orel.live import LiveMonitor
from orel.schemas import CameraSettings

NOW = datetime(2026, 10, 21, 10, tzinfo=UTC)
PERSON = {"kind": "person", "box": [0.2, 0.1, 0.6, 0.9], "confidence": 0.9}
HELMET = {"kind": "helmet", "box": [0.3, 0.12, 0.45, 0.22], "confidence": 0.9}


def prediction(helmet=False):
    return {
        "objects": [PERSON, *([HELMET] if helmet else [])],
        "inference_height": 480,
        "model": {"ppe": True, "weights_sha256": "test"},
        "inference_ms": 10,
        "settings": {"confidence": 0.3, "input_size": 640},
    }


@pytest.fixture
def live(prepared_store):
    clock = [100.0]
    monitor = LiveMonitor(prepared_store, lambda: clock[0])
    session = monitor.start({"ppe": True, "weights_sha256": "test"})
    jpeg = cv2.imencode(".jpg", np.full((240, 320, 3), 116, np.uint8))[1].tobytes()
    return monitor, session["id"], clock, jpeg


def test_camera_checks_helmet_without_inventing_a_permit(live):
    monitor, session, clock, jpeg = live
    result = monitor.observe(session, 0, jpeg, prediction(helmet=True), clock[0], NOW)
    assert result["status"] == "active"
    assert result["people"][0]["helmet"] == "detected"
    assert result["reasons"] == []
    assert monitor.store.list("events") == []


def test_active_polygon_keeps_both_ppe_checks_and_events_independent(live):
    monitor, session, clock, jpeg = live
    monitor.save_settings(
        CameraSettings(
            require_helmet=True,
            require_vest=True,
            danger_zone={
                "name": "Проход",
                "left": 0.1,
                "top": 0.2,
                "right": 0.7,
                "bottom": 0.95,
                "points": [[0.1, 0.2], [0.7, 0.2], [0.7, 0.95], [0.1, 0.95]],
            },
        )
    )
    for sequence in range(45):
        clock[0] = 100 + sequence / 4
        result = monitor.observe(session, sequence, jpeg, prediction(), clock[0], NOW)
    alerts = {alert["code"]: alert for alert in result["alerts"]}
    assert set(alerts) == {"ppe_required", "danger_zone"}
    assert alerts["ppe_required"]["missing"] == ["helmet", "vest"]
    assert all(alert["severity"] == "critical" for alert in alerts.values())
    events = monitor.store.list("events")
    assert len(events) == 2
    assert {event["code"] for event in events} == set(alerts)
    # Putting equipment on clears only PPE; the person remains in the danger zone.
    vest = {"kind": "vest", "box": [0.25, 0.35, 0.55, 0.65], "confidence": 0.9}
    for sequence in range(45, 50):
        clock[0] = 100 + sequence / 4
        data = prediction(helmet=True)
        data["objects"].append(vest)
        result = monitor.observe(session, sequence, jpeg, data, clock[0], NOW)
    assert result["people"][0]["helmet"] == result["people"][0]["vest"] == "detected"
    assert [alert["code"] for alert in result["alerts"]] == ["danger_zone"]
    assert result["alerts"][0]["id"] == alerts["danger_zone"]["id"]


def test_helmet_removal_confirms_once_and_saves_the_actual_camera_frame(live):
    monitor, session, clock, jpeg = live
    for sequence in range(14):
        clock[0] = 100 + sequence / 4
        monitor.observe(session, sequence, jpeg, prediction(), clock[0], NOW)
    events = monitor.store.list("events")
    assert len(events) == 1
    assert events[0]["code"] == "ppe_required"
    assert events[0]["source_type"] == "camera"
    assert events[0]["configuration"]["check_permit"] is False
    assert events[0]["model"]["weights_sha256"] == "test"
    assert (monitor.store.root / "snapshots" / f"{events[0]['id']}.jpg").is_file()


def test_old_camera_frame_cannot_display_current_counts_or_create_an_event(live):
    monitor, session, clock, jpeg = live
    result = monitor.observe(session, 0, jpeg, prediction(), clock[0] - 3, NOW)
    assert result["status"] == "stale"
    assert result["detections"] == []
    assert result["new_events"] == []


def test_changing_requirements_restarts_confirmation(live):
    monitor, session, clock, jpeg = live
    monitor.observe(session, 0, jpeg, prediction(), clock[0], NOW)
    clock[0] += 0.75
    monitor.save_settings(CameraSettings(require_helmet=True, require_vest=True))
    monitor.observe(session, 1, jpeg, prediction(), clock[0], NOW)
    clock[0] += 0.5
    monitor.observe(session, 2, jpeg, prediction(), clock[0], NOW)
    assert monitor.store.list("events") == []


def test_stop_expiry_and_old_cleanup_do_not_end_a_new_camera_session(live):
    monitor, old, clock, jpeg = live
    with pytest.raises(ValueError, match="другом окне"):
        monitor.start({"ppe": True})
    clock[0] += 16
    new = monitor.start({"ppe": True})["id"]
    monitor.stop(old)
    assert monitor.require(new).id == new
    with pytest.raises(ValueError, match="завершён"):
        monitor.observe(old, 0, jpeg, prediction(), clock[0], NOW)
    assert monitor.store.list("events") == []


def test_red_warning_updates_the_same_event_without_losing_first_frame(live):
    monitor, session, clock, jpeg = live
    for sequence in range(45):
        clock[0] = 100 + sequence / 4
        result = monitor.observe(session, sequence, jpeg, prediction(), clock[0], NOW)
    events = monitor.store.list("events")
    assert len(events) == 1
    assert events[0]["severity"] == "critical"
    assert events[0]["duration_seconds"] == 10
    assert events[0]["escalated_at"] == NOW.isoformat()
    assert result["alerts"][0]["severity"] == "critical"


def test_temporarily_missing_person_is_not_counted_and_recovers_the_displayed_id(live):
    monitor, session, clock, jpeg = live
    first = monitor.observe(session, 0, jpeg, prediction(helmet=True), clock[0], NOW)
    original_id = first["detections"][0]["track_id"]
    for sequence in range(1, 15):
        clock[0] = 100 + sequence * 0.2
        data = {**prediction(), "objects": []}
        missing = monitor.observe(session, sequence, jpeg, data, clock[0], NOW)
        assert missing["people_total"] == 0
        assert missing["people"] == missing["detections"] == missing["alerts"] == []
        assert missing["new_events"] == []
    clock[0] = 103
    returned = monitor.observe(session, 15, jpeg, prediction(helmet=True), clock[0], NOW)
    assert returned["people_total"] == 1
    assert returned["detections"][0]["track_id"] == original_id


def test_obscured_camera_clears_people_emits_once_and_recovers(live):
    monitor, session, clock, jpeg = live
    monitor.observe(session, 0, jpeg, prediction(), clock[0], NOW)
    for i in range(1, 30):
        clock[0] = 100 + i * 0.25
        result = monitor.observe(
            session, i, jpeg, {**prediction(), "camera_health": "obscured"}, clock[0], NOW
        )
        assert not result["people"] and not result["detections"] and not result["alerts"]
    events = monitor.store.list("events")
    assert len(events) == 1
    assert events[0]["code"] == "camera_obscured"
    clock[0] += 0.25
    result = monitor.observe(session, 30, jpeg, prediction(), clock[0], NOW)
    assert result["camera_health"] == "ok"
    assert result["people_total"] == 1
    assert not result["alerts"]
