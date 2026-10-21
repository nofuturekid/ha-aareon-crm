"""API client against the mocked Keycloak conversation."""

from __future__ import annotations

from datetime import date

import aiohttp
import pytest
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from custom_components.aareon_crm.api import (
    AareonAuthError,
    AareonClient,
    AareonConnectionError,
    normalize_base_url,
)

from .conftest import BASE, FLAT_REF, KC, mock_portal


def test_normalize_base_url():
    assert normalize_base_url("portal.example.com/app/de/") == "https://portal.example.com"
    assert normalize_base_url(" http://h:8080/x ") == "http://h:8080"
    with pytest.raises(ValueError):
        normalize_base_url("ftp://x")


async def test_login_fetch_logout(hass, aioclient_mock):
    mock_portal(aioclient_mock)
    client = AareonClient(async_get_clientsession(hass), BASE, "u", "p")
    await client.async_login()
    contracts = await client.async_get_contracts()
    results = await client.async_get_consumption(FLAT_REF, date(2019, 1, 1), date(2026, 1, 1))
    await client.async_logout()
    assert contracts[0]["reference"] == FLAT_REF
    assert "consumptions" in results
    token_call = next(c for c in aioclient_mock.mock_calls if c[1].path.endswith("/token"))
    assert token_call[2]["grant_type"] == "authorization_code"
    assert token_call[2]["code"] == "the-code"
    logout = next(c for c in aioclient_mock.mock_calls if c[1].path.endswith("/logout"))
    assert logout[2]["refresh_token"] == "rt"
    api_call = next(c for c in aioclient_mock.mock_calls if "consumption" in c[1].path)
    assert api_call[3]["Authorization"] == "Bearer at"
    assert api_call[1].raw_path.endswith("1000001%7C1%7C-1")


async def test_wrong_password_raises_auth_error(hass, aioclient_mock):
    mock_portal(aioclient_mock, password_ok=False)
    client = AareonClient(async_get_clientsession(hass), BASE, "u", "bad")
    with pytest.raises(AareonAuthError):
        await client.async_login()
    assert not any(c[1].path.endswith("/token") for c in aioclient_mock.mock_calls)


async def test_unreachable_portal(hass, aioclient_mock):
    aioclient_mock.get(f"{BASE}/api/auth-info", exc=aiohttp.ClientError)
    client = AareonClient(async_get_clientsession(hass), BASE, "u", "p")
    with pytest.raises(AareonConnectionError):
        await client.async_login()


async def test_expired_token_is_auth_error(hass, aioclient_mock):
    mock_portal(aioclient_mock)
    client = AareonClient(async_get_clientsession(hass), BASE, "u", "p")
    await client.async_login()
    aioclient_mock.clear_requests()
    aioclient_mock.get(
        f"{BASE}/api/tenant/erp-data-provider/contracts?apply-crm-config-filter=1", status=401
    )
    with pytest.raises(AareonAuthError):
        await client.async_get_contracts()
    assert KC
