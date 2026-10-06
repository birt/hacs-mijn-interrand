"""Data update coordinator for Mijn Interrand."""
from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import InterrandAuthError, InterrandClient, InterrandData, InterrandError
from .const import DOMAIN, TRANSACTION_COUNT, UPDATE_INTERVAL

_LOGGER = logging.getLogger(__name__)

type InterrandConfigEntry = ConfigEntry[InterrandCoordinator]


class InterrandCoordinator(DataUpdateCoordinator[InterrandData]):
    """Polls the Mijn Interrand portal."""

    config_entry: InterrandConfigEntry

    def __init__(self, hass: HomeAssistant, entry: InterrandConfigEntry, client: InterrandClient) -> None:
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=DOMAIN,
            update_interval=UPDATE_INTERVAL,
        )
        self.client = client

    async def _async_update_data(self) -> InterrandData:
        try:
            return await self.client.fetch(TRANSACTION_COUNT)
        except InterrandAuthError as err:
            raise ConfigEntryAuthFailed(str(err)) from err
        except InterrandError as err:
            raise UpdateFailed(str(err)) from err
