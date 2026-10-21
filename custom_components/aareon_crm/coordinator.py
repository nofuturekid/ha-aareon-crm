"""Data coordinator: fetch consumption and import it as external statistics."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any

from homeassistant.components.recorder.models import (
    StatisticMeanType,
    StatisticMetaData,
)
from homeassistant.components.recorder.statistics import async_add_external_statistics
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME, UnitOfEnergy
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.aiohttp_client import async_create_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .api import AareonAuthError, AareonClient, AareonError
from .const import (
    CONF_CONTRACTS,
    CONF_NAMES,
    CONF_PORTAL_URL,
    CONF_PREFIX,
    DOMAIN,
    HISTORY_START,
    UPDATE_INTERVAL,
)
from .naming import device_name
from .statistics import Months, build_statistics, parse_consumption

_LOGGER = logging.getLogger(__name__)

type AareonConfigEntry = ConfigEntry[AareonCoordinator]


@dataclass
class ContractData:
    """Everything the entities need for one contract."""

    reference: str
    number: str
    name: str
    months: Months = field(default_factory=dict)


@dataclass
class AareonData:
    """Coordinator payload."""

    contracts: dict[str, ContractData]
    last_update: datetime


class AareonCoordinator(DataUpdateCoordinator[AareonData]):
    """Poll the portal every few hours."""

    config_entry: AareonConfigEntry

    def __init__(self, hass: HomeAssistant, entry: AareonConfigEntry) -> None:
        """Initialize the coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=DOMAIN,
            update_interval=UPDATE_INTERVAL,
        )
        self._client = AareonClient(
            async_create_clientsession(hass),
            entry.data[CONF_PORTAL_URL],
            entry.data[CONF_USERNAME],
            entry.data[CONF_PASSWORD],
        )

    async def _async_update_data(self) -> AareonData:
        selected: list[str] = self.config_entry.options.get(
            CONF_CONTRACTS, self.config_entry.data.get(CONF_CONTRACTS, [])
        )
        today = dt_util.now().date()
        try:
            await self._client.async_login()
            try:
                portal_contracts = {
                    c["reference"]: c for c in await self._client.async_get_contracts()
                }
                data: dict[str, ContractData] = {}
                for reference in selected:
                    contract = portal_contracts.get(reference)
                    self._set_missing_issue(reference, contract is None)
                    if contract is None:
                        continue
                    results = await self._client.async_get_consumption(
                        reference, date.fromisoformat(HISTORY_START), today
                    )
                    data[reference] = ContractData(
                        reference=reference,
                        number=str(contract["number"]),
                        name=self._contract_name(contract),
                        months=parse_consumption(results),
                    )
            finally:
                await self._client.async_logout()
        except AareonAuthError as err:
            raise ConfigEntryAuthFailed(str(err)) from err
        except AareonError as err:
            raise UpdateFailed(f"Portal request failed: {err}") from err

        for contract in data.values():
            self._import_statistics(contract)
        return AareonData(contracts=data, last_update=dt_util.utcnow())

    def _contract_name(self, contract: dict[str, Any]) -> str:
        """Device name: '<prefix> <name>' if configured, else the portal's label."""
        options = self.config_entry.options
        name = options.get(CONF_NAMES, {}).get(contract["reference"])
        if name:
            return device_name(options.get(CONF_PREFIX, ""), name)
        return contract.get("subLabel") or contract.get("label") or str(contract["number"])

    def _set_missing_issue(self, reference: str, missing: bool) -> None:
        issue_id = f"contract_missing_{self.config_entry.entry_id}_{reference}"
        if missing:
            ir.async_create_issue(
                self.hass,
                DOMAIN,
                issue_id,
                is_fixable=False,
                severity=ir.IssueSeverity.WARNING,
                translation_key="contract_missing",
                translation_placeholders={"reference": reference},
            )
        else:
            ir.async_delete_issue(self.hass, DOMAIN, issue_id)

    def _import_statistics(self, contract: ContractData) -> None:
        """Re-import the full history; rows are upserted by start time."""
        series: dict[str, Any] = build_statistics(contract.months, dt_util.get_default_time_zone())
        for suffix, rows in series.items():
            statistic_id = f"{DOMAIN}:{contract.number}_{suffix}"
            metadata = StatisticMetaData(
                mean_type=StatisticMeanType.NONE,
                has_sum=True,
                name=f"Aareon {contract.number} {suffix.replace('_', ' ')}",
                source=DOMAIN,
                statistic_id=statistic_id,
                unit_class="energy",
                unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
            )
            async_add_external_statistics(self.hass, metadata, rows)
