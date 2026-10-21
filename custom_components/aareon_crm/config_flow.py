"""Config, reauth and options flow."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from datetime import date
from typing import Any
from urllib.parse import urlparse

import voluptuous as vol
from homeassistant.config_entries import (
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlowWithReload,
)
from homeassistant.const import CONF_NAME, CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_create_clientsession
from homeassistant.helpers.selector import (
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
)

from .api import (
    AareonApiError,
    AareonAuthError,
    AareonClient,
    AareonConnectionError,
    normalize_base_url,
)
from .const import (
    CONF_CONTRACTS,
    CONF_NAMES,
    CONF_PORTAL_URL,
    CONF_PREFIX,
    DEFAULT_PORTAL_URL,
    DOMAIN,
    HISTORY_START,
)
from .naming import suggest_contract_name, suggest_prefix
from .statistics import parse_consumption

_LOGGER = logging.getLogger(__name__)


async def _fetch_contract_options(
    client: AareonClient,
) -> tuple[list[SelectOptionDict], list[str], list[dict[str, Any]]]:
    """Log in, list contracts; return (options, references with data, raw contracts)."""
    await client.async_login()
    try:
        contracts = await client.async_get_contracts()
        options: list[SelectOptionDict] = []
        with_data: list[str] = []
        for contract in contracts:
            reference = contract["reference"]
            name = contract.get("subLabel") or contract.get("label")
            options.append(
                SelectOptionDict(value=reference, label=f"{contract.get('number')} - {name}")
            )
            results = await client.async_get_consumption(
                reference, date.fromisoformat(HISTORY_START), date.today()
            )
            if parse_consumption(results):
                with_data.append(reference)
        return options, with_data, contracts
    finally:
        await client.async_logout()


def _error_key(err: Exception) -> str:
    if isinstance(err, AareonAuthError):
        return "invalid_auth"
    if isinstance(err, AareonConnectionError):
        return "cannot_connect"
    return "unknown"


class _NamingSteps:
    """Shared steps: choose contracts + prefix, then name each contract."""

    hass: Any
    _portal_host: str
    _contracts: list[dict[str, Any]]
    _options: list[SelectOptionDict]
    _defaults: list[str]
    _saved_prefix: str | None = None
    _saved_names: dict[str, str]

    def _init_naming(self) -> None:
        self._saved_names = {}
        self._selected: list[str] = []
        self._prefix = ""
        self._names: dict[str, str] = {}
        self._queue: list[str] = []

    def _default_prefix(self) -> str:
        if self._saved_prefix is not None:
            return self._saved_prefix
        company = next((c.get("companyName") for c in self._contracts), None)
        return suggest_prefix(company, self._portal_host)

    def _contract(self, reference: str) -> dict[str, Any]:
        return next(c for c in self._contracts if c["reference"] == reference)

    def _show_contracts(self, step_id: str, errors: dict[str, str]) -> ConfigFlowResult:
        return self.async_show_form(  # type: ignore[attr-defined]
            step_id=step_id,
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_CONTRACTS, default=self._defaults): SelectSelector(
                        SelectSelectorConfig(options=self._options, multiple=True)
                    ),
                    vol.Optional(CONF_PREFIX, default=self._default_prefix()): str,
                }
            ),
            errors=errors,
        )

    async def _handle_contracts(self, step_id: str, user_input: dict[str, Any]) -> ConfigFlowResult:
        if not user_input[CONF_CONTRACTS]:
            return self._show_contracts(step_id, {"base": "no_contracts"})
        self._selected = list(user_input[CONF_CONTRACTS])
        self._prefix = user_input.get(CONF_PREFIX, "").strip()
        self._queue = list(self._selected)
        self._names = {}
        return await self.async_step_name()

    async def async_step_name(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Ask for the display name of the next contract."""
        if user_input is not None:
            reference = self._queue.pop(0)
            self._names[reference] = user_input[CONF_NAME].strip()
        if not self._queue:
            return await self._finish()
        contract = self._contract(self._queue[0])
        default = self._saved_names.get(contract["reference"]) or suggest_contract_name(contract)
        return self.async_show_form(  # type: ignore[attr-defined]
            step_id="name",
            data_schema=vol.Schema({vol.Required(CONF_NAME, default=default): str}),
            description_placeholders={
                "contract": f"{contract.get('number')} - "
                f"{contract.get('subLabel') or contract.get('label')}"
            },
        )

    async def _finish(self) -> ConfigFlowResult:
        raise NotImplementedError

    def _entry_options(self) -> dict[str, Any]:
        return {
            CONF_CONTRACTS: self._selected,
            CONF_PREFIX: self._prefix,
            CONF_NAMES: self._names,
        }


class AareonConfigFlow(_NamingSteps, ConfigFlow, domain=DOMAIN):
    """Handle the setup of one portal account."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialize flow state."""
        self._data: dict[str, Any] = {}
        self._options: list[SelectOptionDict] = []
        self._defaults: list[str] = []
        self._contracts: list[dict[str, Any]] = []
        self._portal_host = ""
        self._init_naming()

    @staticmethod
    @callback
    def async_get_options_flow(config_entry) -> AareonOptionsFlow:
        """Return the options flow."""
        return AareonOptionsFlow()

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Ask for portal URL and credentials."""
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                url = normalize_base_url(user_input[CONF_PORTAL_URL])
            except ValueError:
                errors[CONF_PORTAL_URL] = "invalid_url"
            else:
                await self.async_set_unique_id(
                    f"{urlparse(url).netloc}_{user_input[CONF_USERNAME].strip().lower()}"
                )
                self._abort_if_unique_id_configured()
                client = AareonClient(
                    async_create_clientsession(self.hass),
                    url,
                    user_input[CONF_USERNAME],
                    user_input[CONF_PASSWORD],
                )
                try:
                    (
                        self._options,
                        self._defaults,
                        self._contracts,
                    ) = await _fetch_contract_options(client)
                except (AareonApiError, AareonAuthError, AareonConnectionError) as err:
                    errors["base"] = _error_key(err)
                else:
                    self._data = {**user_input, CONF_PORTAL_URL: url}
                    self._portal_host = urlparse(url).hostname or ""
                    return await self.async_step_contracts()
        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_PORTAL_URL,
                        default=(user_input or {}).get(CONF_PORTAL_URL, DEFAULT_PORTAL_URL),
                    ): str,
                    vol.Required(
                        CONF_USERNAME, default=(user_input or {}).get(CONF_USERNAME, "")
                    ): str,
                    vol.Required(CONF_PASSWORD): str,
                }
            ),
            errors=errors,
        )

    async def async_step_contracts(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Pick the contracts to import and the device name prefix."""
        if user_input is not None:
            return await self._handle_contracts("contracts", user_input)
        return self._show_contracts("contracts", {})

    async def _finish(self) -> ConfigFlowResult:
        return self.async_create_entry(
            title=self._portal_host, data=self._data, options=self._entry_options()
        )

    async def async_step_reauth(self, entry_data: Mapping[str, Any]) -> ConfigFlowResult:
        """Start reauthentication after a failed login."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask for a new password."""
        entry = self._get_reauth_entry()
        errors: dict[str, str] = {}
        if user_input is not None:
            client = AareonClient(
                async_create_clientsession(self.hass),
                entry.data[CONF_PORTAL_URL],
                entry.data[CONF_USERNAME],
                user_input[CONF_PASSWORD],
            )
            try:
                await client.async_login()
                await client.async_logout()
            except (AareonApiError, AareonAuthError, AareonConnectionError) as err:
                errors["base"] = _error_key(err)
            else:
                return self.async_update_reload_and_abort(
                    entry, data_updates={CONF_PASSWORD: user_input[CONF_PASSWORD]}
                )
        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema({vol.Required(CONF_PASSWORD): str}),
            description_placeholders={CONF_USERNAME: entry.data[CONF_USERNAME]},
            errors=errors,
        )


class AareonOptionsFlow(_NamingSteps, OptionsFlowWithReload):
    """Change imported contracts, device name prefix and contract names."""

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Show the contract list of the portal."""
        if user_input is not None:
            return await self._handle_contracts("init", user_input)
        entry = self.config_entry
        client = AareonClient(
            async_create_clientsession(self.hass),
            entry.data[CONF_PORTAL_URL],
            entry.data[CONF_USERNAME],
            entry.data[CONF_PASSWORD],
        )
        try:
            self._options, _, self._contracts = await _fetch_contract_options(client)
        except (AareonApiError, AareonAuthError, AareonConnectionError) as err:
            return self.async_abort(reason=_error_key(err))
        self._init_naming()
        self._portal_host = urlparse(entry.data[CONF_PORTAL_URL]).hostname or ""
        self._defaults = entry.options.get(CONF_CONTRACTS, [])
        self._saved_prefix = entry.options.get(CONF_PREFIX)
        self._saved_names = entry.options.get(CONF_NAMES, {})
        return self._show_contracts("init", {})

    async def _finish(self) -> ConfigFlowResult:
        return self.async_create_entry(data=self._entry_options())
