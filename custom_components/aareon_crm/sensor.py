"""Sensors: last complete month per contract and service."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import EntityCategory, UnitOfEnergy
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from .const import DOMAIN, SERVICE_KEYS
from .coordinator import AareonConfigEntry, AareonCoordinator
from .statistics import last_complete_month

PARALLEL_UPDATES = 0

CONSUMPTION_SENSORS = [
    SensorEntityDescription(
        key=f"{service}{suffix}",
        translation_key=f"{service}{suffix}",
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        suggested_display_precision=0,
    )
    for service in SERVICE_KEYS.values()
    for suffix in ("", "_standardized")
]


async def async_setup_entry(
    hass: HomeAssistant,
    entry: AareonConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Create sensors for every service a contract actually has data for."""
    coordinator = entry.runtime_data
    entities: list[SensorEntity] = [AareonLastUpdateSensor(coordinator)]
    for reference, contract in coordinator.data.contracts.items():
        for description in CONSUMPTION_SENSORS:
            service = description.key.removesuffix("_standardized")
            if service in contract.months:
                entities.append(AareonConsumptionSensor(coordinator, reference, description))
    async_add_entities(entities)


class AareonConsumptionSensor(CoordinatorEntity[AareonCoordinator], SensorEntity):
    """Consumption of the last complete month."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: AareonCoordinator,
        reference: str,
        description: SensorEntityDescription,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self.entity_description = description
        self._reference = reference
        contract = coordinator.data.contracts[reference]
        self._attr_unique_id = f"{contract.number}_{description.key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, contract.number)},
            name=contract.name,
            manufacturer="Aareon",
            model="Mieterportal",
            entry_type=DeviceEntryType.SERVICE,
        )

    def _last(self):
        contract = self.coordinator.data.contracts.get(self._reference)
        if contract is None:
            return None
        key = self.entity_description.key
        service = key.removesuffix("_standardized")
        return last_complete_month(contract.months.get(service, {}), dt_util.now().date())

    @property
    def available(self) -> bool:
        """Unavailable while the contract is missing or has no data."""
        return super().available and self._last() is not None

    @property
    def native_value(self) -> float | None:
        """Amount of the last complete month."""
        last = self._last()
        if last is None:
            return None
        value = last[1]
        if self.entity_description.key.endswith("_standardized"):
            return value.standardized
        return value.amount

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Month the value belongs to."""
        last = self._last()
        if last is None:
            return None
        return {"period": last[0], "estimated": last[1].estimated}


class AareonLastUpdateSensor(CoordinatorEntity[AareonCoordinator], SensorEntity):
    """Time of the last successful portal update."""

    _attr_has_entity_name = True
    _attr_translation_key = "last_update"
    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator: AareonCoordinator) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        entry = coordinator.config_entry
        self._attr_unique_id = f"{entry.entry_id}_last_update"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=entry.title,
            manufacturer="Aareon",
            model="Mieterportal",
            entry_type=DeviceEntryType.SERVICE,
        )

    @property
    def native_value(self) -> datetime:
        """Timestamp of the last successful update."""
        return self.coordinator.data.last_update
