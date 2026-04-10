"""Tests for the Connectbox config flow."""

from __future__ import annotations

from unittest.mock import AsyncMock

from homeassistant import config_entries
from homeassistant.const import CONF_HOST, CONF_PASSWORD
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.connectbox.api import (
    ConnectboxAuthenticationError,
    ConnectboxConnectionError,
)
from custom_components.connectbox.const import DOMAIN

from .conftest import MOCK_CONFIG, MOCK_HOST


async def test_user_flow_success(
    hass: HomeAssistant,
    mock_api_config_flow: AsyncMock,
    mock_setup_entry: AsyncMock,
) -> None:
    """Test successful user config flow."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        user_input=MOCK_CONFIG,
    )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == f"Connectbox ({MOCK_HOST})"
    assert result["data"] == MOCK_CONFIG
    mock_setup_entry.assert_called_once()


async def test_user_flow_invalid_auth(
    hass: HomeAssistant,
    mock_api_config_flow: AsyncMock,
) -> None:
    """Test user flow with invalid auth."""
    mock_api_config_flow.async_validate_credentials.side_effect = (
        ConnectboxAuthenticationError("Login failed")
    )

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        user_input=MOCK_CONFIG,
    )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "invalid_auth"}


async def test_user_flow_cannot_connect(
    hass: HomeAssistant,
    mock_api_config_flow: AsyncMock,
) -> None:
    """Test user flow with connection error."""
    mock_api_config_flow.async_validate_credentials.side_effect = (
        ConnectboxConnectionError("Timeout")
    )

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        user_input=MOCK_CONFIG,
    )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "cannot_connect"}


async def test_user_flow_unknown_error(
    hass: HomeAssistant,
    mock_api_config_flow: AsyncMock,
) -> None:
    """Test user flow with unexpected error."""
    mock_api_config_flow.async_validate_credentials.side_effect = RuntimeError("boom")

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        user_input=MOCK_CONFIG,
    )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "unknown"}


async def test_user_flow_already_configured(
    hass: HomeAssistant,
    mock_api_config_flow: AsyncMock,
    mock_setup_entry: AsyncMock,
) -> None:
    """Test user flow when device is already configured."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Connectbox",
        data=MOCK_CONFIG,
        source=config_entries.SOURCE_USER,
        unique_id=MOCK_HOST,
    )
    entry.add_to_hass(hass)

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        user_input=MOCK_CONFIG,
    )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_reauth_flow_success(
    hass: HomeAssistant,
    mock_api_config_flow: AsyncMock,
    mock_setup_entry: AsyncMock,
) -> None:
    """Test successful reauth flow."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Connectbox",
        data=MOCK_CONFIG,
        source=config_entries.SOURCE_USER,
        unique_id=MOCK_HOST,
    )
    entry.add_to_hass(hass)

    result = await entry.start_reauth_flow(hass)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "reauth_confirm"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        user_input={CONF_PASSWORD: "new_password"},
    )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reauth_successful"
    assert entry.data[CONF_PASSWORD] == "new_password"


async def test_reauth_flow_invalid_auth(
    hass: HomeAssistant,
    mock_api_config_flow: AsyncMock,
) -> None:
    """Test reauth flow with invalid credentials."""
    mock_api_config_flow.async_validate_credentials.side_effect = (
        ConnectboxAuthenticationError("Login failed")
    )

    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Connectbox",
        data=MOCK_CONFIG,
        source=config_entries.SOURCE_USER,
        unique_id=MOCK_HOST,
    )
    entry.add_to_hass(hass)

    result = await entry.start_reauth_flow(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        user_input={CONF_PASSWORD: "wrong"},
    )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "invalid_auth"}


async def test_reconfigure_flow_success(
    hass: HomeAssistant,
    mock_api_config_flow: AsyncMock,
    mock_setup_entry: AsyncMock,
) -> None:
    """Test successful reconfigure flow."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Connectbox",
        data=MOCK_CONFIG,
        source=config_entries.SOURCE_USER,
        unique_id=MOCK_HOST,
    )
    entry.add_to_hass(hass)

    result = await entry.start_reconfigure_flow(hass)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "reconfigure"

    new_config = {CONF_HOST: "10.0.0.1", CONF_PASSWORD: "newpass"}
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        user_input=new_config,
    )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"


async def test_reconfigure_flow_error(
    hass: HomeAssistant,
    mock_api_config_flow: AsyncMock,
) -> None:
    """Test reconfigure flow with connection error."""
    mock_api_config_flow.async_validate_credentials.side_effect = (
        ConnectboxConnectionError("Timeout")
    )

    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Connectbox",
        data=MOCK_CONFIG,
        source=config_entries.SOURCE_USER,
        unique_id=MOCK_HOST,
    )
    entry.add_to_hass(hass)

    result = await entry.start_reconfigure_flow(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        user_input={CONF_HOST: "10.0.0.1", CONF_PASSWORD: "pass"},
    )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "cannot_connect"}


async def test_options_flow(
    hass: HomeAssistant,
    mock_setup_entry: AsyncMock,
) -> None:
    """Test options flow."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Connectbox",
        data=MOCK_CONFIG,
        source=config_entries.SOURCE_USER,
        unique_id=MOCK_HOST,
    )
    entry.add_to_hass(hass)

    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "init"

    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        user_input={"scan_interval": 120},
    )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"] == {"scan_interval": 120}
