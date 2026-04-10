"""Tests for the Connectbox API client."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import aiohttp
import pytest

from custom_components.connectbox.api import (
    ConnectboxApiClient,
    ConnectboxAuthenticationError,
    ConnectboxConnectionError,
    ConnectboxTimeoutError,
    DocsisStatus,
    _parse_docsis_data,
    _parse_value,
    _pbkdf2_hash,
)

# ------------------------------------------------------------------
# Pure function tests
# ------------------------------------------------------------------


class TestPbkdf2Hash:
    """Test the PBKDF2 hash function."""

    def test_known_value(self) -> None:
        """Test PBKDF2 with a known salt."""
        result = _pbkdf2_hash("password", "salt")
        assert isinstance(result, str)
        assert len(result) == 32  # 16 bytes = 32 hex chars

    def test_deterministic(self) -> None:
        """Test that same inputs produce same output."""
        assert _pbkdf2_hash("test", "abc") == _pbkdf2_hash("test", "abc")

    def test_different_passwords(self) -> None:
        """Test that different passwords produce different hashes."""
        assert _pbkdf2_hash("pass1", "salt") != _pbkdf2_hash("pass2", "salt")

    def test_different_salts(self) -> None:
        """Test that different salts produce different hashes."""
        assert _pbkdf2_hash("pass", "salt1") != _pbkdf2_hash("pass", "salt2")


class TestParseValue:
    """Test the value parser."""

    def test_frequency(self) -> None:
        assert _parse_value("674 MHz") == 674.0

    def test_power(self) -> None:
        assert _parse_value("6.9 dBmV") == 6.9

    def test_snr(self) -> None:
        assert _parse_value("38.0 dB") == 38.0

    def test_plain_number(self) -> None:
        assert _parse_value("42.5") == 42.5

    def test_empty_string(self) -> None:
        assert _parse_value("") == 0.0

    def test_invalid_string(self) -> None:
        assert _parse_value("not_a_number") == 0.0

    def test_whitespace(self) -> None:
        assert _parse_value("  100 MHz  ") == 100.0

    def test_symbol_rate_msym(self) -> None:
        assert _parse_value("5.12 Msym/s") == 5.12

    def test_symbol_rate_ksym(self) -> None:
        assert _parse_value("1280 ksym/s") == 1280.0


class TestParseDocsisData:
    """Test the DOCSIS data parser."""

    def test_empty_data(self) -> None:
        result = _parse_docsis_data({})
        assert result.operational == "Unknown"
        assert result.downstream == []
        assert result.upstream == []

    def test_operational_status(self) -> None:
        result = _parse_docsis_data({"operational": "Operational"})
        assert result.operational == "Operational"

    def test_downstream_scqam(self) -> None:
        data = {
            "downstream": [
                {
                    "channelid": "1",
                    "ChannelType": "SC-QAM",
                    "CentralFrequency": "602 MHz",
                    "power": "6.9 dBmV",
                    "SNR": "38.0 dB",
                    "FFT": "256QAM",
                    "locked": "Locked",
                }
            ]
        }
        result = _parse_docsis_data(data)
        assert len(result.downstream) == 1
        ch = result.downstream[0]
        assert ch.channel_id == "1"
        assert ch.direction == "downstream"
        assert ch.channel_type == "SC-QAM"
        assert ch.frequency_mhz == 602.0
        assert ch.power_dbmv == 6.9
        assert ch.snr_db == 38.0
        assert ch.modulation == "256QAM"
        assert ch.locked == "Locked"

    def test_ofdm_downstream(self) -> None:
        data = {
            "ofdm_downstream": [
                {
                    "channelid_ofdm": "33",
                    "ChannelType": "OFDM",
                    "CentralFrequency_ofdm": "722 MHz",
                    "power_ofdm": "8.1 dBmV",
                    "SNR_ofdm": "35.0 dB",
                    "FFT_ofdm": "4096QAM",
                    "locked_ofdm": "Locked",
                }
            ]
        }
        result = _parse_docsis_data(data)
        assert len(result.downstream) == 1
        ch = result.downstream[0]
        assert ch.channel_id == "OFDM-33"
        assert ch.channel_type == "OFDM"

    def test_upstream_scqam(self) -> None:
        data = {
            "upstream": [
                {
                    "channelidup": "1",
                    "ChannelType": "SC-QAM",
                    "CentralFrequency": "51 MHz",
                    "power": "44.0 dBmV",
                    "FFT": "64QAM",
                    "RangingStatus": "Ranged",
                }
            ]
        }
        result = _parse_docsis_data(data)
        assert len(result.upstream) == 1
        ch = result.upstream[0]
        assert ch.channel_id == "1"
        assert ch.direction == "upstream"
        assert ch.locked == "Ranged"

    def test_ofdma_upstream(self) -> None:
        data = {
            "ofdma_upstream": [
                {
                    "channelidup": "5",
                    "ChannelType": "OFDMA",
                    "CentralFrequency": "37 MHz",
                    "power": "40.0 dBmV",
                    "FFT": "256QAM",
                    "RangingStatus": "Ranged",
                }
            ]
        }
        result = _parse_docsis_data(data)
        assert len(result.upstream) == 1
        ch = result.upstream[0]
        assert ch.channel_id == "OFDMA-5"
        assert ch.channel_type == "OFDMA"

    def test_mixed_channels(self) -> None:
        data = {
            "operational": "Operational",
            "downstream": [{"channelid": "1"}],
            "ofdm_downstream": [{"channelid_ofdm": "33"}],
            "upstream": [{"channelidup": "1"}],
            "ofdma_upstream": [{"channelidup": "5"}],
        }
        result = _parse_docsis_data(data)
        assert len(result.downstream) == 2
        assert len(result.upstream) == 2

    def test_only_downstream(self) -> None:
        """Test that missing upstream lists are handled gracefully."""
        data = {
            "operational": "Operational",
            "downstream": [{"channelid": "1", "CentralFrequency": "602 MHz"}],
        }
        result = _parse_docsis_data(data)
        assert len(result.downstream) == 1
        assert result.upstream == []
        assert result.operational == "Operational"

    def test_only_upstream(self) -> None:
        """Test that missing downstream lists are handled gracefully."""
        data = {
            "operational": "Operational",
            "upstream": [{"channelidup": "1", "CentralFrequency": "51 MHz"}],
        }
        result = _parse_docsis_data(data)
        assert result.downstream == []
        assert len(result.upstream) == 1

    def test_channel_with_missing_fields(self) -> None:
        """Test that channels with incomplete data use safe defaults."""
        data = {
            "downstream": [{"channelid": "1"}],
        }
        result = _parse_docsis_data(data)
        ch = result.downstream[0]
        assert ch.channel_id == "1"
        assert ch.frequency_mhz == 0.0
        assert ch.power_dbmv == 0.0
        assert ch.snr_db == 0.0
        assert ch.modulation == ""
        assert ch.locked == ""


# ------------------------------------------------------------------
# Async client tests
# ------------------------------------------------------------------


@pytest.fixture
def mock_session():
    """Create a mocked aiohttp session."""
    session = AsyncMock(spec=aiohttp.ClientSession)
    session.cookie_jar = MagicMock(spec=aiohttp.CookieJar)
    return session


class TestConnectboxApiClient:
    """Test the API client."""

    def test_init(self) -> None:
        client = ConnectboxApiClient("192.168.100.1", "password")
        assert client.host == "192.168.100.1"
        assert client._password == "password"
        assert client._base_url == "http://192.168.100.1"

    @pytest.mark.asyncio
    async def test_validate_credentials_success(self) -> None:
        """Test successful credential validation."""
        client = ConnectboxApiClient("192.168.100.1", "password")
        with (
            patch.object(client, "_async_login", new_callable=AsyncMock),
            patch.object(client, "_async_logout", new_callable=AsyncMock),
        ):
            await client.async_validate_credentials()

    @pytest.mark.asyncio
    async def test_validate_credentials_auth_error(self) -> None:
        """Test credential validation with auth error."""
        client = ConnectboxApiClient("192.168.100.1", "wrong")
        with (
            patch.object(
                client,
                "_async_login",
                side_effect=ConnectboxAuthenticationError("Login failed"),
            ),
            patch.object(client, "_async_logout", new_callable=AsyncMock),
            pytest.raises(ConnectboxAuthenticationError),
        ):
            await client.async_validate_credentials()

    @pytest.mark.asyncio
    async def test_validate_credentials_connection_error(self) -> None:
        """Test credential validation with connection error."""
        client = ConnectboxApiClient("192.168.100.1", "password")
        with (
            patch.object(
                client,
                "_async_login",
                side_effect=ConnectboxConnectionError("Timeout"),
            ),
            patch.object(client, "_async_logout", new_callable=AsyncMock),
            pytest.raises(ConnectboxConnectionError),
        ):
            await client.async_validate_credentials()

    @pytest.mark.asyncio
    async def test_get_docsis_status_success(self) -> None:
        """Test successful DOCSIS status fetch."""
        client = ConnectboxApiClient("192.168.100.1", "password")
        mock_status = DocsisStatus(operational="Operational")
        with (
            patch.object(
                client, "_async_poll", new_callable=AsyncMock, return_value=mock_status
            ),
            patch.object(client, "_async_logout", new_callable=AsyncMock),
        ):
            result = await client.async_get_docsis_status()
            assert result.operational == "Operational"

    @pytest.mark.asyncio
    async def test_get_docsis_status_always_logs_out(self) -> None:
        """Test that logout is called even on error."""
        client = ConnectboxApiClient("192.168.100.1", "password")
        with (
            patch.object(
                client,
                "_async_poll",
                side_effect=ConnectboxConnectionError("fail"),
            ),
            patch.object(
                client, "_async_logout", new_callable=AsyncMock
            ) as mock_logout,
        ):
            with pytest.raises(ConnectboxConnectionError):
                await client.async_get_docsis_status()
            mock_logout.assert_called_once()


class TestExceptionHierarchy:
    """Test exception class hierarchy."""

    def test_timeout_is_connection_error(self) -> None:
        assert issubclass(ConnectboxTimeoutError, ConnectboxConnectionError)

    def test_auth_error_is_not_connection_error(self) -> None:
        assert not issubclass(ConnectboxAuthenticationError, ConnectboxConnectionError)
