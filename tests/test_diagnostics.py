"""Tests for the Connectbox diagnostics."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

from homeassistant import config_entries
from homeassistant.const import CONF_HOST, CONF_PASSWORD
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.connectbox.const import DOMAIN
from custom_components.connectbox.diagnostics import (
    async_get_config_entry_diagnostics,
)

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


async def test_diagnostics(
    hass: HomeAssistant,
    mock_api: AsyncMock,
) -> None:
    """Test diagnostics returns expected data with redacted password."""
    with patch(
        "custom_components.connectbox.ConnectboxApiClient",
        return_value=mock_api,
    ):
        entry = _create_entry(hass)
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    result = await async_get_config_entry_diagnostics(hass, entry)

    # Password should be redacted
    assert result["config_entry"]["data"][CONF_PASSWORD] == "**REDACTED**"
    assert result["config_entry"]["data"][CONF_HOST] == MOCK_HOST

    # DOCSIS data should be present
    assert result["docsis_data"]["operational"] == "Operational"
    assert result["docsis_data"]["downstream_count"] == 2
    assert result["docsis_data"]["upstream_count"] == 1
    assert len(result["docsis_data"]["downstream"]) == 2
    assert len(result["docsis_data"]["upstream"]) == 1

    # Verify channel data
    ds_ch = result["docsis_data"]["downstream"][0]
    assert ds_ch["channel_id"] == "1"
    assert ds_ch["power_dbmv"] == 6.9
    assert ds_ch["snr_db"] == 38.0

    us_ch = result["docsis_data"]["upstream"][0]
    assert us_ch["channel_id"] == "1"
    assert us_ch["power_dbmv"] == 44.0
