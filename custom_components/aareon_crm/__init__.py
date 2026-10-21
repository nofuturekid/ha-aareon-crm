"""Aareon Mieterportal: import Techem consumption as long-term statistics."""

from __future__ import annotations

from homeassistant.const import Platform
from homeassistant.core import HomeAssistant

from .coordinator import AareonConfigEntry, AareonCoordinator

PLATFORMS = [Platform.SENSOR]


async def async_setup_entry(hass: HomeAssistant, entry: AareonConfigEntry) -> bool:
    """Set up a portal account."""
    coordinator = AareonCoordinator(hass, entry)
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: AareonConfigEntry) -> bool:
    """Unload a portal account."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
