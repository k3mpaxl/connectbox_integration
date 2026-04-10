"""The Connectbox integration."""

from __future__ import annotations

from homeassistant.const import CONF_HOST, CONF_PASSWORD
from homeassistant.core import HomeAssistant

from .api import ConnectboxApiClient
from .const import DEFAULT_HOST, PLATFORMS
from .coordinator import ConnectboxConfigEntry, ConnectboxCoordinator


async def async_setup_entry(hass: HomeAssistant, entry: ConnectboxConfigEntry) -> bool:
    """Set up Connectbox from a config entry."""
    host = entry.data.get(CONF_HOST, DEFAULT_HOST)
    password = entry.data[CONF_PASSWORD]

    client = ConnectboxApiClient(host, password)
    coordinator = ConnectboxCoordinator(hass, entry, client)

    await coordinator.async_config_entry_first_refresh()

    entry.runtime_data = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConnectboxConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def _async_update_listener(
    hass: HomeAssistant, entry: ConnectboxConfigEntry
) -> None:
    """Handle options update."""
    await hass.config_entries.async_reload(entry.entry_id)
