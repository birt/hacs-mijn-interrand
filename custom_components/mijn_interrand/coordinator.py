"""Data update coordinators for Mijn Interrand."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .api import InterrandAuthError, InterrandClient, InterrandData, InterrandError
from .const import (
    CONF_HOUSE_NUMBER,
    CONF_RECYCLING_PARK,
    CONF_STREET_ID,
    CONF_ZIPCODE_ID,
    DOMAIN,
    RECYCLE_LOOKAHEAD,
    RECYCLE_MAX_STALE,
    RECYCLE_RETRY_INTERVAL,
    RECYCLE_UPDATE_INTERVAL,
    TRANSACTION_COUNT,
    UPDATE_INTERVAL,
)
from .recycle_api import Collection, RecycleClient, RecycleError, RecyclingPark

_LOGGER = logging.getLogger(__name__)


@dataclass
class InterrandRuntimeData:
    portal: InterrandCoordinator
    # None for entries set up before the address step existed.
    recycle: RecycleCoordinator | None


type InterrandConfigEntry = ConfigEntry[InterrandRuntimeData]


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


@dataclass
class RecycleData:
    collections: list[Collection]
    recycling_park: RecyclingPark | None
    fetched_at: datetime


class RecycleCoordinator(DataUpdateCoordinator[RecycleData]):
    """Polls the Recycle! app for the collection calendar and recycling park."""

    config_entry: InterrandConfigEntry

    def __init__(self, hass: HomeAssistant, entry: InterrandConfigEntry, client: RecycleClient) -> None:
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=f"{DOMAIN}_recycle",
            update_interval=RECYCLE_UPDATE_INTERVAL,
        )
        self.client = client

    async def _async_update_data(self) -> RecycleData:
        try:
            result = await self._async_fetch()
        except RecycleError as err:
            # Collection dates rarely change, so a short outage of the API
            # should not make every sensor unavailable. Keep the last data
            # and retry sooner, unless that data has become too old.
            if self.data is None or dt_util.utcnow() - self.data.fetched_at > RECYCLE_MAX_STALE:
                raise UpdateFailed(str(err)) from err
            _LOGGER.warning(
                "Error fetching Recycle! data, keeping data from %s and retrying in %s: %s",
                dt_util.as_local(self.data.fetched_at).strftime("%Y-%m-%d %H:%M"),
                RECYCLE_RETRY_INTERVAL,
                err,
            )
            self.update_interval = RECYCLE_RETRY_INTERVAL
            return self.data
        self.update_interval = RECYCLE_UPDATE_INTERVAL
        return result

    async def _async_fetch(self) -> RecycleData:
        data = self.config_entry.data
        today = dt_util.now().date()
        collections = await self.client.get_collections(
            data[CONF_ZIPCODE_ID],
            data[CONF_STREET_ID],
            data[CONF_HOUSE_NUMBER],
            today,
            today + RECYCLE_LOOKAHEAD,
        )
        park = None
        if park_id := data.get(CONF_RECYCLING_PARK):
            parks = await self.client.get_recycling_parks(data[CONF_ZIPCODE_ID])
            park = next((p for p in parks if p.id == park_id), None)
        return RecycleData(collections=collections, recycling_park=park, fetched_at=dt_util.utcnow())
