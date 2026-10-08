"""Coordinator und Basis-Entity für die Vestel EVC04."""

from __future__ import annotations

from datetime import timedelta
import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_SCAN_INTERVAL
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import EntityDescription
from homeassistant.helpers.update_coordinator import (
    CoordinatorEntity,
    DataUpdateCoordinator,
    UpdateFailed,
)

from .const import (
    CABLE_STATE,
    CHARGEPOINT_STATE,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    EQUIPMENT_STATE,
)
from .modbus import (
    FC_READ_HOLDING,
    FC_READ_INPUT,
    VestelError,
    VestelModbusClient,
    VestelModbusException,
)

_LOGGER = logging.getLogger(__name__)

type VestelConfigEntry = ConfigEntry[VestelCoordinator]


def _u32(block: list[int | None], i: int) -> int | None:
    hi, lo = block[i], block[i + 1]
    if hi is None or lo is None:
        return None
    return (hi << 16) | lo


def _scale(value: int | None, factor: float, digits: int = 3) -> float | None:
    return None if value is None else round(value * factor, digits)


class VestelCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Liest alle Werte der Wallbox zyklisch."""

    config_entry: VestelConfigEntry

    def __init__(
        self,
        hass: HomeAssistant,
        entry: VestelConfigEntry,
        client: VestelModbusClient,
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=DOMAIN,
            update_interval=timedelta(
                seconds=entry.data.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
            ),
        )
        self.client = client
        self.serial_number: str | None = None
        self.firmware: str | None = None
        # Blöcke, die die Wallbox am Stück ablehnt -> einzeln lesen
        self._single_mode: set[tuple[int, int]] = set()

    async def async_read_device_info(self) -> None:
        """Seriennummer und Firmware lesen (optional)."""
        self.serial_number = await self._read_string(100, 25)
        self.firmware = await self._read_string(230, 50)

    async def _read_string(self, address: int, count: int) -> str | None:
        try:
            regs = await self.client.read_input(address, count)
        except VestelError as err:
            _LOGGER.debug("String-Register %s nicht lesbar: %s", address, err)
            return None
        raw = b"".join(r.to_bytes(2, "big") for r in regs).replace(b"\x00", b"")
        text = raw.decode("ascii", errors="ignore").strip()
        return text or None

    async def _read_block(
        self, function: int, start: int, count: int
    ) -> list[int | None]:
        """Block lesen; lehnt die Box ab, wird registerweise gelesen."""
        read = (
            self.client.read_input
            if function == FC_READ_INPUT
            else self.client.read_holding
        )
        if (function, start) not in self._single_mode:
            try:
                return list(await read(start, count))
            except VestelModbusException as err:
                _LOGGER.debug(
                    "Block %s (%s Register) abgelehnt (%s), lese einzeln",
                    start,
                    count,
                    err,
                )
                self._single_mode.add((function, start))

        result: list[int | None] = []
        for address in range(start, start + count):
            try:
                result.append((await read(address, 1))[0])
            except VestelModbusException:
                result.append(None)
        return result

    async def _async_update_data(self) -> dict[str, Any]:
        try:
            main = await self._read_block(FC_READ_INPUT, 1000, 38)
            limits = await self._read_block(FC_READ_INPUT, 1100, 5)
            session = await self._read_block(FC_READ_INPUT, 1502, 8)
            failsafe = await self._read_block(FC_READ_HOLDING, 2000, 3)
            setpoint = await self._read_block(FC_READ_HOLDING, 5004, 1)
        except VestelError as err:
            raise UpdateFailed(f"Vestel Wallbox nicht erreichbar: {err}") from err

        cp_raw, chg_raw, eq_raw, cable_raw = main[0], main[1], main[2], main[4]

        return {
            "chargepoint_state": CHARGEPOINT_STATE.get(cp_raw),
            "chargepoint_state_raw": cp_raw,
            "charging_state_raw": chg_raw,
            "equipment_state": EQUIPMENT_STATE.get(eq_raw),
            "equipment_state_raw": eq_raw,
            "cable_state": CABLE_STATE.get(cable_raw),
            "cable_state_raw": cable_raw,
            "fault_code": main[6],
            "current_l1": _scale(main[8], 0.001),
            "current_l2": _scale(main[10], 0.001),
            "current_l3": _scale(main[12], 0.001),
            "voltage_l1": main[14],
            "voltage_l2": main[16],
            "voltage_l3": main[18],
            "power": _u32(main, 20),
            "power_l1": _u32(main, 24),
            "power_l2": _u32(main, 28),
            "power_l3": _u32(main, 32),
            "energy_total": _scale(_u32(main, 36), 0.1, 1),
            "hw_max_current": limits[0],
            "hw_min_current": limits[2],
            "cable_max_current": limits[4],
            "session_energy": _u32(session, 0),
            "session_duration": _u32(session, 6),
            "failsafe_current": failsafe[0],
            "failsafe_timeout": failsafe[2],
            "charging_current_setpoint": setpoint[0],
        }


class VestelEntity(CoordinatorEntity[VestelCoordinator]):
    """Gemeinsame Basis aller Vestel-Entities."""

    _attr_has_entity_name = True

    def __init__(
        self, coordinator: VestelCoordinator, description: EntityDescription
    ) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        entry_id = coordinator.config_entry.entry_id
        self._attr_unique_id = f"{entry_id}_{description.key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry_id)},
            name="Vestel Wallbox",
            manufacturer="Vestel",
            model="EVC04",
            serial_number=coordinator.serial_number,
            sw_version=coordinator.firmware,
        )
