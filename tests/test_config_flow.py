"""Config, reauth and options flows."""

from __future__ import annotations

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.const import CONF_NAME, CONF_PASSWORD, CONF_USERNAME
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.aareon_crm.const import (
    CONF_CONTRACTS,
    CONF_NAMES,
    CONF_PORTAL_URL,
    CONF_PREFIX,
    DOMAIN,
)

from .conftest import BASE, FLAT_REF, WORKSHOP_REF, mock_portal

USER = {
    CONF_PORTAL_URL: "portal.example.com",
    CONF_USERNAME: "User@Example.com",
    CONF_PASSWORD: "pw",
}


async def test_full_flow_suggests_names_and_prefix(hass, aioclient_mock):
    mock_portal(aioclient_mock)
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(result["flow_id"], USER)
    assert result["step_id"] == "contracts"
    defaults = {
        k: k.default() for k in result["data_schema"].schema if k.default is not vol.UNDEFINED
    }
    assert defaults[CONF_CONTRACTS] == [FLAT_REF, WORKSHOP_REF]
    assert defaults[CONF_PREFIX] == "Example"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_CONTRACTS: [FLAT_REF, WORKSHOP_REF], CONF_PREFIX: "Example"}
    )
    assert result["step_id"] == "name"
    assert "10001" in result["description_placeholders"]["contract"]
    assert next(iter(result["data_schema"].schema)).default() == "Wohnung"
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {CONF_NAME: "Flat"})
    assert result["step_id"] == "name"
    assert next(iter(result["data_schema"].schema)).default() == "Gewerbe"
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {CONF_NAME: "Shop"})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_PORTAL_URL] == BASE
    assert result["options"] == {
        CONF_CONTRACTS: [FLAT_REF, WORKSHOP_REF],
        CONF_PREFIX: "Example",
        CONF_NAMES: {FLAT_REF: "Flat", WORKSHOP_REF: "Shop"},
    }
    assert result["result"].unique_id == "portal.example.com_user@example.com"


async def test_no_contract_selected_is_rejected(hass, aioclient_mock):
    mock_portal(aioclient_mock)
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(result["flow_id"], USER)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_CONTRACTS: [], CONF_PREFIX: ""}
    )
    assert result["errors"] == {"base": "no_contracts"}


async def test_invalid_auth_shows_error_and_never_retries(hass, aioclient_mock):
    mock_portal(aioclient_mock, password_ok=False)
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(result["flow_id"], USER)
    assert result["errors"] == {"base": "invalid_auth"}
    posts = [c for c in aioclient_mock.mock_calls if c[0] == "POST" and "authenticate" in c[1].path]
    assert len(posts) == 1  # a single attempt: no lockout risk


async def test_invalid_url(hass):
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {**USER, CONF_PORTAL_URL: "ftp://x"}
    )
    assert result["errors"] == {CONF_PORTAL_URL: "invalid_url"}


async def test_duplicate_account_aborts(hass, mock_entry: MockConfigEntry):
    mock_entry.add_to_hass(hass)
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(result["flow_id"], USER)
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_reauth_updates_password(hass, aioclient_mock, mock_entry: MockConfigEntry):
    mock_portal(aioclient_mock)
    mock_entry.add_to_hass(hass)
    result = await mock_entry.start_reauth_flow(hass)
    assert result["step_id"] == "reauth_confirm"
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_PASSWORD: "new"}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reauth_successful"
    assert mock_entry.data[CONF_PASSWORD] == "new"


async def test_reauth_wrong_password(hass, aioclient_mock, mock_entry: MockConfigEntry):
    mock_portal(aioclient_mock, password_ok=False)
    mock_entry.add_to_hass(hass)
    result = await mock_entry.start_reauth_flow(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_PASSWORD: "bad"}
    )
    assert result["errors"] == {"base": "invalid_auth"}


async def test_options_rename_updates_device_name_but_not_unique_ids(
    hass, aioclient_mock, mock_entry: MockConfigEntry
):
    mock_portal(aioclient_mock)
    mock_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_entry.entry_id)
    await hass.async_block_till_done()
    ent_reg = er.async_get(hass)
    before = {
        e.entity_id: e.unique_id
        for e in er.async_entries_for_config_entry(ent_reg, mock_entry.entry_id)
    }

    result = await hass.config_entries.options.async_init(mock_entry.entry_id)
    assert result["step_id"] == "init"
    defaults = {
        k: k.default() for k in result["data_schema"].schema if k.default is not vol.UNDEFINED
    }
    assert defaults[CONF_PREFIX] == "Example"  # nothing saved yet -> suggestion
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {CONF_CONTRACTS: [WORKSHOP_REF], CONF_PREFIX: "Acme"}
    )
    assert result["step_id"] == "name"
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {CONF_NAME: "Shop"}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()

    assert mock_entry.options[CONF_NAMES] == {WORKSHOP_REF: "Shop"}
    device = dr.async_get(hass).async_get_device_by_identifier(
        (DOMAIN, "10002"), mock_entry.entry_id
    )
    assert device.name == "Acme Shop"
    after = {
        e.entity_id: e.unique_id
        for e in er.async_entries_for_config_entry(ent_reg, mock_entry.entry_id)
    }
    for entity_id, unique_id in after.items():
        assert before.get(entity_id, unique_id) == unique_id


async def test_options_saved_names_are_prefilled(hass, aioclient_mock, mock_entry: MockConfigEntry):
    mock_portal(aioclient_mock)
    mock_entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(
        mock_entry,
        options={
            CONF_CONTRACTS: [FLAT_REF],
            CONF_PREFIX: "Acme",
            CONF_NAMES: {FLAT_REF: "Home"},
        },
    )
    result = await hass.config_entries.options.async_init(mock_entry.entry_id)
    defaults = {
        k: k.default() for k in result["data_schema"].schema if k.default is not vol.UNDEFINED
    }
    assert defaults[CONF_PREFIX] == "Acme"
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {CONF_CONTRACTS: [FLAT_REF], CONF_PREFIX: "Acme"}
    )
    assert next(iter(result["data_schema"].schema)).default() == "Home"
