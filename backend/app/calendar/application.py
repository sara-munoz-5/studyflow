from dataclasses import replace
from datetime import datetime, timedelta, timezone

from app.planning.domain.entities import Window
from app.planning.domain.repositories import PlanRepository

from .domain import BOGOTA, PersonalBlock, PersonalRepository, occurrences


class PersonalBlockNotFound(Exception):
    pass


class PersonalBlockConflict(Exception):
    pass


def personal_windows(repository: PersonalRepository, windows: list[Window]) -> list[Window]:
    if not windows:
        return []
    return list(dict.fromkeys(
        Window(item.start.astimezone(timezone.utc), item.end.astimezone(timezone.utc))
        for block in repository.list_all() for window in windows
        for item in occurrences(block, window.start, window.end)
    ))


def conflicting_windows(block: PersonalBlock, reservations: list[Window]):
    return (item for item in reservations if next(occurrences(block, item.start, item.end), None))


class PersonalSchedule:
    def __init__(self, repository: PersonalRepository, reservations: PlanRepository):
        self.repository = repository
        self.reservations = reservations

    def get(self, block_id: int) -> PersonalBlock:
        block = self.repository.get(block_id)
        if block is None:
            raise PersonalBlockNotFound("Compromiso personal no encontrado")
        return block

    def save(self, block: PersonalBlock) -> PersonalBlock:
        with self.reservations.serialized():
            if block.id is not None:
                self.get(block.id)
            reserved = self.reservations.busy(datetime.now(timezone.utc))
            conflict = next(conflicting_windows(block, reserved), None)
            if conflict:
                start = conflict.start.astimezone(BOGOTA)
                finish = conflict.end.astimezone(BOGOTA)
                message = (f"Hay una sesión reservada el {start:%d/%m/%Y} de {start:%H:%M} a {finish:%H:%M}. "
                           "El plan aprobado conserva su reserva. Cambia las horas del compromiso o replantea el plan primero.")
                alternative = self.alternative(block, reserved)
                if alternative:
                    message += f" Una alternativa es {alternative.start_time:%H:%M}–{alternative.end_time:%H:%M}."
                raise PersonalBlockConflict(message)
            return self.repository.save(block)

    @staticmethod
    def alternative(block: PersonalBlock, reserved: list[Window]) -> PersonalBlock | None:
        start = datetime.combine(block.day, block.start_time)
        end = datetime.combine(block.day, block.end_time)
        for minutes in range(15, 1440, 15):
            shift = timedelta(minutes=minutes)
            shifted_start, shifted_end = start + shift, end + shift
            if shifted_end.date() != block.day:
                break
            candidate = replace(block, start_time=shifted_start.time(), end_time=shifted_end.time())
            if not next(conflicting_windows(candidate, reserved), None):
                return candidate
        return None

    def delete(self, block_id: int) -> None:
        with self.reservations.serialized():
            if not self.repository.delete(block_id):
                raise PersonalBlockNotFound("Compromiso personal no encontrado")
