from datetime import UTC, datetime, timedelta

import pytest

from orel.domain import Detection, IncidentGate, Permit, Zone, associate_ppe, evaluate

NOW = datetime(2026, 10, 21, 10, tzinfo=UTC)
ZONE = Zone("Цех", 0.1, 0.4, 0.9, 0.95)
PERSON = Detection("person", (0.2, 0.1, 0.6, 0.9), 0.9)


def valid_permit(**changes):
    return Permit(
        **{
            "number": "ND-1",
            "starts_at": NOW - timedelta(hours=1),
            "ends_at": NOW + timedelta(hours=1),
            **changes,
        }
    )


def test_zone_checks_feet_not_body_center():
    assert ZONE.contains_person((0.2, 0, 0.6, 0.9))
    assert not ZONE.contains_person((0.2, 0.6, 0.6, 0.99))
    assert not ZONE.contains_person((0.92, 0.4, 1, 0.9))


@pytest.mark.parametrize(
    "now,closed,expected",
    [
        (NOW, False, None),
        (NOW - timedelta(hours=2), False, "permit_pending"),
        (NOW + timedelta(hours=1), False, "permit_expired"),
        (NOW, True, "permit_closed"),
    ],
)
def test_permit_boundaries(now, closed, expected):
    assert valid_permit(closed=closed).restriction(now) == expected


def test_permit_rejects_naive_time_and_reversed_interval():
    with pytest.raises(ValueError):
        valid_permit(starts_at=NOW.replace(tzinfo=None))
    with pytest.raises(ValueError):
        valid_permit(ends_at=NOW - timedelta(hours=2))


def test_one_item_is_not_assigned_to_two_overlapping_people():
    second = Detection("person", (0.25, 0.12, 0.65, 0.92), 0.9)
    helmet = Detection("helmet", (0.35, 0.12, 0.45, 0.2), 0.8)
    assignments = associate_ppe([PERSON, second, helmet])
    assert sum(p["helmet"] for p in assignments) == 1


def test_vest_near_feet_is_not_evidence_of_wearing():
    vest = Detection("vest", (0.3, 0.82, 0.5, 0.89), 0.9)
    assert not associate_ppe([PERSON, vest])[0]["vest"]


def test_permit_and_ppe_are_independent():
    result = evaluate([PERSON], ZONE, valid_permit(closed=True), NOW, True, 640)
    assert result["status"] == "restricted"
    assert set(result["reasons"]) == {"permit_closed", "helmet_not_detected", "vest_not_detected"}


def test_small_person_is_uncertain_not_missing_ppe():
    small = Detection("person", (0.4, 0.8, 0.45, 0.9), 0.8)
    result = evaluate([small], ZONE, valid_permit(), NOW, True, 640)
    assert result["status"] == "uncertain"
    assert result["reasons"] == []


def test_person_only_model_cannot_claim_missing_ppe():
    result = evaluate([PERSON], ZONE, valid_permit(), NOW, False, 640)
    assert result["people"][0]["helmet"] == "unavailable"
    assert result["reasons"] == []


def test_no_people_and_no_permit_does_not_create_a_violation():
    result = evaluate([], ZONE, None, NOW, True, 640)
    assert result["status"] == "no_people"
    assert result["reasons"] == []


def test_present_gear_is_detected_but_not_certified():
    detections = [
        PERSON,
        Detection("helmet", (0.3, 0.12, 0.5, 0.23), 0.8),
        Detection("vest", (0.3, 0.35, 0.5, 0.65), 0.8),
    ]
    result = evaluate(detections, ZONE, valid_permit(), NOW, True, 640)
    assert result["status"] == "active"
    assert result["people"][0]["helmet"] == "detected"


def test_gate_confirms_and_deduplicates_then_rearms_after_gap():
    gate = IncidentGate()
    assert not gate.observe(0, True)
    assert not gate.observe(0.4, True)
    assert not gate.observe(0.6, False)
    assert not gate.observe(0.8, True)
    assert gate.observe(1.2, True)
    assert not gate.observe(1.4, True)
    assert not gate.observe(2.4, True)
    assert not gate.observe(2.9, True)
    assert gate.observe(3.4, True)
