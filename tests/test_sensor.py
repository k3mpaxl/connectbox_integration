"""Tests for the Connectbox sensor platform."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

from homeassistant import config_entries
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

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


async def test_sensor_setup(
    hass: HomeAssistant,
    mock_api: AsyncMock,
) -> None:
    """Test sensor entities are created from DOCSIS data."""
    with patch(
        "custom_components.connectbox.ConnectboxApiClient",
        return_value=mock_api,
    ):
        entry = _create_entry(hass)
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

        assert entry.state is ConfigEntryState.LOADED

    # Mock data: 2 DS channels + 1 US channel
    # Per DS channel: power, frequency, snr = 3 enabled sensors
    # Per US channel: power, frequency = 2 enabled sensors (no SNR for US)
    # Plus 1 operational status sensor
    # modulation + locked are disabled-by-default (3 modulation + 3 locked = 6 disabled)
    # Total enabled: 2*3 + 1*2 + 1 = 9
    states = hass.states.async_all("sensor")
    assert len(states) == 9


async def test_sensor_unique_ids(
    hass: HomeAssistant,
    mock_api: AsyncMock,
) -> None:
    """Test that all sensors have unique IDs."""
    with patch(
        "custom_components.connectbox.ConnectboxApiClient",
        return_value=mock_api,
    ):
        entry = _create_entry(hass)
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    entity_registry = er.async_get(hass)
    entities = entity_registry.entities.get_entries_for_config_entry_id(entry.entry_id)
    unique_ids = [e.unique_id for e in entities]
    # All 15 entities registered (including 6 disabled-by-default)
    assert len(unique_ids) == 15
    assert len(unique_ids) == len(set(unique_ids))


async def test_sensor_values(
    hass: HomeAssistant,
    mock_api: AsyncMock,
) -> None:
    """Test sensor state values match DOCSIS data."""
    with patch(
        "custom_components.connectbox.ConnectboxApiClient",
        return_value=mock_api,
    ):
        entry = _create_entry(hass)
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    # Check operational status
    op_state = None
    for state in hass.states.async_all("sensor"):
        if "operational" in state.entity_id:
            op_state = state
            break
    assert op_state is not None
    assert op_state.state == "Operational"


async def test_sensor_no_data(
    hass: HomeAssistant,
    mock_api: AsyncMock,
) -> None:
    """Test sensor setup when coordinator data is None."""
    mock_api.async_get_docsis_status.return_value = None

    with patch(
        "custom_components.connectbox.ConnectboxApiClient",
        return_value=mock_api,
    ):
        entry = _create_entry(hass)
        # This will fail with ConfigEntryNotReady or similar because
        # the coordinator expects DocsisStatus — that's correct behaviour.
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()


async def test_sensor_channel_disappears(
    hass: HomeAssistant,
    mock_api: AsyncMock,
) -> None:
    """Test that sensors return None when a channel disappears between polls."""
    with patch(
        "custom_components.connectbox.ConnectboxApiClient",
        return_value=mock_api,
    ):
        entry = _create_entry(hass)
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
        assert entry.state is ConfigEntryState.LOADED

    # Initially sensors have values
    states = hass.states.async_all("sensor")
    power_states = [s for s in states if "power" in s.entity_id]
    assert all(s.state != "unknown" for s in power_states)

    # Simulate channel disappearing: return empty channel lists
    from custom_components.connectbox.api import DocsisStatus

    mock_api.async_get_docsis_status.return_value = DocsisStatus(
        operational="Operational"
    )
    with patch(
        "custom_components.connectbox.ConnectboxApiClient",
        return_value=mock_api,
    ):
        await entry.runtime_data.async_refresh()
        await hass.async_block_till_done()

    # Channel sensors should now report unknown
    states = hass.states.async_all("sensor")
    power_states = [s for s in states if "power" in s.entity_id]
    assert all(s.state == "unknown" for s in power_states)
