"""Recycling park open/closed sensor for Mijn Interrand."""
from __future__ import annotations

from datetime import datetime, time
from typing import Any

from homeassistant.components.binary_sensor import BinarySensorDeviceClass, BinarySensorEntity
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import async_track_time_change
from homeassistant.util import dt as dt_util

from .coordinator import InterrandConfigEntry, RecycleCoordinator
from .entity import InterrandEntity
from .recycle_api import RecyclingPark

WEEKDAYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")


async def async_setup_entry(
    hass: HomeAssistant,
    entry: InterrandConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    recycle = entry.runtime_data.recycle
    if recycle is not None and recycle.data.recycling_park is not None:
        async_add_entities([RecyclingParkOpen(recycle, entry, recycle.data.recycling_park)])


def _format_hours(hours: list[tuple[time, time]]) -> str:
    if not hours:
        return "closed"
    return ", ".join(f"{start:%H:%M}-{end:%H:%M}" for start, end in sorted(hours))


class RecyclingParkOpen(InterrandEntity[RecycleCoordinator], BinarySensorEntity):
    _attr_device_class = BinarySensorDeviceClass.OPENING
    _attr_translation_key = "recycling_park"
    _attr_icon = "mdi:warehouse"

    def __init__(self, coordinator: RecycleCoordinator, entry: InterrandConfigEntry, park: RecyclingPark) -> None:
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{entry.unique_id}_recycling_park_{park.id}"
        self._attr_translation_placeholders = {"park": park.name}

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        # Opening hours change the state without new data; re-evaluate every minute.
        self.async_on_remove(async_track_time_change(self.hass, self._async_tick, second=0))

    @callback
    def _async_tick(self, _now: datetime) -> None:
        self.async_write_ha_state()

    @property
    def _park(self) -> RecyclingPark | None:
        return self.coordinator.data.recycling_park

    @property
    def available(self) -> bool:
        return super().available and self._park is not None

    @property
    def is_on(self) -> bool | None:
        return self._park.is_open(dt_util.now()) if self._park else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        if not (park := self._park):
            return {}
        now = dt_util.now()
        next_opening = park.next_opening(now)
        next_closing = park.next_closing(now)
        return {
            "address": park.address,
            "today": _format_hours(park.hours_on(now.date())),
            "next_opening": next_opening.isoformat() if next_opening else None,
            "next_closing": next_closing.isoformat() if next_closing else None,
            "opening_hours": {
                day: _format_hours(park.weekly.get(index, []))
                for index, day in enumerate(WEEKDAYS, start=1)
            },
        }
