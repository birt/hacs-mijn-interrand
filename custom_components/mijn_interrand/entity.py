"""Base entity for Mijn Interrand."""
from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity, DataUpdateCoordinator

from .const import DOMAIN
from .coordinator import InterrandConfigEntry


class InterrandEntity[_CoordinatorT: DataUpdateCoordinator](CoordinatorEntity[_CoordinatorT]):
    """All entities of a config entry share one device."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: _CoordinatorT, entry: InterrandConfigEntry) -> None:
        super().__init__(coordinator)
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.unique_id or entry.entry_id)},
            name="Interrand",
            manufacturer="Interrand",
            model=entry.runtime_data.portal.data.address,
            entry_type=DeviceEntryType.SERVICE,
            configuration_url="https://www.mijninterrand.be/Aansluitpunten/Verrichtingen",
        )
