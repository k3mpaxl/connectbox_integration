# Sample Dashboards for Connectbox DOCSIS Monitor

These are ready-to-use dashboard configurations for Home Assistant.

## Important: Entity ID naming

Entity IDs depend on your Home Assistant **language setting**:

| Language | Example entity ID |
|---|---|
| English | `sensor.connectbox_ds_channel_1_power` |
| German | `sensor.connectbox_ds_kanal_1_leistung` |

Adjust the entity IDs in the YAML files to match your installation.
You can find your entity IDs under **Settings → Devices & services → Connectbox → Entities**.

## Available dashboards

### 1. Overview (`overview.yaml`)

A compact single-view dashboard showing:
- Operational status
- Downstream signal power and SNR for all channels
- Upstream signal power
- Channel counts

### 2. Signal Monitor (`signal-monitor.yaml`)

A detailed monitoring dashboard with:
- History graphs tracking power and SNR trends over 24h
- Separate sections for downstream and upstream
- OFDM/OFDMA channels highlighted

### 3. Channel Table (`channel-table.yaml`)

A table-style view mimicking the modem's own web interface:
- All downstream channels with power, frequency, SNR
- All upstream channels with power and frequency

## How to use

1. Go to **Settings → Dashboards → Add Dashboard**.
2. Create a new dashboard and switch to YAML mode (⋮ → Raw configuration editor).
3. Paste the contents of the desired YAML file.
4. Replace entity IDs if your HA language is not English.
