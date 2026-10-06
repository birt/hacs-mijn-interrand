"""The Mijn Interrand integration."""
from __future__ import annotations

from homeassistant.const import CONF_PASSWORD, CONF_USERNAME, Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er, issue_registry as ir
from homeassistant.helpers.aiohttp_client import async_create_clientsession

from .api import InterrandClient
from .const import CONF_STREET_ID, DOMAIN
from .coordinator import (
    InterrandConfigEntry,
    InterrandCoordinator,
    InterrandRuntimeData,
    RecycleCoordinator,
)
from .recycle_api import RecycleClient

PLATFORMS = [Platform.BINARY_SENSOR, Platform.CALENDAR, Platform.SENSOR]


async def async_setup_entry(hass: HomeAssistant, entry: InterrandConfigEntry) -> bool:
    # A dedicated session so the login cookie is not shared with other integrations.
    session = async_create_clientsession(hass)
    client = InterrandClient(session, entry.data[CONF_USERNAME], entry.data[CONF_PASSWORD])
    portal = InterrandCoordinator(hass, entry, client)
    await portal.async_config_entry_first_refresh()

    recycle = None
    issue_id = f"address_missing_{entry.entry_id}"
    if CONF_STREET_ID in entry.data:
        recycle = RecycleCoordinator(hass, entry, RecycleClient(session))
        await recycle.async_config_entry_first_refresh()
        _remove_portal_collection_entities(hass, entry)
        ir.async_delete_issue(hass, DOMAIN, issue_id)
    else:
        ir.async_create_issue(
            hass,
            DOMAIN,
            issue_id,
            is_fixable=False,
            severity=ir.IssueSeverity.WARNING,
            translation_key="address_missing",
        )

    entry.runtime_data = InterrandRuntimeData(portal=portal, recycle=recycle)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: InterrandConfigEntry) -> bool:
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def async_remove_entry(hass: HomeAssistant, entry: InterrandConfigEntry) -> None:
    ir.async_delete_issue(hass, DOMAIN, f"address_missing_{entry.entry_id}")


def _remove_portal_collection_entities(hass: HomeAssistant, entry: InterrandConfigEntry) -> None:
    """Drop the portal-based collection sensors once the Recycle! calendar replaces them.

    This frees their entity IDs, so the new sensors take over the same IDs.
    """
    registry = er.async_get(hass)
    prefix = f"{entry.unique_id}_next_collection_"
    for entity in er.async_entries_for_config_entry(registry, entry.entry_id):
        if entity.unique_id.startswith(prefix):
            registry.async_remove(entity.entity_id)
