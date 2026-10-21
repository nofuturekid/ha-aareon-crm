"""Shared fixtures: a fake portal built from recorded, anonymised JSON."""

from __future__ import annotations

import json
import re
from pathlib import Path
from urllib.parse import quote

import pytest
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from custom_components.aareon_crm.const import CONF_CONTRACTS, CONF_PORTAL_URL, DOMAIN

BASE = "https://portal.example.com"
FIXTURES = Path(__file__).parent / "fixtures"
FLAT_REF = "1000001|1|-1"
WORKSHOP_REF = "1000001|1|-2"
KC = f"{BASE}/realms/tenant/protocol/openid-connect"
LOGIN_FORM = (
    '<html><form id="kc-form-login" action="'
    f"{BASE}/realms/tenant/login-actions/authenticate?session_code=a&amp;tab_id=b"
    '" method="post"></form></html>'
)


def load(name: str):
    return json.loads((FIXTURES / name).read_text())


@pytest.fixture(autouse=True)
def integration_env(recorder_mock, enable_custom_integrations):
    """Real in-memory recorder (a dependency) and custom_components loading.

    `recorder_mock` must come first: the recorder DB is prepared before `hass`.
    """


def mock_portal(mocker: AiohttpClientMocker, *, password_ok: bool = True) -> None:
    """Register the whole Keycloak + API conversation."""
    mocker.get(f"{BASE}/api/auth-info", json={"realm": "tenant", "client-id": "crm-frontend-app"})
    mocker.get(re.compile(rf"{re.escape(KC)}/auth\?"), text=LOGIN_FORM)
    if password_ok:
        mocker.post(
            re.compile(r".*login-actions/authenticate.*"),
            status=302,
            headers={"Location": f"{BASE}/realms/tenant/login-actions/required-action?execution=x"},
        )
        mocker.get(
            re.compile(r".*login-actions/required-action.*"),
            status=302,
            headers={"Location": f"{BASE}/app/de/?state=s&code=the-code"},
        )
    else:
        mocker.post(re.compile(r".*login-actions/authenticate.*"), text=LOGIN_FORM)
    mocker.post(
        f"{KC}/token", json={"access_token": "at", "refresh_token": "rt", "expires_in": 300}
    )
    mocker.post(f"{KC}/logout", status=204)
    mocker.get(
        f"{BASE}/api/tenant/erp-data-provider/contracts?apply-crm-config-filter=1",
        json=load("contracts.json"),
    )
    for ref, fixture in (
        (FLAT_REF, "consumption_flat.json"),
        (WORKSHOP_REF, "consumption_workshop.json"),
    ):
        mocker.get(
            re.compile(rf".*/consumption/from/.*/contract/{re.escape(quote(ref, safe=''))}$"),
            json={"results": load(fixture)},
        )


@pytest.fixture
def portal(aioclient_mock: AiohttpClientMocker) -> AiohttpClientMocker:
    mock_portal(aioclient_mock)
    return aioclient_mock


@pytest.fixture
def mock_entry() -> MockConfigEntry:
    return MockConfigEntry(
        domain=DOMAIN,
        title="portal.example.com",
        unique_id="portal.example.com_user@example.com",
        data={CONF_PORTAL_URL: BASE, CONF_USERNAME: "user@example.com", CONF_PASSWORD: "pw"},
        options={CONF_CONTRACTS: [FLAT_REF, WORKSHOP_REF]},
    )
