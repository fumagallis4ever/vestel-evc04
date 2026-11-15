"""Config-Flow für die Vestel EVC04."""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.const import CONF_HOST, CONF_PORT, CONF_SCAN_INTERVAL
from homeassistant.helpers.selector import (
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
)

from .const import (
    CONF_UNIT_ID,
    DEFAULT_HOST,
    DEFAULT_PORT,
    DEFAULT_SCAN_INTERVAL,
    DEFAULT_UNIT_ID,
    DOMAIN,
)
from .modbus import VestelError, VestelModbusClient

def _box(minimum: int, maximum: int) -> NumberSelector:
    """Zahlenfeld statt Schieberegler."""
    return NumberSelector(
        NumberSelectorConfig(
            min=minimum, max=maximum, step=1, mode=NumberSelectorMode.BOX
        )
    )


SCHEMA = vol.Schema(
    {
        vol.Required(CONF_HOST, default=DEFAULT_HOST): str,
        vol.Required(CONF_PORT, default=DEFAULT_PORT): _box(1, 65535),
        vol.Required(CONF_UNIT_ID, default=DEFAULT_UNIT_ID): _box(0, 255),
        vol.Required(CONF_SCAN_INTERVAL, default=DEFAULT_SCAN_INTERVAL): _box(
            5, 300
        ),
    }
)

INT_KEYS = (CONF_PORT, CONF_UNIT_ID, CONF_SCAN_INTERVAL)


class VestelConfigFlow(ConfigFlow, domain=DOMAIN):
    """Einrichtung über die Oberfläche."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            user_input = {
                **user_input,
                **{k: int(user_input[k]) for k in INT_KEYS},
            }
            host = user_input[CONF_HOST].strip()
            port = user_input[CONF_PORT]
            await self.async_set_unique_id(f"{host}:{port}")
            self._abort_if_unique_id_configured()

            client = VestelModbusClient(host, port, user_input[CONF_UNIT_ID])
            try:
                await client.read_input(1000, 1)
            except VestelError:
                errors["base"] = "cannot_connect"
            finally:
                await client.close()

            if not errors:
                return self.async_create_entry(
                    title=f"Vestel Wallbox ({host})",
                    data={**user_input, CONF_HOST: host},
                )

        return self.async_show_form(
            step_id="user",
            data_schema=self.add_suggested_values_to_schema(SCHEMA, user_input)
            if user_input
            else SCHEMA,
            errors=errors,
        )
