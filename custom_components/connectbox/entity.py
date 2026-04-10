"""Base entity for the Connectbox integration."""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, MANUFACTURER, MODEL
from .coordinator import ConnectboxCoordinator


class ConnectboxEntity(CoordinatorEntity[ConnectboxCoordinator]):
    """Base class for Connectbox entities."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: ConnectboxCoordinator) -> None:
        """Initialise the entity."""
        super().__init__(coordinator)
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, coordinator.config_entry.entry_id)},
            manufacturer=MANUFACTURER,
            model=MODEL,
            name="Connectbox",
            configuration_url=f"http://{coordinator.client.host}",
        )
