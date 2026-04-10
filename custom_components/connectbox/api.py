"""API client for the Connectbox integration.

Communicates with the Compal Connectbox (Vodafone Station) JSON REST API
at ``/api/v1/``.

Authentication protocol (reverse-engineered from ``/js/login.js``):
------------------------------------------------------------------------

The modem allows **one concurrent admin session**.  Each API poll therefore
performs a full login → fetch → logout cycle using an isolated
``aiohttp.ClientSession`` with ``CookieJar(unsafe=True)`` (required
because the modem is addressed by IP, and a *safe* cookie jar silently
drops cookies for IP-address hosts).

Login sequence (``submitFun`` in login.js):

1. ``GET /`` — obtain a ``PHPSESSID`` session cookie.
2. Set cookie ``cwd=No`` (suppresses the "change default password" popup).
3. ``POST /api/v1/session/login`` with ``password=seeksalthash`` and
   ``logout=true``.
   - ``logout=true`` terminates any existing session first (prevents
     MSG_LOGIN_150 "user already logged in").
   - Response on success: ``{"error":"ok", "salt":"…", "saltwebui":"…"}``.
   - If ``salt`` is ``"none"`` the modem expects the plaintext password
     (factory-reset / first-boot state).
4. Derive the login token (when ``salt != "none"``):
   - ``hash1 = PBKDF2-SHA256(password, salt, 1000 iters, 128 bits)`` → hex
   - ``hash2 = PBKDF2-SHA256(hash1, saltwebui, 1000 iters, 128 bits)`` → hex
   (see ``doPbkdf2NotCoded`` in login.js using sjcl)
5. ``POST /api/v1/session/login`` with ``password=<hash2|plaintext>``.
   Possible responses:

   +--------------+------------------+--------------------------------------------+
   | ``error``    | ``message``      | Meaning                                    |
   +==============+==================+============================================+
   | ``"ok"``     | ``MSG_LOGIN_1``  | **Login successful.**                      |
   |              |                  | ``data.Dpd=="Yes"`` → default password     |
   |              |                  | still active (login.js shows change-popup).|
   |              |                  | ``data.uid`` → user role (1=admin, 3=…).   |
   +--------------+------------------+--------------------------------------------+
   | ``"error"``  | ``MSG_LOGIN_1``  | **Wrong credentials.**                     |
   |              |                  | ``data.failedAttempts`` = lockout seconds.  |
   +--------------+------------------+--------------------------------------------+
   | ``"error"``  | ``MSG_LOGIN_150``| **Another user already logged in.**        |
   |              |                  | (Prevented by ``logout=true`` in step 3.)  |
   +--------------+------------------+--------------------------------------------+
   | HTTP 401     |                  | **Too many failed attempts** (lockout).    |
   +--------------+------------------+--------------------------------------------+

6. ``GET /api/v1/session/menu`` — **required** to activate the session;
   without this call subsequent API requests return empty data.
7. ``GET /api/v1/sta_docsis_status`` — the actual DOCSIS channel data.
8. ``POST /api/v1/session/logout`` — release the session.
"""

from __future__ import annotations

import asyncio
import binascii
import hashlib
from dataclasses import dataclass, field
from typing import Any

import aiohttp
import yarl

from .const import LOGGER

TIMEOUT = 15

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/26.4 Safari/605.1.15"
    ),
    "X-Requested-With": "XMLHttpRequest",
    "Accept": "*/*",
}


# ------------------------------------------------------------------
# Exceptions
# ------------------------------------------------------------------


class ConnectboxConnectionError(Exception):
    """Raised when communication with the Connectbox fails."""


class ConnectboxAuthenticationError(Exception):
    """Raised when authentication with the Connectbox fails."""


class ConnectboxTimeoutError(ConnectboxConnectionError):
    """Raised when the Connectbox does not respond in time."""


# ------------------------------------------------------------------
# Data models
# ------------------------------------------------------------------


@dataclass
class DocsisChannel:
    """Representation of a single DOCSIS channel."""

    channel_id: str
    direction: str  # "downstream" | "upstream"
    channel_type: str  # "SC-QAM" | "OFDM" | "OFDMA"
    frequency_mhz: float = 0.0
    power_dbmv: float = 0.0
    snr_db: float | None = None
    modulation: str = ""
    locked: str = ""


@dataclass
class DocsisStatus:
    """Parsed DOCSIS status from the Connectbox."""

    operational: str = "Unknown"
    downstream: list[DocsisChannel] = field(default_factory=list)
    upstream: list[DocsisChannel] = field(default_factory=list)


# ------------------------------------------------------------------
# Client
# ------------------------------------------------------------------


class ConnectboxApiClient:
    """API client for the Connectbox cable modem."""

    def __init__(self, host: str, password: str) -> None:
        """Initialise the client."""
        self._host = host
        self._password = password
        self._base_url = f"http://{host}"

    @property
    def host(self) -> str:
        """Return the host address."""
        return self._host

    # -- Public API -------------------------------------------------

    async def async_get_docsis_status(self) -> DocsisStatus:
        """Fetch DOCSIS channel data (login → fetch → logout)."""
        session = aiohttp.ClientSession(
            cookie_jar=aiohttp.CookieJar(unsafe=True),
        )
        try:
            return await self._async_poll(session)
        finally:
            await self._async_logout(session)
            await session.close()

    async def async_validate_credentials(self) -> None:
        """Validate credentials by performing a full login cycle.

        Raises ConnectboxAuthenticationError or ConnectboxConnectionError.
        """
        session = aiohttp.ClientSession(
            cookie_jar=aiohttp.CookieJar(unsafe=True),
        )
        try:
            await self._async_login(session)
        finally:
            await self._async_logout(session)
            await session.close()

    # -- Internal ---------------------------------------------------

    async def _async_poll(self, session: aiohttp.ClientSession) -> DocsisStatus:
        """Run the full login → fetch → parse cycle."""
        await self._async_login(session)

        try:
            async with asyncio.timeout(TIMEOUT):
                resp = await session.get(
                    f"{self._base_url}/api/v1/sta_docsis_status",
                    headers={**_HEADERS, "Referer": f"{self._base_url}/"},
                )
                if resp.status != 200:
                    raise ConnectboxConnectionError(
                        f"DOCSIS status request failed: HTTP {resp.status}"
                    )
                raw = await resp.json(content_type=None)
        except TimeoutError as err:
            raise ConnectboxTimeoutError(
                f"Timeout fetching DOCSIS status from {self._host}"
            ) from err
        except aiohttp.ClientError as err:
            raise ConnectboxConnectionError(
                f"Connection error fetching DOCSIS status from {self._host}: {err}"
            ) from err

        return _parse_docsis_data(raw.get("data") or {})

    async def _async_login(self, session: aiohttp.ClientSession) -> None:
        """Authenticate with the Connectbox.

        Implements the full login sequence documented in the module
        docstring (steps 1-6).
        """
        try:
            # Step 1: Obtain PHPSESSID cookie.
            async with asyncio.timeout(TIMEOUT):
                await session.get(
                    self._base_url,
                    headers={**_HEADERS, "Referer": f"{self._base_url}/"},
                )

            # Step 2: Set cwd=No cookie (suppresses password-change popup).
            session.cookie_jar.update_cookies(
                {"cwd": "No"},
                response_url=yarl.URL(self._base_url),
            )

            # Step 3: Request salts. logout=true terminates other sessions
            # to prevent MSG_LOGIN_150 ("user already logged in").
            async with asyncio.timeout(TIMEOUT):
                resp = await session.post(
                    f"{self._base_url}/api/v1/session/login",
                    data={
                        "username": "admin",
                        "password": "seeksalthash",
                        "logout": "true",
                    },
                    headers={**_HEADERS, "Referer": f"{self._base_url}/"},
                )
                salt_data = await resp.json(content_type=None)

            if salt_data.get("error") != "ok":
                msg = salt_data.get("message", "")
                if msg == "MSG_LOGIN_150":
                    raise ConnectboxConnectionError(
                        "Another user is already logged in to the Connectbox"
                    )
                raise ConnectboxConnectionError(f"Failed to request salts: {salt_data}")

            salt = salt_data.get("salt", "")
            salt_webui = salt_data.get("saltwebui", "")

            # Step 4: Compute login token.
            if salt == "none":
                # Factory-reset state: modem expects plaintext password.
                login_password = self._password
                LOGGER.debug("Salt is 'none' — using plaintext login")
            else:
                if not salt or not salt_webui:
                    raise ConnectboxConnectionError("Empty salt values in response")
                hash1 = _pbkdf2_hash(self._password, salt)
                login_password = _pbkdf2_hash(hash1, salt_webui)

            # Step 5: Login with computed password.
            async with asyncio.timeout(TIMEOUT):
                resp = await session.post(
                    f"{self._base_url}/api/v1/session/login",
                    data={"username": "admin", "password": login_password},
                    headers={**_HEADERS, "Referer": f"{self._base_url}/"},
                )
                result = await resp.json(content_type=None)

            if not isinstance(result, dict) or result.get("error") != "ok":
                msg = result.get("message", "") if isinstance(result, dict) else ""
                if msg == "MSG_LOGIN_150":
                    raise ConnectboxConnectionError(
                        "Another user is already logged in to the Connectbox"
                    )
                raise ConnectboxAuthenticationError(
                    "Invalid credentials for the Connectbox"
                )

            # Log success details.
            data = result.get("data", {})
            dpd = data.get("Dpd", "No")
            LOGGER.debug(
                "Login successful (message=%s, Dpd=%s, uid=%s)",
                result.get("message"),
                dpd,
                data.get("uid"),
            )
            if dpd == "Yes":
                LOGGER.info(
                    "Connectbox still uses the default password; "
                    "consider changing it in the modem's web interface"
                )

            # Step 6: Activate session (required by firmware).
            async with asyncio.timeout(TIMEOUT):
                await session.get(
                    f"{self._base_url}/api/v1/session/menu",
                    headers={**_HEADERS, "Referer": f"{self._base_url}/"},
                )

        except ConnectboxAuthenticationError:
            raise
        except ConnectboxConnectionError:
            raise
        except TimeoutError as err:
            raise ConnectboxTimeoutError(
                f"Timeout during login to {self._host}"
            ) from err
        except aiohttp.ClientError as err:
            raise ConnectboxConnectionError(
                f"Connection error communicating with {self._host}: {err}"
            ) from err

    async def _async_logout(self, session: aiohttp.ClientSession) -> None:
        """Best-effort logout — always called in a finally block."""
        try:
            async with asyncio.timeout(TIMEOUT):
                await session.post(
                    f"{self._base_url}/api/v1/session/logout",
                    data={},
                    headers={**_HEADERS, "Referer": f"{self._base_url}/"},
                )
        except Exception:
            pass


# ------------------------------------------------------------------
# Pure helpers (module-level)
# ------------------------------------------------------------------


def _pbkdf2_hash(password: str, salt: str) -> str:
    """PBKDF2-SHA256 hash matching ``sjcl.misc.pbkdf2(pw, salt, 1000, 128)``.

    Returns the derived key as a lowercase hex string (32 chars / 16 bytes).
    """
    dk = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt.encode("utf-8"),
        1000,
        16,
    )
    return binascii.hexlify(dk).decode()


def _parse_value(value: str) -> float:
    """Parse a value string like ``'674 MHz'`` or ``'6.9 dBmV'`` to float."""
    if not value:
        return 0.0
    cleaned = value.strip()
    for unit in ("MHz", "dBmV", "dB", "Msym/s", "ksym/s", "Hz"):
        cleaned = cleaned.replace(unit, "").strip()
    try:
        return float(cleaned)
    except ValueError:
        return 0.0


def _parse_docsis_data(data: dict[str, Any]) -> DocsisStatus:
    """Parse raw DOCSIS JSON into a typed :class:`DocsisStatus`.

    The Connectbox returns four channel lists:

    * ``downstream`` — SC-QAM downstream channels (key ``channelid``).
    * ``ofdm_downstream`` — OFDM downstream channels (key ``channelid_ofdm``).
    * ``upstream`` — SC-QAM upstream channels (key ``channelidup``).
    * ``ofdma_upstream`` — OFDMA upstream channels (key ``channelidup``).
    """
    status = DocsisStatus(operational=data.get("operational", "Unknown"))

    if not data:
        return status

    # SC-QAM downstream
    for ch in data.get("downstream", []):
        status.downstream.append(
            DocsisChannel(
                channel_id=ch.get("channelid", ""),
                direction="downstream",
                channel_type=ch.get("ChannelType", "SC-QAM"),
                frequency_mhz=_parse_value(ch.get("CentralFrequency", "")),
                power_dbmv=_parse_value(ch.get("power", "")),
                snr_db=_parse_value(ch.get("SNR", "")),
                modulation=ch.get("FFT", ""),
                locked=ch.get("locked", ""),
            )
        )

    # OFDM downstream
    for ch in data.get("ofdm_downstream", []):
        status.downstream.append(
            DocsisChannel(
                channel_id=f"OFDM-{ch.get('channelid_ofdm', '')}",
                direction="downstream",
                channel_type=ch.get("ChannelType", "OFDM"),
                frequency_mhz=_parse_value(ch.get("CentralFrequency_ofdm", "")),
                power_dbmv=_parse_value(ch.get("power_ofdm", "")),
                snr_db=_parse_value(ch.get("SNR_ofdm", "")),
                modulation=ch.get("FFT_ofdm", ""),
                locked=ch.get("locked_ofdm", ""),
            )
        )

    # SC-QAM upstream
    for ch in data.get("upstream", []):
        status.upstream.append(
            DocsisChannel(
                channel_id=ch.get("channelidup", ""),
                direction="upstream",
                channel_type=ch.get("ChannelType", "SC-QAM"),
                frequency_mhz=_parse_value(ch.get("CentralFrequency", "")),
                power_dbmv=_parse_value(ch.get("power", "")),
                modulation=ch.get("FFT", ""),
                locked=ch.get("RangingStatus", ""),
            )
        )

    # OFDMA upstream
    for ch in data.get("ofdma_upstream", []):
        status.upstream.append(
            DocsisChannel(
                channel_id=f"OFDMA-{ch.get('channelidup', '')}",
                direction="upstream",
                channel_type=ch.get("ChannelType", "OFDMA"),
                frequency_mhz=_parse_value(ch.get("CentralFrequency", "")),
                power_dbmv=_parse_value(ch.get("power", "")),
                modulation=ch.get("FFT", ""),
                locked=ch.get("RangingStatus", ""),
            )
        )

    LOGGER.debug(
        "Parsed %d downstream and %d upstream channels",
        len(status.downstream),
        len(status.upstream),
    )
    return status
