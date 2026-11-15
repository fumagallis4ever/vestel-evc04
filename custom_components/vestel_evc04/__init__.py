"""Vestel EVC04 Wallbox (Modbus TCP, nur lesen) mit Ereignis- und RFID-Protokoll."""

from __future__ import annotations

from homeassistant.const import CONF_HOST, CONF_PORT, Platform
from homeassistant.core import HomeAssistant

from .const import (
    CONF_UNIT_ID,
    CONF_WEB_HOST,
    CONF_WEB_INTERVAL,
    CONF_WEB_PASSWORD,
    CONF_WEB_USER,
    DEFAULT_HOST,
    DEFAULT_WEB_INTERVAL,
    DEFAULT_WEB_USER,
)
from .coordinator import VestelConfigEntry, VestelCoordinator
from .modbus import VestelModbusClient

PLATFORMS = [Platform.SENSOR, Platform.BINARY_SENSOR, Platform.BUTTON]


async def async_setup_entry(hass: HomeAssistant, entry: VestelConfigEntry) -> bool:
    """Integration einrichten."""
    client = VestelModbusClient(
        entry.data[CONF_HOST], entry.data[CONF_PORT], entry.data[CONF_UNIT_ID]
    )
    coordinator = VestelCoordinator(hass, entry, client)
    await coordinator.async_load_log()
    try:
        await coordinator.async_config_entry_first_refresh()
    except Exception:
        await client.close()
        raise
    await coordinator.async_read_device_info()

    entry.runtime_data = coordinator

    # Optional: Weboberfläche für RFID-Nutzungen und Ladevorgänge
    opts = entry.options
    password = opts.get(CONF_WEB_PASSWORD)
    interval = int(opts.get(CONF_WEB_INTERVAL, DEFAULT_WEB_INTERVAL))
    if password and interval > 0:
        from .weblog import VestelWebLog

        coordinator.weblog = VestelWebLog(
            hass,
            coordinator,
            opts.get(CONF_WEB_HOST, DEFAULT_HOST),
            opts.get(CONF_WEB_USER, DEFAULT_WEB_USER),
            password,
            interval,
        )
        coordinator.weblog.start()

    entry.async_on_unload(entry.add_update_listener(_async_reload))
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def _async_reload(hass: HomeAssistant, entry: VestelConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: VestelConfigEntry) -> bool:
    """Integration entladen."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        coordinator = entry.runtime_data
        if coordinator.weblog:
            coordinator.weblog.stop()
        await coordinator.async_save_log()
        await coordinator.client.close()
    return unload_ok
