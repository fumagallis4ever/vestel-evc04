"""Coordinator und Basis-Entity für die Vestel EVC04."""

from __future__ import annotations

from collections import deque
from datetime import timedelta
import logging
import time
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_SCAN_INTERVAL
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util
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
    EVENT_NAME,
    LOG_MAX_ENTRIES,
    REG_RFID,
    REG_RFID_COUNT,
    STORAGE_VERSION,
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


def _decode_text(regs: list[int]) -> str:
    """UTF-16BE (ein Zeichen je Register) bzw. ASCII-Paare dekodieren."""
    raw = b"".join(r.to_bytes(2, "big") for r in regs)
    if all(r < 0x100 for r in regs):
        text = "".join(chr(r) for r in regs if r)
    else:
        text = raw.replace(b"\x00", b"").decode("latin-1", errors="ignore")
    return "".join(c for c in text if c.isprintable()).strip()


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

        # Ereignisprotokoll (neueste zuerst), wird über Neustarts gespeichert
        self.log: deque[dict[str, Any]] = deque(maxlen=LOG_MAX_ENTRIES)
        self._store: Store[list[dict[str, Any]]] = Store(
            hass, STORAGE_VERSION, f"{DOMAIN}.{entry.entry_id}.protokoll"
        )
        self._prev: dict[str, Any] = {}
        self._online: bool | None = None
        self.rfid_supported: bool | None = None
        self.rfid_last: dict[str, Any] | None = None
        self.rfid_raw_hex: str | None = None

        # Kommunikationsstatistik
        self.comm: dict[str, Any] = {
            "abfragen": 0,
            "fehler": 0,
            "letzte_abfrage": None,
            "dauer_ms": None,
            "letzter_fehler": None,
            "letzter_fehler_um": None,
        }

    # ------------------------------------------------------------------
    # Protokoll
    # ------------------------------------------------------------------
    async def async_load_log(self) -> None:
        """Gespeichertes Protokoll laden."""
        stored = await self._store.async_load()
        if stored:
            self.log.extend(stored[:LOG_MAX_ENTRIES])
            for entry in stored:
                if entry.get("typ") == "rfid" and self.rfid_last is None:
                    self.rfid_last = {
                        "uid": entry.get("details", {}).get("uid"),
                        "rohdaten_hex": entry.get("details", {}).get("rohdaten_hex"),
                        "erkannt_um": entry.get("zeit"),
                    }

    async def async_save_log(self) -> None:
        """Protokoll sofort speichern."""
        await self._store.async_save(list(self.log))

    @callback
    def add_log(
        self, typ: str, text: str, details: dict[str, Any] | None = None
    ) -> None:
        """Eintrag hinzufügen, HA-Event feuern und speichern."""
        entry = {
            "zeit": dt_util.now().isoformat(timespec="seconds"),
            "typ": typ,
            "text": text,
            "details": details or {},
        }
        self.log.appendleft(entry)
        _LOGGER.info("[%s] %s %s", typ, text, details or "")
        self.hass.bus.async_fire(
            EVENT_NAME,
            {"entry_id": self.config_entry.entry_id, **entry},
        )
        self._store.async_delay_save(lambda: list(self.log), 5)
        self.async_update_listeners()

    @callback
    def clear_log(self) -> None:
        """Protokoll leeren."""
        self.log.clear()
        self._store.async_delay_save(lambda: list(self.log), 1)
        self.add_log("system", "Protokoll geleert")

    def _track(self, key: str, value: Any, label: str, typ: str = "status") -> None:
        """Änderung eines Werts protokollieren."""
        old = self._prev.get(key, value)
        self._prev[key] = value
        if old != value and value is not None:
            self.add_log(typ, f"{label}: {old} → {value}", {"alt": old, "neu": value})

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

    async def _read_rfid(self) -> list[int] | None:
        """RFID-Register lesen; ältere Firmware lehnt ab -> None."""
        if self.rfid_supported is False:
            return None
        try:
            regs = await self.client.read_input(REG_RFID, REG_RFID_COUNT)
        except VestelModbusException as err:
            self.rfid_supported = False
            self.add_log(
                "rfid",
                "RFID-Register wird von der Firmware nicht unterstützt "
                "(benötigt ≥ 3.156)",
                {"fehler": str(err)},
            )
            return None
        if self.rfid_supported is None:
            self.rfid_supported = True
        return regs

    def _handle_rfid(self, regs: list[int] | None) -> str | None:
        """RFID auswerten und Änderungen protokollieren."""
        if regs is not None:
            uid = _decode_text(regs) or None
            raw_hex = " ".join(f"{r:04X}" for r in regs)
            self.rfid_raw_hex = raw_hex
            first = "rfid" not in self._prev
            old = self._prev.get("rfid")
            self._prev["rfid"] = uid
            if uid and uid != old:
                already_known = (
                    first
                    and self.rfid_last is not None
                    and self.rfid_last.get("uid") == uid
                )
                if not already_known:
                    self.rfid_last = {
                        "uid": uid,
                        "rohdaten_hex": raw_hex,
                        "erkannt_um": dt_util.now().isoformat(timespec="seconds"),
                    }
                    self.add_log(
                        "rfid",
                        f"RFID-Karte erkannt: {uid}",
                        {"uid": uid, "rohdaten_hex": raw_hex, "register": REG_RFID},
                    )
            elif not first and old and not uid:
                self.add_log("rfid", "RFID-Register geleert", {"rohdaten_hex": raw_hex})
        return self.rfid_last["uid"] if self.rfid_last else None

    async def _async_update_data(self) -> dict[str, Any]:
        started = time.monotonic()
        self.comm["abfragen"] += 1
        try:
            main = await self._read_block(FC_READ_INPUT, 1000, 38)
            limits = await self._read_block(FC_READ_INPUT, 1100, 5)
            session = await self._read_block(FC_READ_INPUT, 1502, 8)
            failsafe = await self._read_block(FC_READ_HOLDING, 2000, 3)
            setpoint = await self._read_block(FC_READ_HOLDING, 5004, 1)
            rfid_regs = await self._read_rfid()
        except VestelError as err:
            self.comm["fehler"] += 1
            self.comm["letzter_fehler"] = str(err)
            self.comm["letzter_fehler_um"] = dt_util.now().isoformat(
                timespec="seconds"
            )
            if self._online is not False:
                self._online = False
                self.add_log("verbindung", "Verbindung zur Wallbox verloren",
                             {"fehler": str(err)})
            raise UpdateFailed(f"Vestel Wallbox nicht erreichbar: {err}") from err

        self.comm["dauer_ms"] = round((time.monotonic() - started) * 1000)
        self.comm["letzte_abfrage"] = dt_util.now().isoformat(timespec="seconds")
        if self._online is not True:
            self.add_log(
                "verbindung",
                "Verbindung hergestellt"
                if self._online is None
                else "Verbindung wiederhergestellt",
                {"dauer_ms": self.comm["dauer_ms"]},
            )
            self._online = True

        cp_raw, chg_raw, eq_raw, cable_raw = main[0], main[1], main[2], main[4]

        self._track("chargepoint", CHARGEPOINT_STATE.get(cp_raw, cp_raw), "Ladepunkt")
        self._track("cable", CABLE_STATE.get(cable_raw, cable_raw), "Kabel")
        self._track("equipment", EQUIPMENT_STATE.get(eq_raw, eq_raw), "Gerät")
        self._track("fault", main[6], "Fehlercode", "fehler")
        self._track("setpoint", setpoint[0], "Ladestromvorgabe (A)")

        rfid = self._handle_rfid(rfid_regs)

        was_charging = self._prev.get("charging")
        charging = chg_raw == 1 if chg_raw is not None else None
        self._prev["charging"] = charging
        if was_charging is False and charging:
            self.add_log("ladevorgang", "Ladevorgang gestartet",
                         {"rfid": self.rfid_last["uid"] if self.rfid_last else None})
        elif was_charging and charging is False:
            self.add_log(
                "ladevorgang",
                "Ladevorgang beendet",
                {
                    "energie_wh": _u32(session, 0),
                    "dauer_s": _u32(session, 6),
                },
            )

        return {
            "rfid": rfid,
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
