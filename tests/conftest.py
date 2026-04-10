"""Fixtures for Connectbox integration tests."""

from __future__ import annotations

from collections.abc import Generator
from unittest.mock import AsyncMock, patch

import pytest
from homeassistant.const import CONF_HOST, CONF_PASSWORD

from custom_components.connectbox.api import DocsisChannel, DocsisStatus

MOCK_HOST = "192.168.100.1"
MOCK_PASSWORD = "testpassword"

MOCK_CONFIG = {
    CONF_HOST: MOCK_HOST,
    CONF_PASSWORD: MOCK_PASSWORD,
}


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations: None) -> None:
    """Enable custom integrations for all tests."""
    return


def _build_mock_docsis_status() -> DocsisStatus:
    """Build a representative DocsisStatus for tests."""
    return DocsisStatus(
        operational="Operational",
        downstream=[
            DocsisChannel(
                channel_id="1",
                direction="downstream",
                channel_type="SC-QAM",
                frequency_mhz=602.0,
                power_dbmv=6.9,
                snr_db=38.0,
                modulation="256QAM",
                locked="Locked",
            ),
            DocsisChannel(
                channel_id="2",
                direction="downstream",
                channel_type="SC-QAM",
                frequency_mhz=610.0,
                power_dbmv=7.1,
                snr_db=37.5,
                modulation="256QAM",
                locked="Locked",
            ),
        ],
        upstream=[
            DocsisChannel(
                channel_id="1",
                direction="upstream",
                channel_type="SC-QAM",
                frequency_mhz=51.0,
                power_dbmv=44.0,
                modulation="64QAM",
                locked="Ranged",
            ),
        ],
    )


@pytest.fixture
def mock_docsis_status() -> DocsisStatus:
    """Return a mock DocsisStatus."""
    return _build_mock_docsis_status()


@pytest.fixture
def mock_api() -> Generator[AsyncMock]:
    """Mock the ConnectboxApiClient."""
    with patch(
        "custom_components.connectbox.api.ConnectboxApiClient",
        autospec=True,
    ) as mock_client_class:
        client = mock_client_class.return_value
        client.async_validate_credentials = AsyncMock(return_value=None)
        client.async_get_docsis_status = AsyncMock(
            return_value=_build_mock_docsis_status()
        )
        type(client).host = property(lambda self: MOCK_HOST)
        yield client


@pytest.fixture
def mock_api_config_flow() -> Generator[AsyncMock]:
    """Mock the API client specifically for config flow tests."""
    with patch(
        "custom_components.connectbox.config_flow.ConnectboxApiClient",
        autospec=True,
    ) as mock_client_class:
        client = mock_client_class.return_value
        client.async_validate_credentials = AsyncMock(return_value=None)
        yield client


@pytest.fixture
def mock_setup_entry() -> Generator[AsyncMock]:
    """Mock async_setup_entry."""
    with patch(
        "custom_components.connectbox.async_setup_entry",
        return_value=True,
    ) as mock:
        yield mock
