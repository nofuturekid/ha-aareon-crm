"""Suggestions for device name prefix and per-contract names (pure functions)."""

from __future__ import annotations

from typing import Any

_LEGAL_FORMS = {"mbh", "gmbh", "ag", "eg", "kg", "ohg", "ug", "se", "e.v.", "co.", "&"}


def suggest_prefix(company_name: str | None, portal_host: str) -> str:
    """Short company name: first word of the portal's company name, else the host."""
    for word in (company_name or "").split():
        if word.lower() not in _LEGAL_FORMS:
            return word.title() if word.isupper() else word
    return portal_host.split(".")[0].split("-")[0].title()


def suggest_contract_name(contract: dict[str, Any]) -> str:
    """Short name from the contract's usage category (German portal wording)."""
    categories = " ".join(
        str(v.get("label", "")) for v in (contract.get("flatCategory") or {}).values()
    )
    text = f"{categories} {contract.get('subLabel', '')} {contract.get('label', '')}".lower()
    if "gewerb" in text:
        return "Gewerbe"
    if "wohn" in text:
        return "Wohnung"
    return str(contract.get("number") or "")


def device_name(prefix: str, name: str) -> str:
    """Compose '<prefix> <name>' without stray spaces."""
    return f"{prefix} {name}".strip()
