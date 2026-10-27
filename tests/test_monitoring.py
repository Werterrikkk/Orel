from orel.monitoring import Monitor
from orel.schemas import PlaybackInput
from orel.storage import Store


def request(position, playing=True):
    return PlaybackInput(
        session_id="session-test", video_id="testvideo", position=position, playing=playing
    )


def test_replay_produces_one_persisted_event_and_snapshot(prepared_store):
    monitor = Monitor(prepared_store)
    for position in (0, 0.25, 0.5, 0.75, 1, 1.25, 1.5):
        monitor.observe(request(position))
    events = Store(prepared_store.root).list("events")
    assert len(events) == 1
    assert events[0]["code"] == "permit_closed"
    assert events[0]["position"] == 1
    assert (prepared_store.root / "snapshots" / f"{events[0]['id']}.jpg").is_file()


def test_paused_video_does_not_generate_events(prepared_store):
    monitor = Monitor(prepared_store)
    for position in (0, 0.5, 1, 2):
        monitor.observe(request(position, playing=False))
    assert prepared_store.list("events") == []


def test_evidence_position_matches_detection_sample_not_later_browser_time(prepared_store):
    monitor = Monitor(prepared_store)
    for position in (0.25, 0.5, 0.75, 1, 1.25):
        monitor.observe(request(position))
    event = prepared_store.list("events")[0]
    assert event["position"] == 1.2
    assert event["playback_position"] == 1.25


def test_seeking_does_not_confirm_a_violation_across_the_jump(prepared_store):
    monitor = Monitor(prepared_store)
    monitor.observe(request(0))
    monitor.observe(request(2.5))
    assert prepared_store.list("events") == []


def test_closed_permit_after_open_creates_new_confirmation_window(prepared_store):
    monitor = Monitor(prepared_store)
    config = prepared_store.get("configurations", "testvideo")
    config["permit"]["closed"] = False
    prepared_store.put("configurations", "testvideo", config)
    for position in (0, 0.25, 0.5):
        assert monitor.observe(request(position))["reasons"] == []
    config["permit"]["closed"] = True
    prepared_store.put("configurations", "testvideo", config)
    for position in (0.75, 1, 1.25, 1.5):
        monitor.observe(request(position))
    assert prepared_store.list("events") == []
    monitor.observe(request(1.75))
    assert len(prepared_store.list("events")) == 1


def test_short_seek_starts_a_new_confirmation_window(prepared_store):
    monitor = Monitor(prepared_store)
    for position in (0, 0.25, 0.5):
        monitor.observe(request(position))
    seeking = request(0.8)
    seeking.seeking = True
    monitor.observe(seeking)
    monitor.observe(request(1.05))
    monitor.observe(request(1.3))
    assert prepared_store.list("events") == []


def test_transport_gap_does_not_confirm_using_old_observations(prepared_store):
    monitor = Monitor(prepared_store)
    for position in (0, 0.25, 0.5, 0.75):
        monitor.observe(request(position))
    monitor.sessions["session-test"].updated_at -= 3
    monitor.observe(request(1))
    assert prepared_store.list("events") == []
