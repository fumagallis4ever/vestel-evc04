"""Config-Flow für die Vestel EVC04."""

from __future__ import annotations

import logging
from typing import Any

import aiohttp
import voluptuous as vol

from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.core import callback
from homeassistant.const import CONF_HOST, CONF_PORT, CONF_SCAN_INTERVAL
from homeassistant.helpers.selector import (
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)

from .const import (
    CONF_CARD_NAMES,
    CONF_UNIT_ID,
    CONF_WEB_HOST,
    CONF_WEB_INTERVAL,
    CONF_WEB_PASSWORD,
    CONF_WEB_USER,
    DEFAULT_WEB_INTERVAL,
    DEFAULT_WEB_USER,
    DEFAULT_HOST,
    DEFAULT_PORT,
    DEFAULT_SCAN_INTERVAL,
    DEFAULT_UNIT_ID,
    DOMAIN,
)
from .modbus import VestelError, VestelModbusClient
from .web import VestelWebAuthError, VestelWebClient, VestelWebError

_LOGGER = logging.getLogger(__name__)

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

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> VestelOptionsFlow:
        return VestelOptionsFlow()

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


class VestelOptionsFlow(OptionsFlow):
    """Optionen: Weboberfläche der Wallbox und Kartennamen."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        opts = self.config_entry.options
        if user_input is not None:
            user_input[CONF_WEB_INTERVAL] = int(user_input[CONF_WEB_INTERVAL])
            if not user_input.get(CONF_WEB_PASSWORD):
                # leeres Feld = bisheriges Passwort behalten
                user_input[CONF_WEB_PASSWORD] = opts.get(CONF_WEB_PASSWORD, "")
            if user_input[CONF_WEB_PASSWORD] and user_input[CONF_WEB_INTERVAL] > 0:
                session = aiohttp.ClientSession(
                    cookie_jar=aiohttp.CookieJar(unsafe=True)
                )
                client = VestelWebClient(
                    session,
                    user_input[CONF_WEB_HOST].strip(),
                    user_input[CONF_WEB_USER].strip(),
                    user_input[CONF_WEB_PASSWORD],
                )
                try:
                    await client.login()
                except VestelWebAuthError as err:
                    _LOGGER.warning("Weboberfläche: %s", err)
                    errors["base"] = "web_auth"
                except VestelWebError as err:
                    _LOGGER.warning("Weboberfläche: %s", err)
                    errors["base"] = "web_connect"
                finally:
                    await session.close()
            if not errors:
                return self.async_create_entry(data=user_input)

        schema = vol.Schema(
            {
                vol.Required(
                    CONF_WEB_HOST, default=opts.get(CONF_WEB_HOST, DEFAULT_HOST)
                ): str,
                vol.Required(
                    CONF_WEB_USER, default=opts.get(CONF_WEB_USER, DEFAULT_WEB_USER)
                ): str,
                vol.Optional(CONF_WEB_PASSWORD, default=""): TextSelector(
                    TextSelectorConfig(type=TextSelectorType.PASSWORD)
                ),
                vol.Required(
                    CONF_WEB_INTERVAL,
                    default=opts.get(CONF_WEB_INTERVAL, DEFAULT_WEB_INTERVAL),
                ): _box(0, 60),
                vol.Optional(
                    CONF_CARD_NAMES, default=opts.get(CONF_CARD_NAMES, "")
                ): TextSelector(TextSelectorConfig(multiline=True)),
            }
        )
        return self.async_show_form(step_id="init", data_schema=schema, errors=errors)
