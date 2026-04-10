"""Diagnostics support for the Connectbox integration."""

from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.const import CONF_PASSWORD
from homeassistant.core import HomeAssistant

from .coordinator import ConnectboxConfigEntry

TO_REDACT = {CONF_PASSWORD}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant,
    entry: ConnectboxConfigEntry,
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    coordinator = entry.runtime_data
    data = coordinator.data

    channel_data: dict[str, Any] = {}
    if data is not None:
        channel_data = {
            "operational": data.operational,
            "downstream_count": len(data.downstream),
            "upstream_count": len(data.upstream),
            "downstream": [
                {
                    "channel_id": ch.channel_id,
                    "channel_type": ch.channel_type,
                    "frequency_mhz": ch.frequency_mhz,
                    "power_dbmv": ch.power_dbmv,
                    "snr_db": ch.snr_db,
                    "modulation": ch.modulation,
                    "locked": ch.locked,
                }
                for ch in data.downstream
            ],
            "upstream": [
                {
                    "channel_id": ch.channel_id,
                    "channel_type": ch.channel_type,
                    "frequency_mhz": ch.frequency_mhz,
                    "power_dbmv": ch.power_dbmv,
                    "modulation": ch.modulation,
                    "locked": ch.locked,
                }
                for ch in data.upstream
            ],
        }

    return {
        "config_entry": async_redact_data(entry.as_dict(), TO_REDACT),
        "docsis_data": channel_data,
    }
