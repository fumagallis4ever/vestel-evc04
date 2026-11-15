"""Regelmäßiger Abruf von Kartennutzungen und Ladevorgängen über die Weboberfläche."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
import logging
from typing import Any

import aiohttp

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.aiohttp_client import async_create_clientsession
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.util import dt as dt_util

from .const import RFID_RESULT
from .coordinator import VestelCoordinator
from .web import VestelWebAuthError, VestelWebClient, VestelWebError, parse_device_logs

_LOGGER = logging.getLogger(__name__)


class VestelWebLog:
    """Holt Geräte-Logs und Ladevorgänge und schreibt sie ins Protokoll."""

    def __init__(
        self,
        hass: HomeAssistant,
        coordinator: VestelCoordinator,
        host: str,
        username: str,
        password: str,
        interval_min: int,
    ) -> None:
        self.hass = hass
        self.coordinator = coordinator
        self.interval = timedelta(minutes=interval_min)
        session = async_create_clientsession(
            hass, cookie_jar=aiohttp.CookieJar(unsafe=True)
        )
        self.client = VestelWebClient(session, host, username, password)
        self._unsub: Callable[[], None] | None = None
        self._running = False
        self._error_logged = False

    @callback
    def start(self) -> None:
        self.coordinator.web_status = {"aktiv": True, "intervall_min": int(
            self.interval.total_seconds() // 60
        )}
        self._unsub = async_track_time_interval(
            self.hass, self._tick, self.interval, name="Vestel Weboberfläche"
        )
        self.hass.async_create_background_task(
            self.async_refresh(), "vestel_evc04_web_first"
        )

    @callback
    def stop(self) -> None:
        if self._unsub:
            self._unsub()
            self._unsub = None

    async def _tick(self, _now: datetime) -> None:
        await self.async_refresh()

    async def async_refresh(self) -> None:
        """Einmal Logs und Ladevorgänge abrufen."""
        if self._running:
            return
        self._running = True
        status = self.coordinator.web_status
        try:
            blob = await self.client.device_logs()
            events = await self.hass.async_add_executor_job(parse_device_logs, blob)
            self._handle_events(events)
            try:
                self._handle_sessions(await self.client.charge_sessions())
            except VestelWebError as err:
                _LOGGER.debug("Ladevorgänge nicht lesbar: %s", err)
            status.update(
                letzter_abruf=dt_util.now().isoformat(timespec="seconds"),
                letzter_fehler=None,
                log_groesse_kb=round(len(blob) / 1024),
            )
            if self._error_logged:
                self.coordinator.add_log("verbindung", "Weboberfläche wieder erreichbar")
                self._error_logged = False
        except VestelWebAuthError as err:
            status["letzter_fehler"] = str(err)
            if not self._error_logged:
                self.coordinator.add_log(
                    "fehler",
                    "Weboberfläche: Anmeldung fehlgeschlagen – Benutzer/Passwort in den "
                    "Optionen prüfen",
                )
                self._error_logged = True
        except (VestelWebError, Exception) as err:  # noqa: BLE001
            status["letzter_fehler"] = str(err)
            if not self._error_logged:
                self.coordinator.add_log(
                    "verbindung", "Weboberfläche nicht erreichbar", {"fehler": str(err)}
                )
                self._error_logged = True
            _LOGGER.debug("Weboberfläche: %s", err, exc_info=True)
        finally:
            self._running = False
            self.coordinator.async_update_listeners()

    def _handle_events(self, events: list) -> None:
        """Neue Kartennutzungen übernehmen.

        Beim ersten Abruf (Altbestand aus den Logs) wird gesammelt importiert:
        keine Events, kein Zustandswechsel je Eintrag, nur der neueste zählt.
        """
        coord = self.coordinator
        first_run = not coord.web_seen
        new = [ev for ev in events if ev.key not in coord.web_seen]
        for ev in new:
            coord.web_seen.append(ev.key)
            ergebnis = RFID_RESULT.get(ev.ergebnis, ev.ergebnis)
            coord.add_log(
                "rfid",
                f"RFID-Karte {coord.card_label(ev.uid)}: {ergebnis}",
                {"uid": ev.uid, "ergebnis": ev.ergebnis, "quelle": "weboberflaeche"},
                zeit=ev.zeit,
                notify=not first_run,
            )
        latest = next((ev for ev in reversed(new) if not ev.abgelaufen), None)
        if latest is None:
            return
        zeit = dt_util.as_local(latest.zeit).isoformat(timespec="seconds")
        if coord.rfid_last and (coord.rfid_last.get("erkannt_um") or "") > zeit:
            return
        coord.rfid_last = {
            "uid": latest.uid,
            "name": coord.card_names.get(latest.uid),
            "ergebnis": RFID_RESULT.get(latest.ergebnis, latest.ergebnis),
            "quelle": "weboberflaeche",
            "rohdaten_hex": None,
            "erkannt_um": zeit,
        }
        if first_run:
            _LOGGER.info("%s Kartennutzungen aus den Geräte-Logs übernommen", len(new))

    def _handle_sessions(self, rows: list[dict[str, Any]]) -> None:
        coord = self.coordinator
        first_sessions = not any(k.startswith("session|") for k in coord.web_seen)
        sessions: list[dict[str, Any]] = []
        for row in rows:
            try:
                start = datetime.fromtimestamp(int(row.get("startTime") or 0), UTC)
                stop_raw = int(row.get("stopTime") or 0)
                stop = datetime.fromtimestamp(stop_raw, UTC) if stop_raw else None
                e0 = float(row.get("initialEnergy") or 0) / 1000
                e1 = float(row.get("lastEnergy") or 0) / 1000
            except (TypeError, ValueError):
                continue
            uid = str(row.get("authorizationUid") or "").upper() or None
            item = {
                "id": row.get("sessionUuid"),
                "karte": uid,
                "name": coord.card_names.get(uid or ""),
                "start": dt_util.as_local(start).isoformat(timespec="seconds"),
                "ende": dt_util.as_local(stop).isoformat(timespec="seconds")
                if stop
                else None,
                "energie_kwh": round(e1 - e0, 3) if e1 >= e0 else None,
                "status": row.get("status"),
            }
            sessions.append(item)
            key = f"session|{item['id']}|{item['ende']}"
            if item["id"] and item["ende"] and key not in coord.web_seen:
                coord.web_seen.append(key)
                coord.add_log(
                    "ladevorgang",
                    f"Ladevorgang abgeschlossen mit {coord.card_label(uid)}: "
                    f"{item['energie_kwh']} kWh",
                    {"karte": uid, "energie_kwh": item["energie_kwh"],
                     "start": item["start"], "quelle": "weboberflaeche"},
                    zeit=stop,
                    notify=not first_sessions,
                )
        coord.sessions = sessions
