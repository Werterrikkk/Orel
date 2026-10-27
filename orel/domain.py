"""Pure safety-review rules. No knowledge of HTTP, files, or ML runtimes."""

from dataclasses import dataclass
from datetime import datetime
from typing import Literal

Box = tuple[float, float, float, float]
PPEState = Literal["detected", "not_detected", "uncertain", "unavailable"]


@dataclass(frozen=True)
class Detection:
    kind: str
    box: Box  # Normalized to [0, 1] in the source frame.
    confidence: float


@dataclass(frozen=True)
class Zone:
    name: str
    left: float
    top: float
    right: float
    bottom: float
    require_helmet: bool = True
    require_vest: bool = True
    points: list[tuple[float, float]] | None = None

    def __post_init__(self):
        if not self.name.strip():
            raise ValueError("Укажите название зоны.")
        if not (0 <= self.left < self.right <= 1 and 0 <= self.top < self.bottom <= 1):
            raise ValueError("У зоны должны быть ненулевые ширина и высота.")

    def intersects_person(self, box: Box) -> bool:
        """Convex polygon/box SAT; contact with any edge counts as entry."""
        x1, y1, x2, y2 = box
        person = [(x1, y1), (x2, y1), (x2, y2), (x1, y2)]
        polygon = self.points or [
            (self.left, self.top),
            (self.right, self.top),
            (self.right, self.bottom),
            (self.left, self.bottom),
        ]
        for vertices in (person, polygon):
            for a, b in zip(vertices, vertices[1:] + vertices[:1], strict=True):
                nx, ny = -(b[1] - a[1]), b[0] - a[0]
                first = [x * nx + y * ny for x, y in person]
                second = [x * nx + y * ny for x, y in polygon]
                if max(first) < min(second) - 1e-9 or max(second) < min(first) - 1e-9:
                    return False
        return True

    def contains_person(self, box: Box) -> bool:
        x1, _, x2, y2 = box
        if self.points:
            x, y = (x1 + x2) / 2, y2
            signs = []
            for a, b in zip(self.points, self.points[1:] + self.points[:1], strict=True):
                signs.append((b[0] - a[0]) * (y - a[1]) - (b[1] - a[1]) * (x - a[0]))
            return all(v >= -1e-9 for v in signs) or all(v <= 1e-9 for v in signs)
        return self.left <= (x1 + x2) / 2 <= self.right and self.top <= y2 <= self.bottom


@dataclass(frozen=True)
class Permit:
    number: str
    starts_at: datetime
    ends_at: datetime
    closed: bool = False

    def __post_init__(self):
        if not self.number.strip():
            raise ValueError("Укажите номер наряда.")
        if self.starts_at.tzinfo is None or self.ends_at.tzinfo is None:
            raise ValueError("Время наряда должно включать часовой пояс.")
        if self.ends_at <= self.starts_at:
            raise ValueError("Окончание работ должно быть позже начала.")

    def restriction(self, now: datetime) -> str | None:
        if self.closed:
            return "permit_closed"
        if now < self.starts_at:
            return "permit_pending"
        if now >= self.ends_at:
            return "permit_expired"
        return None


REASONS = {
    "camera_obscured": "Камера закрыта или изображение неразличимо",
    "ppe_required": "Наденьте СИЗ",
    "danger_zone": "Покиньте опасную зону",
    "no_permit": "Наряд не задан",
    "permit_closed": "Наряд закрыт",
    "permit_pending": "Время работ ещё не наступило",
    "permit_expired": "Время работ истекло",
    "helmet_not_detected": "Каска не обнаружена — требуется проверка",
    "vest_not_detected": "Жилет не обнаружен — требуется проверка",
}


def associate_ppe(detections: list[Detection]) -> list[dict[str, bool]]:
    """Assign each item to at most one person, using plausible head/torso regions.

    This is a geometric heuristic, not evidence of correct wearing or identity.
    """
    people = [d for d in detections if d.kind == "person"]
    equipment = [{"helmet": False, "vest": False} for _ in people]
    for item in detections:
        if item.kind not in {"helmet", "vest"}:
            continue
        cx = (item.box[0] + item.box[2]) / 2
        cy = (item.box[1] + item.box[3]) / 2
        candidates = []
        for index, person in enumerate(people):
            x1, y1, x2, y2 = person.box
            height, width = y2 - y1, x2 - x1
            if height <= 0 or width <= 0 or not x1 <= cx <= x2:
                continue
            relative_y = (cy - y1) / height
            low, high, anchor = (-0.12, 0.4, 0.1) if item.kind == "helmet" else (0.15, 0.8, 0.45)
            if low <= relative_y <= high:
                distance = ((cx - (x1 + x2) / 2) / width) ** 2 + (relative_y - anchor) ** 2
                candidates.append((distance, index))
        if candidates:
            _, index = min(candidates)
            equipment[index][item.kind] = True
    return equipment


def evaluate(
    detections: list[Detection],
    zone: Zone,
    permit: Permit | None,
    now: datetime,
    ppe_available: bool,
    inference_height: int,
    *,
    check_permit: bool = True,
) -> dict:
    people = [d for d in detections if d.kind == "person"]
    gear = associate_ppe(detections)
    assessed = []
    for person, items in zip(people, gear, strict=True):
        if not zone.contains_person(person.box):
            continue
        # A size gate reduces overconfident absence claims. It cannot detect all occlusions.
        enough_detail = (person.box[3] - person.box[1]) * inference_height >= 80
        head_visible = person.box[1] > 0.01
        states: dict[str, PPEState] = {}
        for kind in ("helmet", "vest"):
            if not ppe_available:
                states[kind] = "unavailable"
            elif items[kind]:
                states[kind] = "detected"
            elif not enough_detail or (kind == "helmet" and not head_visible):
                states[kind] = "uncertain"
            else:
                states[kind] = "not_detected"
        assessed.append({"box": person.box, **states})

    restriction = (permit.restriction(now) if permit else "no_permit") if check_permit else None
    reasons = [restriction] if assessed and restriction else []
    uncertain = False
    for kind, required in (("helmet", zone.require_helmet), ("vest", zone.require_vest)):
        if required and any(p[kind] == "not_detected" for p in assessed):
            reasons.append(f"{kind}_not_detected")
        if required and any(p[kind] in {"uncertain", "unavailable"} for p in assessed):
            uncertain = True

    if not assessed:
        status = "no_people"
    elif restriction:
        status = "restricted"
    elif reasons:
        status = "review"
    elif uncertain:
        status = "uncertain"
    else:
        status = "active"
    return {
        "status": status,
        "people": assessed,
        "people_in_zone": len(assessed),
        "people_total": len(people),
        "reasons": reasons,
        "uncertain": uncertain,
        "permit_restriction": restriction,
    }


class IncidentGate:
    """One event per continuous observation of one reason, using media timestamps."""

    def __init__(self, minimum_seconds: float = 1.0, grace_seconds: float = 0.65):
        self.minimum_seconds = minimum_seconds
        self.grace_seconds = grace_seconds
        self.started_at: float | None = None
        self.last_seen: float | None = None
        self.emitted = False

    def observe(self, timestamp: float, present: bool) -> bool:
        if self.last_seen is not None and timestamp - self.last_seen > self.grace_seconds:
            self.started_at = None
            self.emitted = False
        if not present:
            return False
        if self.started_at is None:
            self.started_at = timestamp
        self.last_seen = timestamp
        if not self.emitted and timestamp - self.started_at >= self.minimum_seconds:
            self.emitted = True
            return True
        return False
