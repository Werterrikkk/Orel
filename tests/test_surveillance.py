import pytest

from orel.surveillance import SurveillanceRules

DANGER = {"name": "Проход", "left": 0.1, "top": 0.5, "right": 0.8, "bottom": 1.0}


def person(helmet="not_detected", vest="detected", box=(0.2, 0.1, 0.5, 0.9)):
    return {"box": box, "helmet": helmet, "vest": vest}


def assess(rules, t, people=None, danger=None, helmet=True, vest=True):
    return rules.assess([person()] if people is None else people, t, helmet, vest, danger)


def confirm(rules, start=100, people=None, danger=None):
    result = []
    for frame in range(13):
        result = assess(rules, start + frame * 0.2, people, danger)
    return result


def test_single_miss_does_not_warn_and_continuous_signal_confirms_then_escalates():
    rules = SurveillanceRules()
    assert assess(rules, 100) == []
    assert rules.pending_count == 1
    for frame in range(1, 51):
        alerts = assess(rules, 100 + frame * 0.2)
        if frame < 10:
            assert alerts == []
        else:
            assert alerts[0]["severity"] == ("critical" if frame == 50 else "warning")
    assert rules.pending_count == 0


def test_many_fast_checks_cannot_replace_time_confirmation():
    rules = SurveillanceRules()
    for frame in range(20):
        assert assess(rules, 100 + frame * 0.02) == []


def test_minimum_number_of_independent_observations_is_required():
    rules = SurveillanceRules()
    for time in [100, 100.6, 101.2, 101.8, 102.4]:
        assert assess(rules, time) == []
    assert assess(rules, 102.8)[0]["severity"] == "warning"


def test_isolated_ppe_misses_among_positive_detections_do_not_warn():
    rules = SurveillanceRules()
    for frame in range(100):
        state = "not_detected" if frame % 5 == 0 else "detected"
        assert assess(rules, 100 + frame * 0.2, [person(helmet=state)]) == []


def test_majority_of_mixed_detections_must_indicate_the_same_problem():
    rules = SurveillanceRules()
    for frame in range(40):
        state = "detected" if frame % 2 else "not_detected"
        assert assess(rules, 100 + frame * 0.2, [person(helmet=state)]) == []


def test_one_positive_frame_does_not_clear_but_stable_correction_clears():
    rules = SurveillanceRules()
    original = confirm(rules)[0]
    assert assess(rules, 102.6, [person(helmet="detected")])[0]["id"] == original["id"]
    assert assess(rules, 102.9, [person(helmet="detected")])
    assert assess(rules, 103.2, [person(helmet="detected")]) == []
    assert assess(rules, 103.4) == []


def test_red_level_is_not_started_on_a_current_positive_ppe_detection():
    rules = SurveillanceRules()
    for frame in range(50):
        assess(rules, 100 + frame * 0.2)
    assert assess(rules, 110, [person(helmet="detected")])[0]["severity"] == "warning"
    # Critical delivery requires fresh evidence after the intermittent positive.
    for time in [110.2, 110.4, 110.6]:
        alerts = assess(rules, time)
    assert alerts[0]["severity"] == "critical"


def test_each_piece_of_equipment_requires_its_own_evidence():
    rules = SurveillanceRules()
    confirm(rules)
    alerts = assess(rules, 102.6, [person(vest="not_detected")])
    assert alerts[0]["missing"] == ["helmet"]
    for frame in range(1, 13):
        alerts = assess(rules, 102.6 + frame * 0.2, [person(vest="not_detected")])
    assert alerts[0]["missing"] == ["helmet", "vest"]


def test_danger_and_ppe_timers_are_independent():
    rules = SurveillanceRules()
    for frame in range(56):
        alerts = assess(rules, 100 + frame * 0.2, danger=DANGER if frame >= 40 else None)
    assert {a["code"]: a["duration_seconds"] for a in alerts} == {
        "ppe_required": 11,
        "danger_zone": 3,
    }


def test_danger_requires_stable_presence_and_uses_feet_anchor():
    rules = SurveillanceRules()
    assert assess(rules, 100, [person(helmet="detected")], DANGER) == []
    assert [a["code"] for a in confirm(rules, 100.2, [person(helmet="detected")], DANGER)] == [
        "danger_zone"
    ]
    for time in [102.8, 103.1, 103.4]:
        alerts = assess(
            rules, time, [person(helmet="detected", box=(0.2, 0.05, 0.5, 0.45))], DANGER
        )
    assert alerts == []


@pytest.mark.parametrize("state", ["uncertain", "unavailable", "detected"])
def test_unknown_or_present_ppe_does_not_start_an_absence_signal(state):
    assert confirm(SurveillanceRules(), people=[person(helmet=state)]) == []


def test_unknown_ppe_clears_confirmation_without_certifying_safety():
    rules = SurveillanceRules()
    confirm(rules)
    assert assess(rules, 102.6, [person(helmet="uncertain")]) == []
    assert assess(rules, 102.8) == []


def test_disabled_requirements_and_source_gaps_do_not_keep_old_confirmation():
    rules = SurveillanceRules()
    confirm(rules)
    assert assess(rules, 105.5) == []
    assert assess(rules, 105.7, helmet=False, vest=False) == []


def test_timers_are_not_transferred_to_a_different_person_box():
    rules = SurveillanceRules()
    previous = confirm(rules)[0]
    assert assess(rules, 102.6, [person(box=(0.65, 0.1, 0.95, 0.9))]) == []
    next_alert = confirm(rules, 102.8, [person(box=(0.65, 0.1, 0.95, 0.9))])[0]
    assert next_alert["track_id"] != previous["track_id"]


def test_ambiguous_overlaps_and_missing_people_reset_confirmation():
    rules = SurveillanceRules()
    confirm(rules)
    people = [person(), person(box=(0.21, 0.1, 0.51, 0.9))]
    for frame in range(20):
        assert assess(rules, 102.6 + frame * 0.2, people) == []
    assert assess(rules, 107, []) == []
    assert rules.episodes == {} and rules.pending_count == 0


@pytest.mark.parametrize("absence", [0.4, 2.5, 3.0])
def test_person_recovers_the_same_id_within_three_seconds(absence):
    rules = SurveillanceRules()
    original = person()
    assess(rules, 100, [original])
    for step in range(1, int(absence / 0.2)):
        assert assess(rules, 100 + step * 0.2, []) == []
    returned = person(box=(0.21, 0.1, 0.51, 0.9))
    assert assess(rules, 100 + absence, [returned]) == []
    assert returned["track_id"] == original["track_id"]


def test_missing_tracks_expire_and_do_not_recover_after_three_seconds():
    rules = SurveillanceRules()
    original = person()
    assess(rules, 100, [original])
    for step in range(1, 17):
        assess(rules, 100 + step * 0.2, [])
    assert rules.tracks == {}
    returned = person()
    assess(rules, 103.4, [returned])
    assert returned["track_id"] != original["track_id"]


def test_recovered_id_restarts_warning_evidence_without_counting_the_absence():
    rules = SurveillanceRules()
    for frame in range(45):
        alerts = assess(rules, 100 + frame * 0.2)
    old = alerts[0]
    for frame in range(1, 13):
        assert assess(rules, 108.8 + frame * 0.2, []) == []
    returned = person()
    assert assess(rules, 111.4, [returned]) == []
    assert returned["track_id"] == old["track_id"]
    new = confirm(rules, 111.6)[0]
    assert new["track_id"] == old["track_id"]
    assert new["id"] != old["id"]
    assert new["severity"] == "warning"
    assert new["duration_seconds"] < 3


def test_ambiguous_reappearance_retires_old_ids():
    rules = SurveillanceRules()
    original = person()
    assess(rules, 100, [original])
    assess(rules, 100.2, [])
    overlapping = [person(), person(box=(0.21, 0.1, 0.51, 0.9))]
    assess(rules, 100.4, overlapping)
    assert original["track_id"] not in {p["track_id"] for p in overlapping}
    assert original["track_id"] not in rules.tracks


def test_missing_person_does_not_steal_another_visible_persons_id():
    rules = SurveillanceRules()
    left, right = person(), person(box=(0.65, 0.1, 0.95, 0.9))
    assess(rules, 100, [left, right])
    for frame in range(1, 13):
        visible = person(box=right["box"])
        assess(rules, 100 + frame * 0.2, [visible])
        assert visible["track_id"] == right["track_id"]
    returned = [person(box=right["box"]), person()]
    assess(rules, 102.6, returned)
    assert [p["track_id"] for p in returned] == [right["track_id"], left["track_id"]]


def test_source_gap_resets_identity_hints_even_within_recovery_window():
    rules = SurveillanceRules()
    original, returned = person(), person()
    assess(rules, 100, [original])
    assert assess(rules, 102, [returned]) == []
    assert returned["track_id"] != original["track_id"]
