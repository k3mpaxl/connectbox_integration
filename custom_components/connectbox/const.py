"""Constants for the Connectbox integration."""

from __future__ import annotations

import logging
from typing import Final

from homeassistant.const import Platform

DOMAIN: Final = "connectbox"
LOGGER = logging.getLogger(__package__)

PLATFORMS: Final = [Platform.SENSOR]

# Defaults
DEFAULT_HOST: Final = "192.168.100.1"
DEFAULT_SCAN_INTERVAL: Final = 60

# Manufacturer info
MANUFACTURER: Final = "Compal"
MODEL: Final = "Connectbox"
