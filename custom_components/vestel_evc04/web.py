"""Zugriff auf die Weboberfläche ("webconfig") der Vestel EVC04.

Modbus liefert die RFID-Karte nur während eines Ladevorgangs. Die
Weboberfläche liefert dagegen
  * die Geräte-Logs (ZIP) mit jeder Kartennutzung inkl. Ergebnis und
  * die Liste der Ladevorgänge (JSON) mit Karte, Zeiten und Energie.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime
import io
import json
import logging
import re
from typing import Any
import zipfile

import aiohttp

_LOGGER = logging.getLogger(__name__)

TIMEOUT = aiohttp.ClientTimeout(total=90)

# 15.11.2026-12:55:25 [DEBUG] RECEIVED: {"type": "Authorize", "idTag": "fcf70f46"}
_LINE_RE = re.compile(
    r"^(\d{2})\.(\d{2})\.(\d{4})-(\d{2}):(\d{2}):(\d{2}) \[\w+\] RECEIVED: (\{.*\})\s*$"
)


class VestelWebError(Exception):
    """Weboberfläche nicht erreichbar oder unerwartete Antwort."""


class VestelWebAuthError(VestelWebError):
    """Benutzername oder Passwort falsch."""


@dataclass(frozen=True)
class RfidEvent:
    """Eine Kartennutzung aus dem Geräte-Log."""

    zeit: datetime
    uid: str
    ergebnis: str  # Accepted, Invalid, Blocked, Expired, ...
    abgelaufen: bool = False  # Freigabe ohne Kabel verfallen

    @property
    def key(self) -> str:
        return f"{self.zeit.isoformat()}|{self.uid}|{self.ergebnis}|{self.abgelaufen}"


def _is_login_page(html: str) -> bool:
    return "button_login" in html


def parse_ui_log(text: str) -> list[RfidEvent]:
    """Kartennutzungen aus ui-*.log lesen (Zeitstempel der Box sind UTC)."""
    events: list[RfidEvent] = []
    pending: tuple[datetime, str] | None = None
    last_accepted: tuple[datetime, str] | None = None
    for line in text.splitlines():
        m = _LINE_RE.match(line)
        if not m:
            continue
        d, mo, y, h, mi, s, payload = m.groups()
        try:
            data = json.loads(payload)
        except ValueError:
            continue
        ts = datetime(int(y), int(mo), int(d), int(h), int(mi), int(s), tzinfo=UTC)
        typ = data.get("type")
        if typ == "Authorize" and data.get("idTag"):
            pending = (ts, str(data["idTag"]).upper())
        elif typ == "AuthorizationResponse":
            status = (data.get("idTagInfo") or {}).get("status", "")
            if status == "Timeout":
                if last_accepted:
                    events.append(
                        RfidEvent(ts, last_accepted[1], "Timeout", abgelaufen=True)
                    )
                    last_accepted = None
                continue
            if pending:
                events.append(RfidEvent(pending[0], pending[1], status))
                if status == "Accepted":
                    last_accepted = pending
                pending = None
    return events


def parse_device_logs(blob: bytes) -> list[RfidEvent]:
    """ZIP der Geräte-Logs auswerten."""
    events: list[RfidEvent] = []
    with zipfile.ZipFile(io.BytesIO(blob)) as zf:
        for name in sorted(zf.namelist()):
            base = name.rsplit("/", 1)[-1]
            if base.startswith("ui-") and base.endswith(".log"):
                text = zf.read(name).decode("utf-8", errors="replace")
                events.extend(parse_ui_log(text))
    events.sort(key=lambda e: e.zeit)
    return events


class VestelWebClient:
    """Login per Formular (PHPSESSID), danach Seiten abrufen."""

    def __init__(
        self, session: aiohttp.ClientSession, host: str, username: str, password: str
    ) -> None:
        self._session = session
        self._base = f"http://{host}"
        self._username = username
        self._password = password
        self._logged_in = False
        self._lock = asyncio.Lock()

    def _headers(self, referer: str = "/") -> dict[str, str]:
        return {
            "User-Agent": "Mozilla/5.0 (HomeAssistant vestel_evc04)",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Origin": self._base,
            "Referer": f"{self._base}{referer}",
        }

    async def login(self) -> None:
        """Wie der Browser: GET /, POST / (Formular), GET / -> 302 index_main.php."""
        steps: list[str] = []
        try:
            async with self._session.get(
                f"{self._base}/", headers=self._headers(), timeout=TIMEOUT
            ) as r:
                await r.read()
                steps.append(f"GET / {r.status}")
            form = {
                "username": self._username,
                "pass": self._password,
                "button_login": "ANMELDEN",
            }
            async with self._session.post(
                f"{self._base}/",
                data=form,
                headers=self._headers(),
                allow_redirects=False,
                timeout=TIMEOUT,
            ) as r:
                await r.read()
                steps.append(f"POST / {r.status} -> {r.headers.get('Location')}")
            async with self._session.get(
                f"{self._base}/",
                headers=self._headers(),
                allow_redirects=False,
                timeout=TIMEOUT,
            ) as r:
                body = await r.text(errors="replace")
                location = r.headers.get("Location", "")
                steps.append(f"GET / {r.status} -> {location}")
            ok = "index_main" in location
            if not ok:
                async with self._session.get(
                    f"{self._base}/index_main.php",
                    headers=self._headers(),
                    allow_redirects=False,
                    timeout=TIMEOUT,
                ) as r:
                    body = await r.text(errors="replace")
                    steps.append(f"GET index_main.php {r.status}")
                    ok = r.status == 200 and not _is_login_page(body)
        except (aiohttp.ClientError, asyncio.TimeoutError) as err:
            raise VestelWebError(f"Weboberfläche nicht erreichbar: {err!r}") from err
        _LOGGER.debug("Login %s: %s", "ok" if ok else "fehlgeschlagen", "; ".join(steps))
        if not ok:
            self._logged_in = False
            raise VestelWebAuthError(
                "Anmeldung fehlgeschlagen (" + "; ".join(steps) + ")"
            )
        self._logged_in = True

    async def _get(self, path: str, params: dict[str, Any] | None = None) -> bytes:
        async with self._lock:
            for attempt in range(2):
                if not self._logged_in:
                    await self.login()
                try:
                    async with self._session.get(
                        f"{self._base}/{path}",
                        params=params,
                        headers=self._headers("/index_main.php"),
                        timeout=TIMEOUT,
                    ) as r:
                        body = await r.read()
                        ctype = r.headers.get("Content-Type", "")
                except (aiohttp.ClientError, asyncio.TimeoutError) as err:
                    raise VestelWebError(f"{path}: {err}") from err
                looks_html = "html" in ctype or body[:200].lstrip().startswith(b"<")
                expired = body.strip() == b"session_expired" or (
                    looks_html and b"button_login" in body
                )
                if expired and attempt == 0:
                    self._logged_in = False
                    continue
                if expired:
                    raise VestelWebAuthError("Sitzung abgelaufen, Login fehlgeschlagen")
                return body
        raise VestelWebError(path)

    async def device_logs(self) -> bytes:
        """Geräte-Logs als ZIP (die Box packt sie bei jedem Abruf neu)."""
        blob = await self._get("downloadDeviceLogs.php")
        if not blob.startswith(b"PK"):
            raise VestelWebError("Geräte-Logs: keine ZIP-Datei erhalten")
        return blob

    async def charge_sessions(self, page: int = 1) -> list[dict[str, Any]]:
        """Ladevorgänge (neueste Seite) als Liste."""
        raw = await self._get("query_chargeSession.php", {"page": page})
        try:
            data = json.loads(raw.decode("utf-8", errors="replace"))
        except ValueError as err:
            raise VestelWebError("Ladevorgänge: keine JSON-Antwort") from err
        rows = data.get("data") if isinstance(data, dict) else data
        return rows if isinstance(rows, list) else []
