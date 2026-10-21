"""Diagnostics with personal data and credentials removed."""

from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant

from .const import CONF_CONTRACTS, CONF_NAMES, CONF_PORTAL_URL, CONF_PREFIX
from .coordinator import AareonConfigEntry

TO_REDACT = {
    CONF_PASSWORD,
    CONF_USERNAME,
    CONF_PORTAL_URL,
    CONF_CONTRACTS,
    CONF_PREFIX,
    CONF_NAMES,
}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: AareonConfigEntry
) -> dict[str, Any]:
    """Return redacted entry data and a numeric summary (no names, numbers or addresses)."""
    data = entry.runtime_data.data
    return {
        "entry": async_redact_data(dict(entry.data), TO_REDACT),
        "options": async_redact_data(dict(entry.options), TO_REDACT),
        "last_update": data.last_update.isoformat(),
        "contracts": [
            {
                service: {
                    "months": len(by_period),
                    "first": min(by_period),
                    "last": max(by_period),
                    "estimated_months": sum(v.estimated for v in by_period.values()),
                }
                for service, by_period in contract.months.items()
            }
            for contract in data.contracts.values()
        ],
    }
