"""Config flow for Gunkly."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any

import probatio
from homeassistant.config_entries import (
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlowWithReload,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
    BooleanSelector,
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)
from yarl import URL

from .api import (
    GunklyAuthError,
    GunklyClient,
    GunklyError,
    TokenInfo,
    normalize_url,
)
from .const import (
    CONF_POLL_INTERVAL,
    CONF_SHOW_LATER,
    CONF_TOKEN,
    CONF_URL,
    DEFAULT_POLL_INTERVAL,
    DEFAULT_SHOW_LATER,
    DOMAIN,
    MAX_POLL_INTERVAL,
    MIN_POLL_INTERVAL,
    SCOPE_READ,
)
from .coordinator import GunklyConfigEntry

_LOGGER = logging.getLogger(__name__)

TOKEN_SELECTOR = TextSelector(TextSelectorConfig(type=TextSelectorType.PASSWORD))


class _FlowError(Exception):
    """A validation error with a translation key for the form."""


async def _validate(hass: HomeAssistant, url: str, token: str) -> TokenInfo:
    """Check the token against the server and return its info."""
    client = GunklyClient(async_get_clientsession(hass), url, token.strip())
    try:
        info = await client.get_token_info()
    except GunklyAuthError as err:
        raise _FlowError("invalid_auth") from err
    except GunklyError as err:
        _LOGGER.debug("Cannot connect to Gunkly: %s", err)
        raise _FlowError("cannot_connect") from err
    if SCOPE_READ not in info.scopes:
        raise _FlowError("missing_scope")
    if not info.households:
        raise _FlowError("no_households")
    return info


def _unique_id(url: str, info: TokenInfo) -> str:
    parsed = URL(url)
    return f"{info.id}@{parsed.host}:{parsed.port}"


class GunklyConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Gunkly."""

    VERSION = 1

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: GunklyConfigEntry) -> GunklyOptionsFlow:
        """Return the options flow."""
        return GunklyOptionsFlow()

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Ask for the server URL and API token."""
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                url = normalize_url(user_input[CONF_URL])
            except ValueError:
                errors["base"] = "invalid_url"
            else:
                try:
                    info = await _validate(self.hass, url, user_input[CONF_TOKEN])
                except _FlowError as err:
                    errors["base"] = str(err)
                else:
                    await self.async_set_unique_id(_unique_id(url, info))
                    self._abort_if_unique_id_configured()
                    return self.async_create_entry(
                        title=f"Gunkly ({info.user_name or info.name} @ {URL(url).host})",
                        data={CONF_URL: url, CONF_TOKEN: user_input[CONF_TOKEN].strip()},
                    )
        return self.async_show_form(
            step_id="user",
            data_schema=self.add_suggested_values_to_schema(
                probatio.Schema(
                    {
                        probatio.Required(CONF_URL): TextSelector(
                            TextSelectorConfig(type=TextSelectorType.URL)
                        ),
                        probatio.Required(CONF_TOKEN): TOKEN_SELECTOR,
                    }
                ),
                user_input,
            ),
            description_placeholders={"example_url": "https://gunkly.example.com"},
            errors=errors,
        )

    async def async_step_reauth(self, entry_data: Mapping[str, Any]) -> ConfigFlowResult:
        """Start reauthentication after the token was rejected."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask for a new token for the same server."""
        errors: dict[str, str] = {}
        entry = self._get_reauth_entry()
        if user_input is not None:
            token = user_input[CONF_TOKEN].strip()
            try:
                info = await _validate(self.hass, entry.data[CONF_URL], token)
            except _FlowError as err:
                errors["base"] = str(err)
            else:
                # A replacement token has a new id, so the unique id changes too.
                unique_id = _unique_id(entry.data[CONF_URL], info)
                other = self.hass.config_entries.async_entry_for_domain_unique_id(DOMAIN, unique_id)
                if other is not None and other.entry_id != entry.entry_id:
                    return self.async_abort(reason="already_configured")
                return self.async_update_reload_and_abort(
                    entry, unique_id=unique_id, data_updates={CONF_TOKEN: token}
                )
        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=probatio.Schema({probatio.Required(CONF_TOKEN): TOKEN_SELECTOR}),
            description_placeholders={"url": entry.data[CONF_URL]},
            errors=errors,
        )


class GunklyOptionsFlow(OptionsFlowWithReload):
    """Options: polling interval and whether to list later chores."""

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Manage the options."""
        if user_input is not None:
            return self.async_create_entry(data=user_input)
        return self.async_show_form(
            step_id="init",
            data_schema=self.add_suggested_values_to_schema(
                probatio.Schema(
                    {
                        probatio.Required(
                            CONF_POLL_INTERVAL, default=DEFAULT_POLL_INTERVAL
                        ): NumberSelector(
                            NumberSelectorConfig(
                                min=MIN_POLL_INTERVAL,
                                max=MAX_POLL_INTERVAL,
                                step=1,
                                unit_of_measurement="s",
                                mode=NumberSelectorMode.BOX,
                            )
                        ),
                        probatio.Required(
                            CONF_SHOW_LATER, default=DEFAULT_SHOW_LATER
                        ): BooleanSelector(),
                    }
                ),
                self.config_entry.options,
            ),
        )
