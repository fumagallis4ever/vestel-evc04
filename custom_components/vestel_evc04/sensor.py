"""Sensoren der Vestel EVC04."""

from __future__ import annotations

from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import (
    EntityCategory,
    UnitOfElectricCurrent,
    UnitOfElectricPotential,
    UnitOfEnergy,
    UnitOfPower,
    UnitOfTime,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import CABLE_STATE, CHARGEPOINT_STATE, EQUIPMENT_STATE
from .coordinator import VestelConfigEntry, VestelEntity

ENUM_KEYS = {"chargepoint_state", "equipment_state", "cable_state"}

A = UnitOfElectricCurrent.AMPERE
CURRENT = SensorDeviceClass.CURRENT
MEAS = SensorStateClass.MEASUREMENT
DIAG = EntityCategory.DIAGNOSTIC


def _phase_sensors() -> list[SensorEntityDescription]:
    out: list[SensorEntityDescription] = []
    for p in ("l1", "l2", "l3"):
        up = p.upper()
        out += [
            SensorEntityDescription(
                key=f"current_{p}",
                name=f"Strom {up}",
                native_unit_of_measurement=A,
                device_class=CURRENT,
                state_class=MEAS,
                suggested_display_precision=2,
            ),
            SensorEntityDescription(
                key=f"voltage_{p}",
                name=f"Spannung {up}",
                native_unit_of_measurement=UnitOfElectricPotential.VOLT,
                device_class=SensorDeviceClass.VOLTAGE,
                state_class=MEAS,
                suggested_display_precision=0,
            ),
            SensorEntityDescription(
                key=f"power_{p}",
                name=f"Leistung {up}",
                native_unit_of_measurement=UnitOfPower.WATT,
                device_class=SensorDeviceClass.POWER,
                state_class=MEAS,
                suggested_display_precision=0,
            ),
        ]
    return out


SENSORS: tuple[SensorEntityDescription, ...] = (
    SensorEntityDescription(
        key="chargepoint_state",
        name="Ladepunktstatus",
        device_class=SensorDeviceClass.ENUM,
        options=list(CHARGEPOINT_STATE.values()),
    ),
    SensorEntityDescription(
        key="cable_state",
        name="Kabelstatus",
        device_class=SensorDeviceClass.ENUM,
        options=list(CABLE_STATE.values()),
    ),
    SensorEntityDescription(
        key="equipment_state",
        name="Gerätestatus",
        device_class=SensorDeviceClass.ENUM,
        options=list(EQUIPMENT_STATE.values()),
    ),
    SensorEntityDescription(
        key="power",
        name="Ladeleistung",
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=MEAS,
        suggested_display_precision=0,
    ),
    *_phase_sensors(),
    SensorEntityDescription(
        key="energy_total",
        name="Zählerstand",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        suggested_display_precision=1,
    ),
    SensorEntityDescription(
        key="session_energy",
        name="Energie Ladevorgang",
        native_unit_of_measurement=UnitOfEnergy.WATT_HOUR,
        suggested_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        suggested_display_precision=2,
    ),
    SensorEntityDescription(
        key="session_duration",
        name="Dauer Ladevorgang",
        native_unit_of_measurement=UnitOfTime.SECONDS,
        suggested_unit_of_measurement=UnitOfTime.MINUTES,
        device_class=SensorDeviceClass.DURATION,
        suggested_display_precision=0,
    ),
    SensorEntityDescription(
        key="charging_current_setpoint",
        name="Ladestromvorgabe",
        native_unit_of_measurement=A,
        device_class=CURRENT,
        state_class=MEAS,
    ),
    SensorEntityDescription(
        key="fault_code",
        name="Fehlercode",
        entity_category=DIAG,
    ),
    SensorEntityDescription(
        key="hw_max_current",
        name="Max. Ladestrom Wallbox",
        native_unit_of_measurement=A,
        device_class=CURRENT,
        entity_category=DIAG,
    ),
    SensorEntityDescription(
        key="hw_min_current",
        name="Min. Ladestrom Wallbox",
        native_unit_of_measurement=A,
        device_class=CURRENT,
        entity_category=DIAG,
    ),
    SensorEntityDescription(
        key="cable_max_current",
        name="Max. Ladestrom Kabel",
        native_unit_of_measurement=A,
        device_class=CURRENT,
        entity_category=DIAG,
    ),
    SensorEntityDescription(
        key="failsafe_current",
        name="Failsafe-Strom",
        native_unit_of_measurement=A,
        device_class=CURRENT,
        entity_category=DIAG,
    ),
    SensorEntityDescription(
        key="failsafe_timeout",
        name="Failsafe-Timeout",
        native_unit_of_measurement=UnitOfTime.SECONDS,
        device_class=SensorDeviceClass.DURATION,
        entity_category=DIAG,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: VestelConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data
    async_add_entities(VestelSensor(coordinator, d) for d in SENSORS)


class VestelSensor(VestelEntity, SensorEntity):
    """Ein Messwert der Wallbox."""

    @property
    def native_value(self) -> Any:
        return self.coordinator.data.get(self.entity_description.key)

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        key = self.entity_description.key
        if key in ENUM_KEYS:
            return {"rohwert": self.coordinator.data.get(f"{key}_raw")}
        return None
