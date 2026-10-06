"""Sensors for Mijn Interrand."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime
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
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import async_track_time_change
from homeassistant.util import dt as dt_util, slugify

from .api import InterrandData, Transaction
from .coordinator import InterrandConfigEntry, InterrandCoordinator, RecycleCoordinator
from .entity import InterrandEntity
from .recycle_api import Collection

FRACTION_ICONS = {
    "restafval": "mdi:trash-can",
    "gft": "mdi:leaf",
    "pmd": "mdi:recycle",
    "papier": "mdi:newspaper-variant-outline",
    "glas": "mdi:bottle-wine",
    "grofvuil": "mdi:sofa",
    "kerstbomen": "mdi:pine-tree",
    "textiel": "mdi:tshirt-crew",
    "snoeihout": "mdi:tree",
}


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
    portal = entry.runtime_data.portal
    recycle = entry.runtime_data.recycle
    async_add_entities(InterrandSensor(portal, entry, description) for description in SENSORS)

    # One sensor per fraction, created for whatever fractions show up.
    known: set[str] = set()

    if recycle is None:
        # No address configured: fall back to the dates on the portal page.
        @callback
        def _add_portal_collection_sensors() -> None:
            new = [f for f in portal.data.collections if f not in known]
            known.update(new)
            if new:
                async_add_entities(PortalCollectionSensor(portal, entry, f) for f in new)

        _add_portal_collection_sensors()
        entry.async_on_unload(portal.async_add_listener(_add_portal_collection_sensors))
        return

    @callback
    def _add_collection_sensors() -> None:
        fractions = {c.fraction_id: c.short_name for c in recycle.data.collections}
        new = [fid for fid in fractions if fid not in known]
        known.update(new)
        if new:
            async_add_entities(
                CollectionSensor(recycle, entry, fid, fractions[fid]) for fid in new
            )

    _add_collection_sensors()
    entry.async_on_unload(recycle.async_add_listener(_add_collection_sensors))


class InterrandSensor(InterrandEntity[InterrandCoordinator], SensorEntity):
    entity_description: InterrandSensorDescription

    def __init__(
        self,
        coordinator: InterrandCoordinator,
        entry: InterrandConfigEntry,
        description: InterrandSensorDescription,
    ) -> None:
        super().__init__(coordinator, entry)
        self.entity_description = description
        self._attr_unique_id = f"{entry.unique_id}_{description.key}"

    @property
    def native_value(self) -> Decimal | float | date | None:
        return self.entity_description.value_fn(self.coordinator.data)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return self.entity_description.attrs_fn(self.coordinator.data)


class CollectionSensor(InterrandEntity[RecycleCoordinator], SensorEntity):
    """Next collection date of one fraction, from the Recycle! calendar."""

    _attr_device_class = SensorDeviceClass.DATE
    _attr_translation_key = "next_collection"

    def __init__(
        self,
        coordinator: RecycleCoordinator,
        entry: InterrandConfigEntry,
        fraction_id: str,
        short_name: str,
    ) -> None:
        super().__init__(coordinator, entry)
        self._fraction_id = fraction_id
        self._attr_unique_id = f"{entry.unique_id}_collection_{fraction_id}"
        self._attr_translation_placeholders = {"fraction": short_name}
        slug = slugify(short_name)
        self._attr_icon = next(
            (icon for key, icon in FRACTION_ICONS.items() if slug.startswith(key)), "mdi:trash-can"
        )

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        # Move on to the next date right after midnight, without refetching.
        self.async_on_remove(
            async_track_time_change(self.hass, self._async_midnight, hour=0, minute=0, second=5)
        )

    @callback
    def _async_midnight(self, _now: datetime) -> None:
        self.async_write_ha_state()

    def _upcoming(self) -> list[Collection]:
        today = dt_util.now().date()
        return [
            c
            for c in self.coordinator.data.collections
            if c.fraction_id == self._fraction_id and c.date >= today
        ]

    @property
    def native_value(self) -> date | None:
        upcoming = self._upcoming()
        return upcoming[0].date if upcoming else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        upcoming = self._upcoming()
        if not upcoming:
            return {}
        return {
            "fraction": upcoming[0].fraction_name,
            "days_until": (upcoming[0].date - dt_util.now().date()).days,
            "upcoming": [c.date.isoformat() for c in upcoming[:5]],
            "color": upcoming[0].color,
        }


class PortalCollectionSensor(InterrandEntity[InterrandCoordinator], SensorEntity):
    """Next collection date as shown on the portal, used when no address is configured."""

    _attr_device_class = SensorDeviceClass.DATE
    _attr_translation_key = "next_collection"
    _attr_icon = "mdi:trash-can"

    def __init__(self, coordinator: InterrandCoordinator, entry: InterrandConfigEntry, fraction: str) -> None:
        super().__init__(coordinator, entry)
        self._fraction = fraction
        self._attr_unique_id = f"{entry.unique_id}_next_collection_{slugify(fraction)}"
        self._attr_translation_placeholders = {"fraction": fraction}

    @property
    def available(self) -> bool:
        return super().available and self._fraction in self.coordinator.data.collections

    @property
    def native_value(self) -> date | None:
        return self.coordinator.data.collections.get(self._fraction)
