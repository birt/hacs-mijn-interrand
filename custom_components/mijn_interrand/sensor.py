"""Sensors for Mijn Interrand."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import CURRENCY_EURO, UnitOfMass
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import slugify

from .api import InterrandData, Transaction
from .const import DOMAIN
from .coordinator import InterrandConfigEntry, InterrandCoordinator


def _latest(data: InterrandData, tx_type: str | None = None) -> Transaction | None:
    for tx in data.transactions:
        if tx_type is None or tx.type.lower() == tx_type:
            return tx
    return None


def _tx_attrs(tx: Transaction | None) -> dict[str, Any]:
    return tx.as_dict() if tx else {}


def _balance_attrs(data: InterrandData) -> dict[str, Any]:
    return {
        "customer_number": data.customer_number,
        "ogm": data.ogm,
        "residents": data.residents,
        "address": data.address,
        "transaction_count": data.transaction_count,
        "recent_transactions": [tx.as_dict() for tx in data.transactions],
    }


def _last_weight(data: InterrandData) -> float | None:
    tx = _latest(data, "gewicht")
    return tx.weight_kg if tx else None


@dataclass(frozen=True, kw_only=True)
class InterrandSensorDescription(SensorEntityDescription):
    value_fn: Callable[[InterrandData], Decimal | float | date | None]
    attrs_fn: Callable[[InterrandData], dict[str, Any]] = lambda _: {}


SENSORS: tuple[InterrandSensorDescription, ...] = (
    InterrandSensorDescription(
        key="balance",
        translation_key="balance",
        device_class=SensorDeviceClass.MONETARY,
        state_class=SensorStateClass.TOTAL,
        native_unit_of_measurement=CURRENCY_EURO,
        suggested_display_precision=2,
        value_fn=lambda data: data.balance,
        attrs_fn=_balance_attrs,
    ),
    InterrandSensorDescription(
        key="last_transaction",
        translation_key="last_transaction",
        device_class=SensorDeviceClass.MONETARY,
        native_unit_of_measurement=CURRENCY_EURO,
        suggested_display_precision=2,
        value_fn=lambda data: (tx.amount if (tx := _latest(data)) else None),
        attrs_fn=lambda data: _tx_attrs(_latest(data)),
    ),
    InterrandSensorDescription(
        key="last_weight",
        translation_key="last_weight",
        device_class=SensorDeviceClass.WEIGHT,
        native_unit_of_measurement=UnitOfMass.KILOGRAMS,
        suggested_display_precision=1,
        value_fn=_last_weight,
        attrs_fn=lambda data: _tx_attrs(_latest(data, "gewicht")),
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: InterrandConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data
    async_add_entities(InterrandSensor(coordinator, description) for description in SENSORS)

    # The portal lists one "Volgende inzameling <fraction>" line per container,
    # so collection sensors are created for whatever fractions show up.
    known: set[str] = set()

    @callback
    def _add_collection_sensors() -> None:
        new = [f for f in coordinator.data.collections if f not in known]
        known.update(new)
        if new:
            async_add_entities(InterrandCollectionSensor(coordinator, fraction) for fraction in new)

    _add_collection_sensors()
    entry.async_on_unload(coordinator.async_add_listener(_add_collection_sensors))


class InterrandEntity(CoordinatorEntity[InterrandCoordinator]):
    _attr_has_entity_name = True

    def __init__(self, coordinator: InterrandCoordinator) -> None:
        super().__init__(coordinator)
        entry = coordinator.config_entry
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.unique_id or entry.entry_id)},
            name="Interrand",
            manufacturer="Interrand",
            model=coordinator.data.address,
            entry_type=DeviceEntryType.SERVICE,
            configuration_url="https://www.mijninterrand.be/Aansluitpunten/Verrichtingen",
        )


class InterrandSensor(InterrandEntity, SensorEntity):
    entity_description: InterrandSensorDescription

    def __init__(self, coordinator: InterrandCoordinator, description: InterrandSensorDescription) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{coordinator.config_entry.unique_id}_{description.key}"

    @property
    def native_value(self) -> Decimal | float | date | None:
        return self.entity_description.value_fn(self.coordinator.data)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return self.entity_description.attrs_fn(self.coordinator.data)


class InterrandCollectionSensor(InterrandEntity, SensorEntity):
    _attr_device_class = SensorDeviceClass.DATE
    _attr_translation_key = "next_collection"
    _attr_icon = "mdi:trash-can"

    def __init__(self, coordinator: InterrandCoordinator, fraction: str) -> None:
        super().__init__(coordinator)
        self._fraction = fraction
        self._attr_unique_id = f"{coordinator.config_entry.unique_id}_next_collection_{slugify(fraction)}"
        self._attr_translation_placeholders = {"fraction": fraction}

    @property
    def available(self) -> bool:
        return super().available and self._fraction in self.coordinator.data.collections

    @property
    def native_value(self) -> date | None:
        return self.coordinator.data.collections.get(self._fraction)
