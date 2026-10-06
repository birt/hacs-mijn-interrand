"""Waste collection calendar for Mijn Interrand."""
from __future__ import annotations

from datetime import datetime, timedelta

from homeassistant.components.calendar import CalendarEntity, CalendarEvent
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.util import dt as dt_util

from .coordinator import InterrandConfigEntry, RecycleCoordinator
from .entity import InterrandEntity
from .recycle_api import Collection


async def async_setup_entry(
    hass: HomeAssistant,
    entry: InterrandConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    if (recycle := entry.runtime_data.recycle) is not None:
        async_add_entities([WasteCalendar(recycle, entry)])


def _event(collection: Collection) -> CalendarEvent:
    return CalendarEvent(
        start=collection.date,
        end=collection.date + timedelta(days=1),
        summary=collection.short_name,
        description=collection.fraction_name,
        uid=f"{collection.fraction_id}_{collection.date.isoformat()}",
    )


class WasteCalendar(InterrandEntity[RecycleCoordinator], CalendarEntity):
    _attr_translation_key = "waste_collection"

    def __init__(self, coordinator: RecycleCoordinator, entry: InterrandConfigEntry) -> None:
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{entry.unique_id}_waste_calendar"

    @property
    def event(self) -> CalendarEvent | None:
        today = dt_util.now().date()
        return next(
            (_event(c) for c in self.coordinator.data.collections if c.date >= today), None
        )

    async def async_get_events(
        self, hass: HomeAssistant, start_date: datetime, end_date: datetime
    ) -> list[CalendarEvent]:
        start = dt_util.as_local(start_date).date()
        end = dt_util.as_local(end_date).date()
        return [
            _event(c)
            for c in self.coordinator.data.collections
            # All-day events cover [date, date + 1 day).
            if c.date + timedelta(days=1) > start and c.date <= end
        ]
