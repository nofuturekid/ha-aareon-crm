"""Name suggestions."""

import pytest

from custom_components.aareon_crm.naming import device_name, suggest_contract_name, suggest_prefix


@pytest.mark.parametrize(
    ("company", "host", "expected"),
    [
        ("ACME mbH Town", "x.example.com", "Acme"),
        ("Muster Wohnen GmbH", "x.example.com", "Muster"),
        ("GmbH", "acme-town-crm.aareon.com", "Acme"),
        (None, "acme-town-crm.aareon.com", "Acme"),
    ],
)
def test_suggest_prefix(company, host, expected):
    assert suggest_prefix(company, host) == expected


@pytest.mark.parametrize(
    ("contract", "expected"),
    [
        ({"flatCategory": {"a": {"label": "Wohnraum"}}}, "Wohnung"),
        ({"flatCategory": {"a": {"label": "gewerbliche Nutzung"}}}, "Gewerbe"),
        ({"flatCategory": None, "subLabel": "Weg 1 - Wohnraum"}, "Wohnung"),
        ({"flatCategory": None, "subLabel": "Garage", "number": "7"}, "7"),
    ],
)
def test_suggest_contract_name(contract, expected):
    assert suggest_contract_name(contract) == expected


def test_device_name_without_prefix_has_no_stray_space():
    assert device_name("", "Home") == "Home"
    assert device_name("Acme", "Home") == "Acme Home"
