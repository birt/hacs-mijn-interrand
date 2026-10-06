"""Config flow for Mijn Interrand."""
from __future__ import annotations

from collections.abc import Mapping
import logging
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import SOURCE_RECONFIGURE, ConfigFlow, ConfigFlowResult
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.helpers.aiohttp_client import async_create_clientsession, async_get_clientsession
from homeassistant.helpers.selector import SelectOptionDict, SelectSelector, SelectSelectorConfig

from .api import InterrandAuthError, InterrandClient, InterrandError
from .const import (
    CONF_HOUSE_NUMBER,
    CONF_RECYCLING_PARK,
    CONF_STREET,
    CONF_STREET_ID,
    CONF_ZIPCODE,
    CONF_ZIPCODE_ID,
    DOMAIN,
)
from .recycle_api import RecycleClient, RecycleError, RecycleNotFound, RecyclingPark, split_address

_LOGGER = logging.getLogger(__name__)

USER_SCHEMA = vol.Schema({vol.Required(CONF_USERNAME): str, vol.Required(CONF_PASSWORD): str})
REAUTH_SCHEMA = vol.Schema({vol.Required(CONF_PASSWORD): str})
ADDRESS_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_ZIPCODE): str,
        vol.Required(CONF_STREET): str,
        vol.Required(CONF_HOUSE_NUMBER): str,
    }
)


class MijnInterrandConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1

    def __init__(self) -> None:
        self._credentials: dict[str, str] = {}
        self._title: str | None = None
        self._city: str | None = None
        self._suggested_address: dict[str, str] = {}
        self._address: dict[str, str] = {}
        self._parks: list[RecyclingPark] = []

    async def _async_validate(self, username: str, password: str) -> tuple[dict[str, str], str | None]:
        """Log in and return (errors, address shown on the portal)."""
        session = async_create_clientsession(self.hass)
        try:
            client = InterrandClient(session, username, password)
            data = await client.fetch(transaction_count=1)
        except InterrandAuthError:
            return {"base": "invalid_auth"}, None
        except InterrandError:
            _LOGGER.exception("Error connecting to Mijn Interrand")
            return {"base": "cannot_connect"}, None
        finally:
            await session.close()
        return {}, data.address

    def _suggest_from_portal(self, address: str | None) -> None:
        if address and (parts := split_address(address)):
            street, number, zipcode, city = parts
            self._suggested_address = {
                CONF_ZIPCODE: zipcode,
                CONF_STREET: street,
                CONF_HOUSE_NUMBER: number,
            }
            self._city = city

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            username = user_input[CONF_USERNAME].strip()
            await self.async_set_unique_id(username.lower())
            self._abort_if_unique_id_configured()
            errors, address = await self._async_validate(username, user_input[CONF_PASSWORD])
            if not errors:
                self._credentials = {CONF_USERNAME: username, CONF_PASSWORD: user_input[CONF_PASSWORD]}
                self._title = address or username
                self._suggest_from_portal(address)
                return await self.async_step_address()
        return self.async_show_form(
            step_id="user",
            data_schema=self.add_suggested_values_to_schema(USER_SCHEMA, user_input),
            errors=errors,
        )

    async def async_step_reconfigure(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        entry = self._get_reconfigure_entry()
        if CONF_STREET in entry.data:
            self._suggested_address = {
                key: entry.data[key] for key in (CONF_ZIPCODE, CONF_STREET, CONF_HOUSE_NUMBER)
            }
        elif runtime := getattr(entry, "runtime_data", None):
            self._suggest_from_portal(runtime.portal.data.address)
        return await self.async_step_address()

    async def async_step_address(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            zipcode = user_input[CONF_ZIPCODE].strip()
            street = user_input[CONF_STREET].strip()
            house_number = user_input[CONF_HOUSE_NUMBER].strip()
            client = RecycleClient(async_get_clientsession(self.hass))
            try:
                zip_info = await client.find_zipcode(zipcode, self._city)
            except RecycleNotFound:
                errors[CONF_ZIPCODE] = "zipcode_not_found"
            except RecycleError:
                _LOGGER.exception("Error connecting to Recycle!")
                errors["base"] = "recycle_cannot_connect"
            else:
                try:
                    street_info = await client.find_street(zip_info.id, street)
                    self._parks = await client.get_recycling_parks(zip_info.id)
                except RecycleNotFound:
                    errors[CONF_STREET] = "street_not_found"
                except RecycleError:
                    _LOGGER.exception("Error connecting to Recycle!")
                    errors["base"] = "recycle_cannot_connect"
                else:
                    self._city = zip_info.city
                    self._address = {
                        CONF_ZIPCODE: zipcode,
                        CONF_STREET: street_info.name,
                        CONF_HOUSE_NUMBER: house_number,
                        CONF_ZIPCODE_ID: zip_info.id,
                        CONF_STREET_ID: street_info.id,
                    }
                    if self._parks:
                        return await self.async_step_recycling_park()
                    return self._async_finish({CONF_RECYCLING_PARK: None})
        return self.async_show_form(
            step_id="address",
            data_schema=self.add_suggested_values_to_schema(
                ADDRESS_SCHEMA, user_input or self._suggested_address
            ),
            errors=errors,
        )

    async def async_step_recycling_park(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            return self._async_finish({CONF_RECYCLING_PARK: user_input[CONF_RECYCLING_PARK]})

        default = None
        if self.source == SOURCE_RECONFIGURE:
            default = self._get_reconfigure_entry().data.get(CONF_RECYCLING_PARK)
        if default not in {p.id for p in self._parks}:
            default = next(
                (p.id for p in self._parks if self._city and p.name.lower() == self._city.lower()),
                self._parks[0].id,
            )
        options = [SelectOptionDict(value=p.id, label=f"{p.name} ({p.address})") for p in self._parks]
        return self.async_show_form(
            step_id="recycling_park",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_RECYCLING_PARK, default=default): SelectSelector(
                        SelectSelectorConfig(options=options)
                    )
                }
            ),
        )

    def _async_finish(self, park: dict[str, Any]) -> ConfigFlowResult:
        data = {**self._address, **park}
        if self.source == SOURCE_RECONFIGURE:
            return self.async_update_reload_and_abort(self._get_reconfigure_entry(), data_updates=data)
        return self.async_create_entry(title=self._title, data={**self._credentials, **data})

    async def async_step_reauth(self, entry_data: Mapping[str, Any]) -> ConfigFlowResult:
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        entry = self._get_reauth_entry()
        errors: dict[str, str] = {}
        if user_input is not None:
            errors, _ = await self._async_validate(entry.data[CONF_USERNAME], user_input[CONF_PASSWORD])
            if not errors:
                return self.async_update_reload_and_abort(
                    entry, data_updates={CONF_PASSWORD: user_input[CONF_PASSWORD]}
                )
        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=REAUTH_SCHEMA,
            description_placeholders={"username": entry.data[CONF_USERNAME]},
            errors=errors,
        )
