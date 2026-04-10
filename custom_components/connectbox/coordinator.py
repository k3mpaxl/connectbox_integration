"""DataUpdateCoordinator for the Connectbox integration."""

from __future__ import annotations

from datetime import timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import (
    ConnectboxApiClient,
    ConnectboxAuthenticationError,
    ConnectboxConnectionError,
    DocsisStatus,
)
from .const import DEFAULT_SCAN_INTERVAL, DOMAIN, LOGGER

type ConnectboxConfigEntry = ConfigEntry[ConnectboxCoordinator]


class ConnectboxCoordinator(DataUpdateCoordinator[DocsisStatus]):
    """Coordinator to manage fetching DOCSIS data from the Connectbox."""

    config_entry: ConnectboxConfigEntry

    def __init__(
        self,
        hass: HomeAssistant,
        config_entry: ConnectboxConfigEntry,
        client: ConnectboxApiClient,
    ) -> None:
        """Initialise the coordinator."""
        self.client = client

        scan_interval = config_entry.options.get("scan_interval", DEFAULT_SCAN_INTERVAL)

        super().__init__(
            hass,
            LOGGER,
            name=DOMAIN,
            config_entry=config_entry,
            update_interval=timedelta(seconds=scan_interval),
        )

    async def _async_update_data(self) -> DocsisStatus:
        """Fetch data from the Connectbox."""
        try:
            return await self.client.async_get_docsis_status()
        except ConnectboxAuthenticationError as err:
            raise ConfigEntryAuthFailed(
                translation_domain=DOMAIN,
                translation_key="auth_failed",
            ) from err
        except ConnectboxConnectionError as err:
            raise UpdateFailed(
                translation_domain=DOMAIN,
                translation_key="communication_error",
                translation_placeholders={"error": str(err)},
            ) from err
