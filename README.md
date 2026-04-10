# Connectbox DOCSIS Monitor

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://github.com/hacs/integration)

Home Assistant integration for monitoring [Compal Connectbox](https://www.compal.com/) (also marketed as **Vodafone Station**) cable modems via their local JSON REST API.

## Supported devices

| Manufacturer | Model | Firmware |
|---|---|---|
| Compal | Connectbox (CH7465LG, CH7465CE) | Tested with current Vodafone firmware |

The integration communicates **locally** with the modem at its default IP address `192.168.100.1`. No cloud connection is required.

## Features

- **DOCSIS channel monitoring** — real-time metrics for all downstream and upstream channels:
  - Signal power (dBmV)
  - Frequency (MHz)
  - Signal-to-Noise Ratio (dB) — downstream only
  - Modulation type (e.g. 256QAM, 4096QAM) — disabled by default
  - Lock/Ranging status — disabled by default
- **Channel types** — supports SC-QAM, OFDM (downstream), and OFDMA (upstream)
- **Operational status** — overall DOCSIS link state
- **Configurable polling interval** — default 60 seconds, adjustable 30–3600 seconds
- **Diagnostics** — full channel data export with automatic password redaction
- **Reauth & reconfigure flows** — seamless credential and host updates

## Installation

### HACS (recommended)

1. Open HACS in Home Assistant.
2. Go to **Integrations** → **⋮** → **Custom repositories**.
3. Add `https://github.com/k3mpaxl/connectbox_integration` as an **Integration**.
4. Search for **Connectbox DOCSIS Monitor** and install it.
5. Restart Home Assistant.

### Manual installation

1. Copy the `custom_components/connectbox` folder into your Home Assistant `config/custom_components/` directory.
2. Restart Home Assistant.

## Configuration

1. Go to **Settings** → **Devices & services** → **Add integration**.
2. Search for **Connectbox**.
3. Enter the modem IP address (default: `192.168.100.1`) and admin password.

### Configuration parameters

| Parameter | Description | Default |
|---|---|---|
| Host | IP address of the Connectbox modem | `192.168.100.1` |
| Password | Admin password for the modem web interface | *(required)* |

### Options

| Parameter | Description | Default | Range |
|---|---|---|---|
| Update interval | Polling interval in seconds | 60 | 30–3600 |

To change options: **Settings** → **Devices & services** → **Connectbox** → **⚙ Configure**.

## Data updates

The integration uses **local polling** to retrieve DOCSIS channel data. Each poll cycle performs a full login → fetch → logout sequence because the modem firmware allows only **one concurrent admin session**.

A typical poll cycle takes 7–8 seconds due to the multi-step authentication protocol:

1. Establish session cookie (`GET /`)
2. Request cryptographic salts (`POST /api/v1/session/login`)
3. Compute PBKDF2-SHA256 double-hash and authenticate
4. Activate session (`GET /api/v1/session/menu`)
5. Fetch DOCSIS data (`GET /api/v1/sta_docsis_status`)
6. Logout (`POST /api/v1/session/logout`)

### Entities

For a typical DOCSIS 3.1 modem with 24 SC-QAM + 2 OFDM downstream channels and 4 SC-QAM + 1 OFDMA upstream channels, the integration creates **~150 sensor entities**:

| Sensor | Per channel | Directions | Category | Enabled by default |
|---|---|---|---|---|
| Power | ✓ | DS + US | — | ✓ |
| Frequency | ✓ | DS + US | — | ✓ |
| SNR | ✓ | DS only | Diagnostic | ✓ |
| Modulation | ✓ | DS + US | Diagnostic | ✗ |
| Lock status | ✓ | DS + US | Diagnostic | ✗ |
| Operational status | ✗ (1 total) | — | — | ✓ |

## Example use cases

### Monitor signal quality

Use the downstream SNR and power sensors to monitor your cable connection quality over time. Create a history graph card on your dashboard to spot degradation patterns:

```yaml
type: history-graph
entities:
  - entity_id: sensor.connectbox_ds_channel_1_snr
  - entity_id: sensor.connectbox_ds_channel_1_power
hours_to_show: 48
```

### Alert on signal loss

Trigger a notification when a downstream channel loses lock:

```yaml
automation:
  - alias: "Connectbox channel unlock alert"
    triggers:
      - trigger: state
        entity_id: sensor.connectbox_operational_status
        from: "Operational"
    actions:
      - action: notify.mobile_app
        data:
          title: "Connectbox"
          message: "DOCSIS link is no longer operational: {{ states('sensor.connectbox_operational_status') }}"
```

### Track upstream power levels

High upstream power levels can indicate cable plant issues. Create a threshold automation:

```yaml
automation:
  - alias: "Connectbox high upstream power"
    triggers:
      - trigger: numeric_state
        entity_id: sensor.connectbox_us_channel_1_power
        above: 50
        for:
          minutes: 10
    actions:
      - action: persistent_notification.create
        data:
          title: "High upstream power"
          message: "Upstream channel 1 power is {{ states('sensor.connectbox_us_channel_1_power') }} dBmV — check cable connections."
```

## Authentication protocol

The integration reverse-engineered the authentication protocol from the modem's `login.js`. Key details:

- **PBKDF2-SHA256 double-hash**: The modem provides stable and per-request salts. The password is hashed twice using PBKDF2-SHA256 (1000 iterations, 128-bit output).
- **Factory-reset state**: When `salt == "none"`, the modem expects a plaintext password (first-boot/factory-reset).
- **Default password detection**: A successful login with `Dpd == "Yes"` indicates the default password is still active.
- **Session exclusivity**: Only one admin session is allowed. The integration sends `logout=true` with the salt request to terminate stale sessions.

## Troubleshooting

1. [Enable debug logging](https://www.home-assistant.io/docs/configuration/troubleshooting/#enabling-debug-logging) for the `connectbox` integration.
2. Reproduce the issue.
3. [Disable debug logging and download logs](https://www.home-assistant.io/docs/configuration/troubleshooting/#disable-debug-logging-and-download-logs).

### Common issues

| Problem | Cause | Solution |
|---|---|---|
| "Cannot connect" during setup | Modem IP unreachable | Ensure HA host is on the modem's LAN (usually `192.168.100.0/24`) |
| "Invalid authentication" | Wrong password | Use the admin password from the modem's label or web interface |
| "Another user already logged in" | Stale session on modem | Wait 1–2 minutes for the session to expire, or reboot the modem |
| Sensors unavailable after working | Session conflict | Another device/browser is logged into the modem web interface — close it |
| Default password warning in logs | `Dpd=Yes` from modem | Change the admin password in the modem's web interface |
| All sensor values are 0 | Session not activated | This is handled by the integration; if persistent, check firmware version |

## Known limitations

- The modem allows only **one concurrent admin session**. While the integration is polling, you cannot use the modem's web interface simultaneously (and vice versa).
- Each poll cycle takes **7–8 seconds** due to the multi-step authentication protocol. Setting the scan interval below 30 seconds is not recommended.
- The integration currently monitors **DOCSIS channel data only**. Other modem features (WiFi, DHCP, firmware updates) are not supported.
- Only the **admin** user account is supported.

## Removing the integration

This integration follows standard integration removal. Go to **Settings** → **Devices & services** → **Connectbox** → **⋮** → **Delete**.

## Contributing

Contributions are welcome! Please open an issue or pull request on [GitHub](https://github.com/k3mpaxl/connectbox_integration).

## License

This project is licensed under the MIT License.
