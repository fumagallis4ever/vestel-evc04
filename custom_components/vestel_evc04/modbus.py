"""Minimaler Modbus-TCP-Client (nur lesen) für die Vestel EVC04.

Bewusst ohne pymodbus, damit API-Änderungen in Home Assistant
die Integration nicht kaputt machen.
"""

from __future__ import annotations

import asyncio
import logging
import struct

_LOGGER = logging.getLogger(__name__)

FC_READ_HOLDING = 0x03
FC_READ_INPUT = 0x04


class VestelError(Exception):
    """Basisfehler."""


class VestelConnectionError(VestelError):
    """Verbindungs- oder Protokollfehler."""


class VestelModbusException(VestelError):
    """Die Wallbox hat mit einer Modbus-Exception geantwortet."""

    def __init__(self, function: int, address: int, code: int) -> None:
        super().__init__(
            f"Modbus-Exception {code} (Funktion {function}, Register {address})"
        )
        self.code = code


class VestelModbusClient:
    """Hält eine persistente TCP-Verbindung und verbindet bei Fehlern neu."""

    def __init__(
        self, host: str, port: int, unit_id: int, timeout: float = 5.0
    ) -> None:
        self._host = host
        self._port = port
        self._unit_id = unit_id
        self._timeout = timeout
        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None
        self._lock = asyncio.Lock()
        self._tid = 0

    async def _connect(self) -> None:
        self._reader, self._writer = await asyncio.wait_for(
            asyncio.open_connection(self._host, self._port), self._timeout
        )
        _LOGGER.debug("Verbunden mit %s:%s", self._host, self._port)

    async def close(self) -> None:
        """Verbindung schließen."""
        writer = self._writer
        self._reader = None
        self._writer = None
        if writer is not None:
            writer.close()
            try:
                await writer.wait_closed()
            except Exception:  # noqa: BLE001
                pass

    async def read_input(self, address: int, count: int) -> list[int]:
        """Input-Register lesen (Funktion 4)."""
        return await self._read(FC_READ_INPUT, address, count)

    async def read_holding(self, address: int, count: int) -> list[int]:
        """Holding-Register lesen (Funktion 3)."""
        return await self._read(FC_READ_HOLDING, address, count)

    async def _read(self, function: int, address: int, count: int) -> list[int]:
        async with self._lock:
            last_err: Exception | None = None
            for _attempt in range(2):
                try:
                    if self._writer is None:
                        await self._connect()
                    return await asyncio.wait_for(
                        self._transfer(function, address, count), self._timeout
                    )
                except VestelModbusException:
                    raise
                except (
                    OSError,
                    asyncio.TimeoutError,
                    asyncio.IncompleteReadError,
                    VestelConnectionError,
                ) as err:
                    last_err = err
                    await self.close()
            raise VestelConnectionError(
                f"Keine Antwort von {self._host}:{self._port}: {last_err!r}"
            ) from last_err

    async def _transfer(self, function: int, address: int, count: int) -> list[int]:
        assert self._reader is not None and self._writer is not None
        self._tid = (self._tid + 1) & 0xFFFF
        pdu = struct.pack(">BHH", function, address, count)
        mbap = struct.pack(">HHHB", self._tid, 0, len(pdu) + 1, self._unit_id)
        self._writer.write(mbap + pdu)
        await self._writer.drain()

        while True:
            header = await self._reader.readexactly(7)
            tid, proto, length, _unit = struct.unpack(">HHHB", header)
            if proto != 0 or length < 2:
                raise VestelConnectionError("Ungültiger Modbus-Header")
            body = await self._reader.readexactly(length - 1)
            if tid == self._tid:
                break
            _LOGGER.debug("Verwerfe Antwort mit fremder Transaktions-ID %s", tid)

        if body[0] == function | 0x80:
            raise VestelModbusException(function, address, body[1])
        if body[0] != function:
            raise VestelConnectionError(f"Unerwarteter Funktionscode {body[0]}")
        byte_count = body[1]
        if byte_count != count * 2 or len(body) < 2 + byte_count:
            raise VestelConnectionError("Antwortlänge passt nicht")
        return list(struct.unpack(f">{count}H", body[2 : 2 + byte_count]))
