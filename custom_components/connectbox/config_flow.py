"""Config flow for the Connectbox integration."""

from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.const import CONF_HOST, CONF_PASSWORD
from homeassistant.core import callback

from .api import (
    ConnectboxApiClient,
    ConnectboxAuthenticationError,
    ConnectboxConnectionError,
)
from .const import DEFAULT_HOST, DEFAULT_SCAN_INTERVAL, DOMAIN, LOGGER

STEP_USER_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_HOST, default=DEFAULT_HOST): str,
        vol.Required(CONF_PASSWORD): str,
    }
)

STEP_REAUTH_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_PASSWORD): str,
    }
)


class ConnectboxConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Connectbox."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle the initial step."""
        errors: dict[str, str] = {}

        if user_input is not None:
            error = await self._async_validate(
                user_input[CONF_HOST], user_input[CONF_PASSWORD]
            )
            if error is None:
                await self.async_set_unique_id(user_input[CONF_HOST])
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title=f"Connectbox ({user_input[CONF_HOST]})",
                    data=user_input,
                )
            errors["base"] = error

        return self.async_show_form(
            step_id="user",
            data_schema=STEP_USER_SCHEMA,
            errors=errors,
        )

    async def async_step_reauth(self, entry_data: dict[str, Any]) -> ConfigFlowResult:
        """Handle reauthentication."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle reauthentication confirmation."""
        errors: dict[str, str] = {}

        if user_input is not None:
            entry = self._get_reauth_entry()
            host = entry.data[CONF_HOST]
            error = await self._async_validate(host, user_input[CONF_PASSWORD])
            if error is None:
                return self.async_update_reload_and_abort(
                    entry,
                    data={**entry.data, CONF_PASSWORD: user_input[CONF_PASSWORD]},
                )
            errors["base"] = error

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=STEP_REAUTH_SCHEMA,
            errors=errors,
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle reconfiguration."""
        errors: dict[str, str] = {}

        if user_input is not None:
            error = await self._async_validate(
                user_input[CONF_HOST], user_input[CONF_PASSWORD]
            )
            if error is None:
                return self.async_update_reload_and_abort(
                    self._get_reconfigure_entry(),
                    data=user_input,
                )
            errors["base"] = error

        entry = self._get_reconfigure_entry()
        return self.async_show_form(
            step_id="reconfigure",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_HOST,
                        default=entry.data.get(CONF_HOST, DEFAULT_HOST),
                    ): str,
                    vol.Required(CONF_PASSWORD): str,
                }
            ),
            errors=errors,
        )

    async def _async_validate(self, host: str, password: str) -> str | None:
        """Validate credentials. Return error key or None on success."""
        client = ConnectboxApiClient(host, password)
        try:
            await client.async_validate_credentials()
        except ConnectboxAuthenticationError:
            return "invalid_auth"
        except ConnectboxConnectionError:
            return "cannot_connect"
        except Exception:
            LOGGER.exception("Unexpected error during validation")
            return "unknown"
        return None

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        """Get the options flow."""
        return ConnectboxOptionsFlow()


class ConnectboxOptionsFlow(OptionsFlow):
    """Handle options for Connectbox."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Manage the options."""
        if user_input is not None:
            return self.async_create_entry(data=user_input)

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Optional(
                        "scan_interval",
                        default=self.config_entry.options.get(
                            "scan_interval", DEFAULT_SCAN_INTERVAL
                        ),
                    ): vol.All(vol.Coerce(int), vol.Range(min=30, max=3600)),
                }
            ),
        )
