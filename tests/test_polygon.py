import pytest
from pydantic import ValidationError

from orel.domain import Zone
from orel.schemas import RectangleInput


def test_perspective_zone_uses_polygon_not_bounding_rectangle():
    data = RectangleInput(
        name="Пол",
        left=0,
        top=0,
        right=1,
        bottom=1,
        points=[(0.4, 0.2), (0.6, 0.2), (0.9, 0.9), (0.1, 0.9)],
    )
    zone = Zone(**data.model_dump())
    assert zone.contains_person((0.45, 0.1, 0.55, 0.7))
    assert not zone.contains_person((0.1, 0.1, 0.2, 0.3))
    assert zone.contains_person((0.35, 0, 0.45, 0.2))


@pytest.mark.parametrize(
    "points",
    [
        [(0, 0), (1, 1), (1, 0), (0, 1)],
        [(0, 0), (1, 0), (1, 0), (0, 1)],
        [(0, 0), (1, 0), (2, 1), (0, 1)],
    ],
)
def test_invalid_polygon_is_rejected(points):
    with pytest.raises(ValidationError):
        RectangleInput(name="Пол", left=0, top=0, right=1, bottom=1, points=points)


@pytest.mark.parametrize(
    "box",
    [
        (0.1, 0.1, 0.45, 0.8),
        (0.45, 0, 0.55, 0.3),
        (0.5, 0.3, 0.8, 0.5),
        (0, 0, 1, 1),
        (0.45, 0.3, 0.55, 0.4),
    ],
)
def test_any_body_overlap_counts_even_when_feet_outside(box):
    zone = Zone("Danger", 0.4, 0.2, 0.6, 0.6)
    assert zone.intersects_person(box)


def test_diagonal_polygon_does_not_use_its_bounding_rectangle():
    zone = Zone(
        "Danger", 0.1, 0.2, 0.9, 0.9, points=[(0.4, 0.2), (0.6, 0.2), (0.9, 0.9), (0.1, 0.9)]
    )
    assert not zone.intersects_person((0.1, 0.1, 0.2, 0.3))
    assert zone.intersects_person((0.35, 0.1, 0.45, 0.25))
    assert not zone.intersects_person((0.91, 0.2, 0.99, 0.8))


def test_partial_overlap_confirms_and_disappearance_clears_alert():
    from orel.surveillance import SurveillanceRules

    rules = SurveillanceRules()
    zone = {"name": "Danger", "left": 0.4, "top": 0.2, "right": 0.6, "bottom": 0.6}
    for i in range(12):
        person = {"box": (0.1, 0.1, 0.45, 0.8), "helmet": "detected", "vest": "detected"}
        alerts = rules.assess([person], i * 0.25, False, False, zone)
    assert len(alerts) == 1 and alerts[0]["code"] == "danger_zone"
    track_id = person["track_id"]
    assert rules.assess([], 3, False, False, zone) == []
    returned = {"box": (0.1, 0.1, 0.45, 0.8), "helmet": "detected", "vest": "detected"}
    assert rules.assess([returned], 3.5, False, False, zone) == []
    assert returned["track_id"] == track_id
