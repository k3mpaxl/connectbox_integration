"""Sensor platform for the Connectbox integration."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import (
    EntityCategory,
    UnitOfFrequency,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .api import DocsisChannel, DocsisStatus
from .const import LOGGER
from .coordinator import ConnectboxConfigEntry, ConnectboxCoordinator
from .entity import ConnectboxEntity

PARALLEL_UPDATES = 0

UNIT_DBMV = "dBmV"
UNIT_DECIBEL = "dB"


@dataclass(frozen=True, kw_only=True)
class ConnectboxSensorDescription(SensorEntityDescription):
    """Describe a Connectbox sensor."""

    value_fn: Callable[[DocsisChannel], float | str | None]
    directions: tuple[str, ...] = ("downstream", "upstream")


CHANNEL_SENSORS: tuple[ConnectboxSensorDescription, ...] = (
    ConnectboxSensorDescription(
        key="power",
        translation_key="channel_power",
        native_unit_of_measurement=UNIT_DBMV,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
        value_fn=lambda ch: ch.power_dbmv,
    ),
    ConnectboxSensorDescription(
        key="frequency",
        translation_key="channel_frequency",
        native_unit_of_measurement=UnitOfFrequency.MEGAHERTZ,
        device_class=SensorDeviceClass.FREQUENCY,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
        value_fn=lambda ch: ch.frequency_mhz,
    ),
    ConnectboxSensorDescription(
        key="snr",
        translation_key="channel_snr",
        native_unit_of_measurement=UNIT_DECIBEL,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        suggested_display_precision=1,
        directions=("downstream",),
        value_fn=lambda ch: ch.snr_db,
    ),
    ConnectboxSensorDescription(
        key="modulation",
        translation_key="channel_modulation",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda ch: ch.modulation or None,
    ),
    ConnectboxSensorDescription(
        key="locked",
        translation_key="channel_locked",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda ch: ch.locked or None,
    ),
)

OPERATIONAL_SENSOR = ConnectboxSensorDescription(
    key="operational_status",
    translation_key="operational_status",
    value_fn=lambda _: None,  # handled separately
)


def _get_channels(data: DocsisStatus, direction: str) -> list[DocsisChannel]:
    """Return channels for a given direction."""
    if direction == "downstream":
        return data.downstream
    return data.upstream


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConnectboxConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Connectbox sensors from a config entry."""
    coordinator = entry.runtime_data

    entities: list[ConnectboxSensorEntity] = []
    data = coordinator.data

    if data is None:
        return

    # Operational status sensor
    entities.append(
        ConnectboxOperationalSensor(
            coordinator=coordinator,
            description=OPERATIONAL_SENSOR,
        )
    )

    # Per-channel sensors
    for description in CHANNEL_SENSORS:
        for direction in description.directions:
            for channel in _get_channels(data, direction):
                entities.append(
                    ConnectboxChannelSensor(
                        coordinator=coordinator,
                        description=description,
                        direction=direction,
                        channel_id=channel.channel_id,
                    )
                )

    LOGGER.debug("Adding %d Connectbox sensors", len(entities))
    async_add_entities(entities)


class ConnectboxSensorEntity(ConnectboxEntity, SensorEntity):
    """Base class for Connectbox sensors."""


class ConnectboxOperationalSensor(ConnectboxSensorEntity):
    """Sensor for the overall DOCSIS operational status."""

    entity_description: ConnectboxSensorDescription

    def __init__(
        self,
        coordinator: ConnectboxCoordinator,
        description: ConnectboxSensorDescription,
    ) -> None:
        """Initialise the sensor."""
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{coordinator.config_entry.entry_id}_operational_status"

    @property
    def native_value(self) -> str | None:
        """Return the operational status."""
        if self.coordinator.data is None:
            return None
        return self.coordinator.data.operational


class ConnectboxChannelSensor(ConnectboxSensorEntity):
    """Sensor for a per-channel DOCSIS metric."""

    entity_description: ConnectboxSensorDescription

    def __init__(
        self,
        coordinator: ConnectboxCoordinator,
        description: ConnectboxSensorDescription,
        direction: str,
        channel_id: str,
    ) -> None:
        """Initialise the sensor."""
        super().__init__(coordinator)
        self.entity_description = description
        self._direction = direction
        self._channel_id = channel_id

        prefix = "DS" if direction == "downstream" else "US"
        entry_id = coordinator.config_entry.entry_id
        self._attr_unique_id = f"{entry_id}_{direction}_{channel_id}_{description.key}"
        self._attr_translation_placeholders = {
            "prefix": prefix,
            "channel_id": channel_id,
        }

    @property
    def native_value(self) -> float | str | None:
        """Return the current value."""
        channel = self._find_channel()
        if channel is None:
            return None
        return self.entity_description.value_fn(channel)

    def _find_channel(self) -> DocsisChannel | None:
        """Find the channel in coordinator data."""
        if self.coordinator.data is None:
            return None
        channels = _get_channels(self.coordinator.data, self._direction)
        for ch in channels:
            if ch.channel_id == self._channel_id:
                return ch
        return None
