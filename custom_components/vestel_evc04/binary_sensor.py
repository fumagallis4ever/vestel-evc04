"""Binärsensoren der Vestel EVC04."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import VestelConfigEntry, VestelEntity


@dataclass(frozen=True, kw_only=True)
class VestelBinarySensorDescription(BinarySensorEntityDescription):
    """Beschreibung mit Auswertefunktion."""

    is_on_fn: Callable[[dict[str, Any]], bool | None]


def _check(key: str, test: Callable[[int], bool]) -> Callable[[dict], bool | None]:
    def fn(data: dict[str, Any]) -> bool | None:
        raw = data.get(key)
        return None if raw is None else test(raw)

    return fn


BINARY_SENSORS: tuple[VestelBinarySensorDescription, ...] = (
    VestelBinarySensorDescription(
        key="charging",
        name="Ladevorgang aktiv",
        device_class=BinarySensorDeviceClass.BATTERY_CHARGING,
        is_on_fn=_check("charging_state_raw", lambda v: v == 1),
    ),
    VestelBinarySensorDescription(
        key="vehicle_connected",
        name="Fahrzeug verbunden",
        device_class=BinarySensorDeviceClass.PLUG,
        is_on_fn=_check("cable_state_raw", lambda v: v >= 2),
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: VestelConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data
    async_add_entities(VestelBinarySensor(coordinator, d) for d in BINARY_SENSORS)


class VestelBinarySensor(VestelEntity, BinarySensorEntity):
    """Ein Ja/Nein-Zustand der Wallbox."""

    entity_description: VestelBinarySensorDescription

    @property
    def is_on(self) -> bool | None:
        return self.entity_description.is_on_fn(self.coordinator.data)
