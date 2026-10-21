"""Setup, coordinator, sensors, statistics import, diagnostics."""

from __future__ import annotations

from unittest.mock import patch

from homeassistant.components.diagnostics import REDACTED
from homeassistant.config_entries import ConfigEntryState
from homeassistant.helpers import issue_registry as ir
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.components.diagnostics import (
    get_diagnostics_for_config_entry,
)

from custom_components.aareon_crm.const import (
    CONF_CONTRACTS,
    CONF_NAMES,
    CONF_PREFIX,
    DOMAIN,
)

from .conftest import FLAT_REF, mock_portal

STATS = "custom_components.aareon_crm.coordinator.async_add_external_statistics"


async def test_setup_imports_statistics_and_creates_sensors(
    hass, aioclient_mock, mock_entry: MockConfigEntry, freezer
):
    freezer.move_to("2026-10-20 12:00:00+02:00")
    mock_portal(aioclient_mock)
    mock_entry.add_to_hass(hass)
    with patch(STATS) as add_stats:
        await hass.config_entries.async_setup(mock_entry.entry_id)
        await hass.async_block_till_done()
    assert mock_entry.state is ConfigEntryState.LOADED

    imported = {c.args[1]["statistic_id"]: c for c in add_stats.call_args_list}
    assert set(imported) == {
        "aareon_crm:10001_heating",
        "aareon_crm:10001_heating_standardized",
        "aareon_crm:10001_hot_water",
        "aareon_crm:10001_hot_water_standardized",
        "aareon_crm:10002_heating",
        "aareon_crm:10002_heating_standardized",
    }
    meta = imported["aareon_crm:10001_heating"].args[1]
    assert meta["source"] == DOMAIN and meta["has_sum"] and meta["unit_of_measurement"] == "kWh"
    assert len(imported["aareon_crm:10001_heating"].args[2]) >= 55

    heating = hass.states.get("sensor.example_st_1_12345_town_flat_heating")
    assert heating is not None
    assert heating.attributes["period"] == "2026-09"
    assert hass.states.get("sensor.example_st_2_12345_town_workshop_hot_water") is None
    assert hass.states.get("sensor.example_st_2_12345_town_workshop_heating") is not None
    last = hass.states.get("sensor.portal_example_com_last_successful_update")
    assert last is not None and last.state.startswith("2026-10-20")


async def test_second_run_reimports_same_rows(hass, aioclient_mock, mock_entry):
    """Idempotency: the second update sends the identical full history again."""
    mock_portal(aioclient_mock)
    mock_entry.add_to_hass(hass)
    with patch(STATS) as add_stats:
        await hass.config_entries.async_setup(mock_entry.entry_id)
        await hass.async_block_till_done()
        first = [c.args[2] for c in add_stats.call_args_list]
        add_stats.reset_mock()
        await mock_entry.runtime_data.async_refresh()
        second = [c.args[2] for c in add_stats.call_args_list]
    assert first == second


async def test_login_failure_starts_reauth(hass, aioclient_mock, mock_entry):
    mock_portal(aioclient_mock, password_ok=False)
    mock_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_entry.entry_id)
    await hass.async_block_till_done()
    assert mock_entry.state is ConfigEntryState.SETUP_ERROR
    assert any(
        f["context"]["source"] == "reauth" for f in hass.config_entries.flow.async_progress()
    )


async def test_unreachable_portal_retries_setup(hass, aioclient_mock, mock_entry):
    import aiohttp

    aioclient_mock.get("https://portal.example.com/api/auth-info", exc=aiohttp.ClientError)
    mock_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_entry.entry_id)
    assert mock_entry.state is ConfigEntryState.SETUP_RETRY


async def test_missing_contract_raises_repair(hass, aioclient_mock):
    mock_portal(aioclient_mock)
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id="x",
        data={"portal_url": "https://portal.example.com", "username": "u", "password": "p"},
        options={CONF_CONTRACTS: [FLAT_REF, "9|9|9"]},
    )
    entry.add_to_hass(hass)
    with patch(STATS):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.LOADED
    assert ir.async_get(hass).async_get_issue(DOMAIN, f"contract_missing_{entry.entry_id}_9|9|9")


async def test_diagnostics_are_redacted(hass, hass_client, aioclient_mock, mock_entry):
    mock_portal(aioclient_mock)
    mock_entry.add_to_hass(hass)
    with patch(STATS):
        await hass.config_entries.async_setup(mock_entry.entry_id)
        await hass.async_block_till_done()
    diag = await get_diagnostics_for_config_entry(hass, hass_client, mock_entry)
    assert diag["entry"]["password"] == REDACTED
    assert diag["entry"]["username"] == REDACTED
    dumped = str(diag)
    for secret in ("user@example.com", "10001", "Example St", "pw'"):
        assert secret not in dumped
    assert diag["contracts"][0]["heating"]["first"] == "2022-02"


async def test_diagnostics_hide_prefix_names_and_contract_numbers(
    hass, hass_client, aioclient_mock, mock_entry
):
    """A shared diagnostics file must not reveal the landlord, contracts or login."""
    mock_entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(
        mock_entry,
        options={
            CONF_CONTRACTS: [FLAT_REF],
            CONF_PREFIX: "Acmeprefix",
            CONF_NAMES: {FLAT_REF: "Flatname", "10001": "Flatname"},
        },
    )
    mock_portal(aioclient_mock)
    with patch(STATS):
        await hass.config_entries.async_setup(mock_entry.entry_id)
        await hass.async_block_till_done()
    diag = await get_diagnostics_for_config_entry(hass, hass_client, mock_entry)
    assert diag["options"][CONF_PREFIX] == REDACTED
    assert diag["options"][CONF_NAMES] == REDACTED
    dumped = str(diag)
    for secret in (
        "Acmeprefix",
        "Flatname",
        "10001",
        "1000001",
        "portal.example.com",
        "user@example.com",
        "pw'",
    ):
        assert secret not in dumped
