"""Tests for the Connectbox coordinator."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import UpdateFailed
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.connectbox.api import (
    ConnectboxApiClient,
    ConnectboxAuthenticationError,
    ConnectboxConnectionError,
)
from custom_components.connectbox.const import DOMAIN
from custom_components.connectbox.coordinator import ConnectboxCoordinator

from .conftest import MOCK_CONFIG, MOCK_HOST, _build_mock_docsis_status


def _create_entry(hass: HomeAssistant) -> MockConfigEntry:
    """Create a mock config entry."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Connectbox",
        data=MOCK_CONFIG,
        source=config_entries.SOURCE_USER,
        unique_id=MOCK_HOST,
    )
    entry.add_to_hass(hass)
    return entry


async def test_coordinator_update_success(hass: HomeAssistant) -> None:
    """Test successful coordinator update."""
    entry = _create_entry(hass)
    client = AsyncMock(spec=ConnectboxApiClient)
    client.async_get_docsis_status.return_value = _build_mock_docsis_status()

    coordinator = ConnectboxCoordinator(hass, entry, client)
    result = await coordinator._async_update_data()

    assert result is not None
    assert result.operational == "Operational"
    assert len(result.downstream) == 2
    assert len(result.upstream) == 1


async def test_coordinator_auth_error(hass: HomeAssistant) -> None:
    """Test coordinator raises ConfigEntryAuthFailed on auth error."""
    entry = _create_entry(hass)
    client = AsyncMock(spec=ConnectboxApiClient)
    client.async_get_docsis_status.side_effect = ConnectboxAuthenticationError(
        "Login failed"
    )

    coordinator = ConnectboxCoordinator(hass, entry, client)

    with pytest.raises(ConfigEntryAuthFailed):
        await coordinator._async_update_data()


async def test_coordinator_connection_error(hass: HomeAssistant) -> None:
    """Test coordinator raises UpdateFailed on connection error."""
    entry = _create_entry(hass)
    client = AsyncMock(spec=ConnectboxApiClient)
    client.async_get_docsis_status.side_effect = ConnectboxConnectionError("Timeout")

    coordinator = ConnectboxCoordinator(hass, entry, client)

    with pytest.raises(UpdateFailed):
        await coordinator._async_update_data()


async def test_coordinator_scan_interval_from_options(
    hass: HomeAssistant,
) -> None:
    """Test scan interval is taken from options."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Connectbox",
        data=MOCK_CONFIG,
        source=config_entries.SOURCE_USER,
        unique_id=MOCK_HOST,
        options={"scan_interval": 120},
    )
    entry.add_to_hass(hass)

    client = AsyncMock(spec=ConnectboxApiClient)
    coordinator = ConnectboxCoordinator(hass, entry, client)

    assert coordinator.update_interval is not None
    assert coordinator.update_interval.total_seconds() == 120
