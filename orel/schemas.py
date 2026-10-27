from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator, model_validator


class RectangleInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=100)
    left: float = Field(ge=0, le=1)
    top: float = Field(ge=0, le=1)
    right: float = Field(ge=0, le=1)
    bottom: float = Field(ge=0, le=1)
    points: list[tuple[float, float]] | None = Field(default=None, min_length=4, max_length=4)

    @model_validator(mode="after")
    def valid_rectangle(self):
        if not self.name.strip() or self.right <= self.left or self.bottom <= self.top:
            raise ValueError("Задайте название и ненулевую область зоны.")
        if self.points:
            if any(not (0 <= x <= 1 and 0 <= y <= 1) for x, y in self.points):
                raise ValueError("Точки должны находиться внутри кадра.")
            crosses = []
            for i in range(4):
                a, b, c = self.points[i], self.points[(i + 1) % 4], self.points[(i + 2) % 4]
                crosses.append((b[0] - a[0]) * (c[1] - b[1]) - (b[1] - a[1]) * (c[0] - b[0]))
            if not (all(v > 1e-5 for v in crosses) or all(v < -1e-5 for v in crosses)):
                raise ValueError("Выберите четыре угла по порядку, без пересечений.")
            self.left = min(p[0] for p in self.points)
            self.right = max(p[0] for p in self.points)
            self.top = min(p[1] for p in self.points)
            self.bottom = max(p[1] for p in self.points)
        return self


class ZoneInput(RectangleInput):
    require_helmet: bool = True
    require_vest: bool = True


class PermitInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    number: str = Field(min_length=1, max_length=100)
    starts_at: datetime
    ends_at: datetime
    closed: bool = False

    @field_validator("starts_at", "ends_at")
    @classmethod
    def aware_time(cls, value: datetime):
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("Укажите часовой пояс.")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def valid_interval(self):
        if not self.number.strip() or self.ends_at <= self.starts_at:
            raise ValueError("Укажите номер и корректный интервал наряда.")
        return self


class Configuration(BaseModel):
    model_config = ConfigDict(extra="forbid")
    video_id: str = Field(min_length=1, max_length=64)
    zone: ZoneInput | None = None
    permit: PermitInput | None = None


class AnalysisInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    model: Literal["person", "ppe"] = "ppe"


class PlaybackInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    session_id: str = Field(min_length=1, max_length=64)
    video_id: str = Field(min_length=1, max_length=64)
    position: float = Field(ge=0, allow_inf_nan=False)
    playing: bool = False
    seeking: bool = False


class EventReview(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reviewed: bool


class CameraSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")
    require_helmet: bool = True
    require_vest: bool = False
    danger_zone: RectangleInput | None = None


class TelegramTokenInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    token: SecretStr


class TelegramConfiguration(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enabled: bool
    chat_id: str = Field(max_length=100)
