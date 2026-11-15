"""Coordinator und Basis-Entity für die Vestel EVC04."""

from __future__ import annotations

from collections import deque
from datetime import datetime, timedelta
import logging
import re
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
    CONF_CARD_NAMES,
    EVENT_NAME,
    LOG_MAX_ENTRIES,
    WEB_SEEN_MAX,
    REG_RFID,
    REG_LOG_MAX,
    REG_NAMES,
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


def parse_card_names(text: str) -> dict[str, str]:
    """'FCF70F46=Michael, DCA1461E=Bea' (Komma oder Zeilen) -> dict."""
    names: dict[str, str] = {}
    for part in re.split(r"[,;\n]", text or ""):
        if "=" in part:
            uid, name = part.split("=", 1)
            if uid.strip() and name.strip():
                names[uid.strip().upper()] = name.strip()
    return names


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
        self.web_seen: deque[str] = deque(maxlen=WEB_SEEN_MAX)
        self.web_status: dict[str, Any] = {"aktiv": False}
        self.sessions: list[dict[str, Any]] = []
        self.weblog: Any = None
        # Rohwerte aller gelesenen Register und Änderungsprotokoll
        self.registers: dict[str, int | None] = {}
        self.reg_log: deque[dict[str, Any]] = deque(maxlen=REG_LOG_MAX)
        self.reg_changes_last_poll = 0
        self.card_names = parse_card_names(entry.options.get(CONF_CARD_NAMES, ""))
        self._store: Store[Any] = Store(
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
    def _store_data(self) -> dict[str, Any]:
        return {"log": list(self.log), "web_seen": list(self.web_seen)}

    async def async_load_log(self) -> None:
        """Gespeichertes Protokoll laden."""
        stored = await self._store.async_load()
        if isinstance(stored, list):  # Format bis 0.2.x
            stored = {"log": stored}
        if not stored:
            return
        self.log.extend(stored.get("log", [])[:LOG_MAX_ENTRIES])
        self.web_seen.extend(stored.get("web_seen", []))
        for entry in self.log:
            if entry.get("typ") == "rfid" and entry.get("details", {}).get("uid"):
                det = entry["details"]
                self.rfid_last = {
                    "uid": det.get("uid"),
                    "name": self.card_names.get(det.get("uid", "")),
                    "ergebnis": det.get("ergebnis"),
                    "quelle": det.get("quelle", "modbus"),
                    "rohdaten_hex": det.get("rohdaten_hex"),
                    "erkannt_um": entry.get("zeit"),
                }
                break

    async def async_save_log(self) -> None:
        """Protokoll sofort speichern."""
        await self._store.async_save(self._store_data())

    def card_label(self, uid: str | None) -> str:
        """Kartenname mit ID, falls hinterlegt."""
        if not uid:
            return "–"
        name = self.card_names.get(uid.upper())
        return f"{name} ({uid})" if name else uid

    @callback
    def add_log(
        self,
        typ: str,
        text: str,
        details: dict[str, Any] | None = None,
        zeit: datetime | None = None,
        notify: bool = True,
    ) -> None:
        """Eintrag hinzufügen, HA-Event feuern und speichern."""
        entry = {
            "zeit": dt_util.as_local(zeit or dt_util.now()).isoformat(
                timespec="seconds"
            ),
            "typ": typ,
            "text": text,
            "details": details or {},
        }
        self.log.appendleft(entry)
        if zeit is not None:  # nachträglich gemeldet -> zeitlich einsortieren
            ordered = sorted(self.log, key=lambda e: e["zeit"], reverse=True)
            self.log.clear()
            self.log.extend(ordered)
        _LOGGER.info("[%s] %s %s", typ, text, details or "")
        self._store.async_delay_save(self._store_data, 5)
        if not notify:  # Sammelimport: kein Event, keine Zustandsänderung je Eintrag
            return
        self.hass.bus.async_fire(
            EVENT_NAME,
            {"entry_id": self.config_entry.entry_id, **entry},
        )
        self.async_update_listeners()

    @callback
    def clear_log(self) -> None:
        """Protokoll leeren."""
        self.log.clear()
        self._store.async_delay_save(self._store_data, 1)
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
                        "name": self.card_names.get(uid.upper()),
                        "ergebnis": "Ladevorgang",
                        "quelle": "modbus",
                        "rohdaten_hex": raw_hex,
                        "erkannt_um": dt_util.now().isoformat(timespec="seconds"),
                    }
                    self.add_log(
                        "rfid",
                        f"RFID-Karte im Ladevorgang: {self.card_label(uid)}",
                        {
                            "uid": uid,
                            "quelle": "modbus",
                            "rohdaten_hex": raw_hex,
                            "register": REG_RFID,
                        },
                    )
            elif not first and old and not uid:
                self.add_log("rfid", "RFID-Register geleert", {"rohdaten_hex": raw_hex})
        return self.rfid_last["uid"] if self.rfid_last else None

    def _track_registers(
        self, blocks: list[tuple[str, int, list[int | None]]]
    ) -> None:
        """Rohwerte merken und jede Änderung protokollieren."""
        now = dt_util.now().isoformat(timespec="seconds")
        first = not self.registers
        changes = 0
        for fc, start, values in blocks:
            for offset, value in enumerate(values):
                reg = start + offset
                key = f"{fc} {reg}"
                old = self.registers.get(key)
                self.registers[key] = value
                if first or old == value:
                    continue
                changes += 1
                self.reg_log.appendleft(
                    {
                        "zeit": now,
                        "art": fc,
                        "register": reg,
                        "name": REG_NAMES.get(reg, "–"),
                        "alt": old,
                        "neu": value,
                    }
                )
        self.reg_changes_last_poll = changes

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

        self._track_registers(
            [
                ("IR", 1000, main),
                ("IR", 1100, limits),
                ("IR", 1502, session),
                ("HR", 2000, failsafe),
                ("HR", 5004, setpoint),
                ("IR", REG_RFID, rfid_regs or []),
            ]
        )
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
