"""Buttons der Vestel EVC04."""

from __future__ import annotations

from homeassistant.components.button import ButtonEntity, ButtonEntityDescription
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import VestelConfigEntry, VestelEntity

CLEAR_LOG = ButtonEntityDescription(
    key="clear_log",
    name="Protokoll leeren",
    icon="mdi:delete-sweep",
    entity_category=EntityCategory.CONFIG,
)
FETCH_WEB = ButtonEntityDescription(
    key="fetch_web",
    name="Wallbox-Logs abrufen",
    icon="mdi:cloud-download-outline",
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: VestelConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data
    entities: list[ButtonEntity] = [VestelClearLogButton(coordinator, CLEAR_LOG)]
    if coordinator.weblog:
        entities.append(VestelFetchWebButton(coordinator, FETCH_WEB))
    async_add_entities(entities)


class VestelClearLogButton(VestelEntity, ButtonEntity):
    """Leert das Ereignisprotokoll."""

    @property
    def available(self) -> bool:
        return True

    async def async_press(self) -> None:
        self.coordinator.clear_log()


class VestelFetchWebButton(VestelEntity, ButtonEntity):
    """Ruft Geräte-Logs und Ladevorgänge sofort ab."""

    @property
    def available(self) -> bool:
        return True

    async def async_press(self) -> None:
        await self.coordinator.weblog.async_refresh()
