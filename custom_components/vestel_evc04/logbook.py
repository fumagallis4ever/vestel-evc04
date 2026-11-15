"""Ereignisse der Vestel EVC04 im Logbuch anzeigen."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from homeassistant.core import Event, HomeAssistant, callback

from .const import DOMAIN, EVENT_NAME

TYP_LABEL = {
    "rfid": "RFID",
    "ladevorgang": "Ladevorgang",
    "status": "Status",
    "fehler": "Fehler",
    "verbindung": "Verbindung",
    "system": "System",
}


@callback
def async_describe_events(
    hass: HomeAssistant,
    async_describe_event: Callable[[str, str, Callable[[Event], dict[str, Any]]], None],
) -> None:
    """Logbuch-Beschreibung registrieren."""

    @callback
    def describe(event: Event) -> dict[str, Any]:
        data = event.data
        typ = TYP_LABEL.get(data.get("typ"), data.get("typ", ""))
        return {
            "name": f"Vestel Wallbox ({typ})",
            "message": data.get("text", ""),
        }

    async_describe_event(DOMAIN, EVENT_NAME, describe)
