# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/).

## [1.1.0] - 2026-09-13

### Added

- Support for Connectbox/Vodafone Station units running **ARRIS/CommScope
  firmware**, which uses a different login protocol (PBKDF2 + AES-CCM over
  `/php/` endpoints) than the original Compal `/api/v1/` REST API. The
  firmware family is now auto-detected on login, so existing Compal setups
  are unaffected.

### Fixed

- A non-JSON error response from the modem (e.g. an HTTP 404/401 error
  page) during login could crash with an unhandled `JSONDecodeError`
  instead of a clear error. This showed up as a confusing "Unknown error"
  in the reauth/reconfigure password form and as a raw traceback in the
  "setup failed, will retry" message. It's now reported as a proper
  connection error.

## [1.0.0] - 2026-04-10

### Added

- Initial release: DOCSIS channel monitoring (power, frequency, SNR,
  modulation, lock status) for Compal Connectbox (CH7465LG, CH7465CE) /
  Vodafone Station cable modems via the local `/api/v1/` REST API.
- Config flow with reauth and reconfigure support.
- Diagnostics with automatic password redaction.
- HACS support.
