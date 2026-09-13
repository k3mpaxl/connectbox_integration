"""API client for the Connectbox integration.

Communicates with either of two known Connectbox/Vodafone Station firmware
families, auto-detected from the login page:

* **Compal** — JSON REST API under ``/api/v1/`` (see ``_CompalMixin``).
* **ARRIS/CommScope** — PHP endpoints under ``/php/`` with an
  AES-CCM-encrypted login (see ``_ArrisMixin``).

Both share the same one-concurrent-admin-session model, so each poll does a
full login → fetch → logout cycle on an isolated ``aiohttp.ClientSession``
with ``CookieJar(unsafe=True)`` (required because the modem is addressed by
IP, and a *safe* cookie jar silently drops cookies for IP-address hosts).

Compal login sequence (reverse-engineered from ``/js/login.js``):
------------------------------------------------------------------------

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

ARRIS login sequence (reverse-engineered from ``base_95x.js`` /
``sjclCrypto.js``, verified against a live device):
------------------------------------------------------------------------

1. ``GET /`` — obtain a ``PHPSESSID`` cookie and the login page's embedded
   ``mySalt`` / ``myIv`` / ``currentSessionId`` (hex strings).
2. Derive ``key = PBKDF2-SHA256(password, mySalt, 1000 iters, 128 bits)``
   (raw bytes, not hex).
3. Encrypt ``{"Password": "<password>", "Nonce": "<currentSessionId>"}``
   (UTF-8 bytes) with AES-128-CCM using ``key``, nonce ``myIv`` and
   associated data ``b"loginPassword"``, 128-bit tag. sjcl's CCM mode is
   the standard NIST construction, byte-identical to
   ``cryptography``'s ``AESCCM``.
4. ``POST /php/ajaxSet_Password.php`` (JSON body)
   ``{"EncryptData": "<hex ciphertext>", "Name": "admin",
   "AuthData": "loginPassword"}``.
   Response: ``{"p_status": "...", "p_waitTime": N, "encryptData": "..."}``.
   ``p_status == "Lockout"`` means too many failed attempts;
   ``"Default"`` or a status containing ``"Match"`` means success (the
   modem's own client shows a change-password nag for ``"Default"``, but
   still grants a real session).
5. Decrypt ``encryptData`` (same key/nonce, associated data ``b"nonce"``)
   to get the CSRF nonce, sent as the ``csrfNonce`` header on every
   subsequent request.
6. ``GET /`` again, then ``GET /?status_docsis&mid=StatusDocsis`` — the
   modem ties the session to this exact page-navigation sequence; skipping
   it (or going straight to the data endpoint) gets a "session lost" 400.
7. ``GET /php/status_docsis_data.php`` — HTML fragment with the channel
   data embedded as ``json_dsData``/``json_usData`` JS array literals.
8. ``POST /php/logout.php`` — release the session.
"""

from __future__ import annotations

import asyncio
import binascii
import hashlib
import json
import re
from dataclasses import dataclass, field
from typing import Any

import aiohttp
import yarl
from cryptography.hazmat.primitives.ciphers.aead import AESCCM

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
        self._protocol: str | None = None  # "compal" | "arris"
        # ARRIS-only session state, set by _async_login_arris.
        self._arris_key: bytes | None = None
        self._arris_iv: str | None = None
        self._arris_csrf_nonce: str | None = None

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

        if self._protocol == "arris":
            return await self._async_fetch_arris(session)
        return await self._async_fetch_compal(session)

    async def _async_fetch_compal(self, session: aiohttp.ClientSession) -> DocsisStatus:
        """Fetch DOCSIS status via the Compal ``/api/v1/`` REST endpoint."""
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

        return _parse_docsis_data_compal(raw.get("data") or {})

    async def _async_fetch_arris(self, session: aiohttp.ClientSession) -> DocsisStatus:
        """Fetch DOCSIS status from the ARRIS/CommScope ``/php/`` firmware.

        The session is tied to this exact page-navigation sequence (see
        module docstring, ARRIS step 6-7): a bare GET to the data endpoint
        without first "visiting" the surrounding pages is rejected with a
        "session lost" response, even with a valid csrfNonce.
        """
        try:
            async with asyncio.timeout(TIMEOUT):
                resp = await session.get(
                    self._base_url,
                    headers={**_HEADERS, "Referer": f"{self._base_url}/?status_docsis&mid=StatusDocsis"},
                )
                operational = _extract_js_var(await resp.text(), "_ga.modemConnectionStatus")
            async with asyncio.timeout(TIMEOUT):
                await session.get(
                    f"{self._base_url}/?status_docsis&mid=StatusDocsis",
                    headers={**_HEADERS, "Referer": f"{self._base_url}/"},
                )
            async with asyncio.timeout(TIMEOUT):
                resp = await session.get(
                    f"{self._base_url}/php/status_docsis_data.php",
                    headers={
                        **_HEADERS,
                        "Referer": f"{self._base_url}/?status_docsis&mid=StatusDocsis",
                        "csrfNonce": self._arris_csrf_nonce or "",
                    },
                )
                if resp.status != 200:
                    raise ConnectboxConnectionError(
                        f"DOCSIS status request failed: HTTP {resp.status}"
                    )
                body = await resp.text()
        except TimeoutError as err:
            raise ConnectboxTimeoutError(
                f"Timeout fetching DOCSIS status from {self._host}"
            ) from err
        except aiohttp.ClientError as err:
            raise ConnectboxConnectionError(
                f"Connection error fetching DOCSIS status from {self._host}: {err}"
            ) from err

        if "json_dsData" not in body:
            raise ConnectboxConnectionError(
                "Connectbox session was lost while fetching DOCSIS status"
            )
        return _parse_docsis_data_arris(body, operational)

    async def _async_login(self, session: aiohttp.ClientSession) -> None:
        """Authenticate with the Connectbox, auto-detecting the firmware.

        Compal firmware serves an ``/api/v1/`` REST API; ARRIS/CommScope
        firmware serves ``/php/`` endpoints with an AES-CCM-encrypted
        login (identified by the ``encryptflag`` marker on the login
        page). See the module docstring for both full sequences.
        """
        try:
            # Step 1: Obtain PHPSESSID cookie and inspect the login page.
            async with asyncio.timeout(TIMEOUT):
                resp = await session.get(
                    self._base_url,
                    headers={**_HEADERS, "Referer": f"{self._base_url}/"},
                )
                home_html = await resp.text()

            # Step 2: Set cwd=No cookie (suppresses password-change popup).
            session.cookie_jar.update_cookies(
                {"cwd": "No"},
                response_url=yarl.URL(self._base_url),
            )
        except TimeoutError as err:
            raise ConnectboxTimeoutError(
                f"Timeout during login to {self._host}"
            ) from err
        except aiohttp.ClientError as err:
            raise ConnectboxConnectionError(
                f"Connection error communicating with {self._host}: {err}"
            ) from err

        if "encryptflag" in home_html:
            self._protocol = "arris"
            await self._async_login_arris(session, home_html)
        else:
            self._protocol = "compal"
            await self._async_login_compal(session)

    async def _async_login_compal(self, session: aiohttp.ClientSession) -> None:
        """Complete the Compal login (steps 3-6 of the module docstring)."""
        try:
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
                salt_data = await _async_read_json(resp)

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
                result = await _async_read_json(resp)

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

    async def _async_login_arris(
        self, session: aiohttp.ClientSession, home_html: str
    ) -> None:
        """Complete the ARRIS/CommScope AES-CCM login.

        See the module docstring (ARRIS steps 2-5) for the protocol.
        """
        salt = _extract_js_var(home_html, "mySalt")
        iv = _extract_js_var(home_html, "myIv")
        nonce = _extract_js_var(home_html, "currentSessionId")
        if not salt or not iv or not nonce:
            raise ConnectboxConnectionError(
                "Could not find login encryption parameters on the Connectbox login page"
            )

        key = hashlib.pbkdf2_hmac(
            "sha256", self._password.encode("utf-8"), bytes.fromhex(salt), 1000, 16
        )
        js_data = '{"Password": "' + self._password + '", "Nonce": "' + nonce + '"}'
        aesccm = AESCCM(key, tag_length=16)
        try:
            encrypt_data = aesccm.encrypt(
                bytes.fromhex(iv), js_data.encode("utf-8"), b"loginPassword"
            )
        except Exception as err:
            raise ConnectboxConnectionError(f"Failed to encrypt login payload: {err}") from err

        try:
            async with asyncio.timeout(TIMEOUT):
                resp = await session.post(
                    f"{self._base_url}/php/ajaxSet_Password.php",
                    json={
                        "EncryptData": binascii.hexlify(encrypt_data).decode(),
                        "Name": "admin",
                        "AuthData": "loginPassword",
                    },
                    headers={
                        **_HEADERS,
                        "Content-Type": "application/json",
                        "Origin": self._base_url,
                        "Referer": f"{self._base_url}/",
                        "csrfNonce": "undefined",
                    },
                )
                result = await _async_read_json(resp)
        except TimeoutError as err:
            raise ConnectboxTimeoutError(
                f"Timeout during login to {self._host}"
            ) from err
        except aiohttp.ClientError as err:
            raise ConnectboxConnectionError(
                f"Connection error communicating with {self._host}: {err}"
            ) from err

        status = result.get("p_status", "") if isinstance(result, dict) else ""
        if status == "Lockout":
            raise ConnectboxConnectionError(
                "Connectbox has temporarily locked out logins after too many "
                "failed attempts"
            )
        if status != "Default" and "Match" not in status:
            raise ConnectboxAuthenticationError("Invalid credentials for the Connectbox")
        if status == "Default":
            LOGGER.info(
                "Connectbox still uses its default admin password; "
                "consider changing it in the modem's web interface"
            )

        try:
            csrf_nonce = aesccm.decrypt(
                bytes.fromhex(iv), bytes.fromhex(result["encryptData"]), b"nonce"
            ).decode()
        except Exception as err:
            raise ConnectboxConnectionError(
                f"Failed to decrypt Connectbox login response: {err}"
            ) from err

        self._arris_key = key
        self._arris_iv = iv
        self._arris_csrf_nonce = csrf_nonce

    async def _async_logout(self, session: aiohttp.ClientSession) -> None:
        """Best-effort logout — always called in a finally block."""
        url = (
            f"{self._base_url}/php/logout.php"
            if self._protocol == "arris"
            else f"{self._base_url}/api/v1/session/logout"
        )
        try:
            async with asyncio.timeout(TIMEOUT):
                await session.post(
                    url,
                    data={},
                    headers={**_HEADERS, "Referer": f"{self._base_url}/"},
                )
        except Exception:
            pass


# ------------------------------------------------------------------
# Pure helpers (module-level)
# ------------------------------------------------------------------


async def _async_read_json(resp: aiohttp.ClientResponse) -> Any:
    """Parse a response as JSON, raising ConnectboxConnectionError on failure.

    The modem returns a plain HTML error page (e.g. on HTTP 404/401,
    which happens during a lockout or when the API path is unreachable)
    instead of JSON when a request is rejected. Without this, that would
    crash with an unhandled JSONDecodeError instead of a clear error.
    """
    try:
        return await resp.json(content_type=None)
    except (aiohttp.ContentTypeError, json.JSONDecodeError) as err:
        raise ConnectboxConnectionError(
            f"Unexpected response from Connectbox (HTTP {resp.status}): {err}"
        ) from err


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


def _extract_js_var(html: str, name: str) -> str:
    """Extract a ``[var ]<name> = '<value>';`` string literal from a page."""
    match = re.search(rf"(?:var\s+)?{re.escape(name)}\s*=\s*'([^']*)'", html)
    return match.group(1) if match else ""


def _coerce_number(value: Any) -> float:
    """Coerce a value like ``'135~324'``, ``'7.2/67.2'`` or ``42`` to float.

    ARRIS firmware channel data mixes numeric JSON values (e.g.
    ``39.6``) with strings for ranges (``'135~324'`` MHz for OFDM) and
    dual power readings (``'7.2/67.2'`` dBmV). Only the first component
    is meaningful for our purposes.
    """
    if isinstance(value, (int, float)):
        return float(value)
    if not value:
        return 0.0
    first = re.split(r"[~/]", str(value))[0]
    return _parse_value(first)


def _parse_docsis_data_arris(body: str, operational: str = "") -> DocsisStatus:
    """Parse an ARRIS/CommScope ``status_docsis_data.php`` response.

    The response is an HTML fragment embedding the channel lists as JS
    array literals: ``json_dsData = [...]; json_usData = [...];``.
    ``operational`` comes from the surrounding page's
    ``_ga.modemConnectionStatus`` (the data endpoint itself doesn't
    include it).
    """
    status = DocsisStatus(operational=operational or "Unknown")

    ds_match = re.search(r"json_dsData\s*=\s*(\[.*?\]);", body, re.DOTALL)
    us_match = re.search(r"json_usData\s*=\s*(\[.*?\]);", body, re.DOTALL)

    if ds_match:
        for ch in json.loads(ds_match.group(1)):
            channel_type = ch.get("ChannelType", "")
            channel_id = str(ch.get("ChannelID", ""))
            status.downstream.append(
                DocsisChannel(
                    channel_id=(
                        f"OFDM-{channel_id}" if channel_type == "OFDM" else channel_id
                    ),
                    direction="downstream",
                    channel_type=channel_type,
                    frequency_mhz=_coerce_number(ch.get("Frequency")),
                    power_dbmv=_coerce_number(ch.get("PowerLevel")),
                    snr_db=_coerce_number(ch.get("SNRLevel")),
                    modulation=ch.get("Modulation", ""),
                    locked=ch.get("LockStatus", ""),
                )
            )

    if us_match:
        for ch in json.loads(us_match.group(1)):
            channel_type = ch.get("ChannelType", "")
            channel_id = str(ch.get("ChannelID", ""))
            status.upstream.append(
                DocsisChannel(
                    channel_id=(
                        f"OFDMA-{channel_id}" if channel_type == "OFDMA" else channel_id
                    ),
                    direction="upstream",
                    channel_type=channel_type,
                    frequency_mhz=_coerce_number(ch.get("Frequency")),
                    power_dbmv=_coerce_number(ch.get("PowerLevel")),
                    modulation=ch.get("Modulation", ""),
                    locked=ch.get("LockStatus", ""),
                )
            )

    LOGGER.debug(
        "Parsed %d downstream and %d upstream channels",
        len(status.downstream),
        len(status.upstream),
    )
    return status


def _parse_docsis_data_compal(data: dict[str, Any]) -> DocsisStatus:
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
