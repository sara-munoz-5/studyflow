from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from typing import Protocol
from zoneinfo import ZoneInfo

from app.planning.domain.entities import Window

BOGOTA = ZoneInfo("America/Bogota")


@dataclass
class PersonalBlock:
    title: str
    day: date
    start_time: time
    end_time: time
    category: str | None = None
    description: str | None = None
    weekdays: list[int] = field(default_factory=list)
    until: date | None = None
    id: int | None = None


class PersonalRepository(Protocol):
    def list_all(self) -> list[PersonalBlock]: ...
    def get(self, block_id: int) -> PersonalBlock | None: ...
    def save(self, block: PersonalBlock) -> PersonalBlock: ...
    def delete(self, block_id: int) -> bool: ...


def occurrences(block: PersonalBlock, start: datetime, end: datetime):
    """Yield full occurrences intersecting the half-open query interval."""
    if end <= start:
        return
    first = max(block.day, start.astimezone(BOGOTA).date())
    last = end.astimezone(BOGOTA).date()
    if block.until:
        last = min(last, block.until)
    if first > last:
        return

    def window(day):
        return Window(datetime.combine(day, block.start_time, BOGOTA),
                      datetime.combine(day, block.end_time, BOGOTA))

    def overlaps(item):
        return item.start < end and start < item.end

    if not block.weekdays:
        item = window(block.day)
        if overlaps(item):
            yield item
        return

    for weekday in sorted(block.weekdays):
        offset = (weekday - first.weekday()) % 7
        for days in range(offset, (last - first).days + 1, 7):
            item = window(first + timedelta(days=days))
            if overlaps(item):
                yield item
