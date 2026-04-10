"""Tests for the Connectbox integration setup."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

from homeassistant import config_entries
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.connectbox.api import (
    ConnectboxAuthenticationError,
    ConnectboxConnectionError,
)
from custom_components.connectbox.const import DOMAIN

from .conftest import MOCK_CONFIG, MOCK_HOST


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


async def test_setup_entry(
    hass: HomeAssistant,
    mock_api: AsyncMock,
) -> None:
    """Test successful setup."""
    with patch(
        "custom_components.connectbox.ConnectboxApiClient",
        return_value=mock_api,
    ):
        entry = _create_entry(hass)
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

        assert entry.state is ConfigEntryState.LOADED
        assert entry.runtime_data is not None


async def test_setup_entry_connection_error(
    hass: HomeAssistant,
    mock_api: AsyncMock,
) -> None:
    """Test setup with connection error raises ConfigEntryNotReady."""
    mock_api.async_get_docsis_status.side_effect = ConnectboxConnectionError("Timeout")

    with patch(
        "custom_components.connectbox.ConnectboxApiClient",
        return_value=mock_api,
    ):
        entry = _create_entry(hass)
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

        assert entry.state is ConfigEntryState.SETUP_RETRY


async def test_setup_entry_auth_error(
    hass: HomeAssistant,
    mock_api: AsyncMock,
) -> None:
    """Test setup with auth error triggers reauth."""
    mock_api.async_get_docsis_status.side_effect = ConnectboxAuthenticationError(
        "Login failed"
    )

    with patch(
        "custom_components.connectbox.ConnectboxApiClient",
        return_value=mock_api,
    ):
        entry = _create_entry(hass)
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

        assert entry.state is ConfigEntryState.SETUP_ERROR


async def test_unload_entry(
    hass: HomeAssistant,
    mock_api: AsyncMock,
) -> None:
    """Test unloading an entry."""
    with patch(
        "custom_components.connectbox.ConnectboxApiClient",
        return_value=mock_api,
    ):
        entry = _create_entry(hass)
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

        assert entry.state is ConfigEntryState.LOADED

        await hass.config_entries.async_unload(entry.entry_id)
        await hass.async_block_till_done()

        assert entry.state is ConfigEntryState.NOT_LOADED
