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


async def async_setup_entry(
    hass: HomeAssistant,
    entry: VestelConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    async_add_entities([VestelClearLogButton(entry.runtime_data, CLEAR_LOG)])


class VestelClearLogButton(VestelEntity, ButtonEntity):
    """Leert das Ereignisprotokoll."""

    @property
    def available(self) -> bool:
        return True

    async def async_press(self) -> None:
        self.coordinator.clear_log()
