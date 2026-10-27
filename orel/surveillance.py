"""Portable, dependency-free surveillance rules for local or future camera adapters.

Track IDs are short-lived geometric hints, never person identities. Ambiguous
matches start over rather than inheriting someone else's warning timer.
"""

import uuid
from dataclasses import dataclass

from orel.domain import Box, Zone
from orel.temporal import TemporalCondition

ESCALATION_SECONDS = 10.0
MAX_OBSERVATION_GAP = 1.25
TRACK_RECOVERY_SECONDS = 3.0


def intersection_over_union(a: Box, b: Box) -> float:
    left, top = max(a[0], b[0]), max(a[1], b[1])
    right, bottom = min(a[2], b[2]), min(a[3], b[3])
    common = max(0, right - left) * max(0, bottom - top)
    union = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - common
    return common / union if union > 0 else 0


@dataclass
class Track:
    box: Box
    last_seen: float


@dataclass
class Episode:
    id: str
    started_at: float
    event_id: str | None = None
    saved_severity: str | None = None


class SurveillanceRules:
    def __init__(self):
        self.tracks: dict[int, Track] = {}
        self.episodes: dict[tuple[int, str], Episode] = {}
        self.conditions: dict[tuple[int, str], TemporalCondition] = {}
        self.pending_count = 0
        self.next_track = 1
        self.last_time: float | None = None

    def reset(self):
        self.tracks.clear()
        self.episodes.clear()
        self.conditions.clear()
        self.pending_count = 0
        self.last_time = None

    def _match(self, people: list[dict], timestamp: float) -> list[int]:
        self.tracks = {
            track_id: track
            for track_id, track in self.tracks.items()
            if timestamp - track.last_seen <= TRACK_RECOVERY_SECONDS
        }
        candidates = sorted(
            (
                (intersection_over_union(tuple(person["box"]), track.box), index, track_id)
                for index, person in enumerate(people)
                for track_id, track in self.tracks.items()
            ),
            reverse=True,
        )
        candidates = [item for item in candidates if item[0] >= 0.35]
        assigned: dict[int, int] = {}
        used = set()
        for score, index, track_id in candidates:
            ambiguous = any(
                abs(score - other_score) < 0.12
                and (
                    (index == other_index and track_id != other_id)
                    or (track_id == other_id and index != other_index)
                )
                for other_score, other_index, other_id in candidates
            )
            if not ambiguous and index not in assigned and track_id not in used:
                assigned[index] = track_id
                used.add(track_id)
        # Keep missing boxes briefly, but retire contested matches instead of
        # letting an ambiguous old ID attach to someone in a later frame.
        candidate_tracks = {track_id for _, _, track_id in candidates}
        current = {
            track_id: track
            for track_id, track in self.tracks.items()
            if track_id not in candidate_tracks
        }
        ids = []
        for index, person in enumerate(people):
            track_id = assigned.get(index)
            if track_id is None:
                track_id = self.next_track
                self.next_track += 1
            current[track_id] = Track(tuple(person["box"]), timestamp)
            ids.append(track_id)
        self.tracks = current
        return ids

    def assess(
        self,
        people: list[dict],
        timestamp: float,
        require_helmet: bool,
        require_vest: bool,
        danger_zone: dict | None,
    ) -> list[dict]:
        if self.last_time is not None and (
            timestamp - self.last_time > MAX_OBSERVATION_GAP or timestamp <= self.last_time
        ):
            self.reset()
        self.last_time = timestamp
        ids = self._match(people, timestamp)
        active = {}
        alerts = []
        danger = Zone(**danger_zone) if danger_zone else None
        conditions = {}

        def condition(track_id: int, kind: str, value: bool | None) -> TemporalCondition:
            key = track_id, kind
            state = self.conditions.get(key) or TemporalCondition()
            state.observe(timestamp, value)
            if (
                state.since is not None
                and timestamp - state.since >= ESCALATION_SECONDS
                and value is True
                and len(state.samples) >= 3
                and all(present for _, present in list(state.samples)[-3:])
            ):
                state.critical = True
            conditions[key] = state
            return state

        for person, track_id in zip(people, ids, strict=True):
            person["track_id"] = track_id
            missing = []
            gear_since = []
            gear_critical = False
            for kind, required in (("helmet", require_helmet), ("vest", require_vest)):
                if not required:
                    continue
                raw = person[kind]
                state = condition(
                    track_id,
                    kind,
                    None if raw in {"uncertain", "unavailable"} else raw == "not_detected",
                )
                if state.since is not None:
                    missing.append(kind)
                    gear_since.append(state.since)
                    gear_critical = gear_critical or state.critical
            signals = []
            if missing:
                signals.append(
                    ("ppe_required", "Наденьте СИЗ", "Весь кадр", min(gear_since), gear_critical)
                )
            if danger:
                state = condition(
                    track_id, "danger", danger.intersects_person(tuple(person["box"]))
                )
                if state.since is not None:
                    signals.append(
                        (
                            "danger_zone",
                            "Покиньте опасную зону",
                            danger.name,
                            state.since,
                            state.critical,
                        )
                    )
            for code, message, zone_name, since, critical in signals:
                key = track_id, code
                episode = self.episodes.get(key) or Episode(uuid.uuid4().hex, since)
                episode.started_at = since
                active[key] = episode
                duration = max(0, timestamp - episode.started_at)
                alerts.append(
                    {
                        "id": episode.id,
                        "track_id": track_id,
                        "code": code,
                        "message": message,
                        "zone": zone_name,
                        "missing": missing if code == "ppe_required" else [],
                        "severity": "critical" if critical else "warning",
                        "duration_seconds": round(duration, 1),
                        "escalates_after": ESCALATION_SECONDS,
                    }
                )
        self.episodes = active
        self.conditions = conditions
        self.pending_count = sum(state.pending for state in conditions.values())
        return alerts
