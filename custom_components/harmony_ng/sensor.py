"""Sensor platform for Harmony NG."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
import logging
from typing import Any

from homeassistant.components.sensor import SensorEntity, SensorEntityDescription
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import HarmonyNgConfigEntry
from .entity import HarmonyNgEntity

_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, kw_only=True)
class HarmonyNgSensorEntityDescription(SensorEntityDescription):
    """Describes a Harmony NG sensor entity."""

    value_fn: Callable[[dict[str, Any]], Any] | None = None


SENSOR_DESCRIPTIONS: tuple[HarmonyNgSensorEntityDescription, ...] = (
    # TODO: Add sensor descriptions
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: HarmonyNgConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up sensor entities."""
    coordinator = entry.runtime_data.coordinator
    async_add_entities(
        HarmonyNgSensor(coordinator, description) for description in SENSOR_DESCRIPTIONS
    )


class HarmonyNgSensor(HarmonyNgEntity, SensorEntity):
    """A Harmony NG sensor."""

    entity_description: HarmonyNgSensorEntityDescription

    @property
    def native_value(self) -> Any:
        """Return the value read from the coordinator data."""
        if self.entity_description.value_fn is None:
            return None
        return self.entity_description.value_fn(self.coordinator.data)
