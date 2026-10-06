"""The Mijn Interrand integration."""
from __future__ import annotations

from homeassistant.const import CONF_PASSWORD, CONF_USERNAME, Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_create_clientsession

from .api import InterrandClient
from .coordinator import InterrandConfigEntry, InterrandCoordinator

PLATFORMS = [Platform.SENSOR]


async def async_setup_entry(hass: HomeAssistant, entry: InterrandConfigEntry) -> bool:
    # A dedicated session so the login cookie is not shared with other integrations.
    session = async_create_clientsession(hass)
    client = InterrandClient(session, entry.data[CONF_USERNAME], entry.data[CONF_PASSWORD])
    coordinator = InterrandCoordinator(hass, entry, client)
    await coordinator.async_config_entry_first_refresh()

    entry.runtime_data = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: InterrandConfigEntry) -> bool:
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
