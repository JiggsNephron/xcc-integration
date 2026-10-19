# AC Heating XCC Heat Pump Controller Integration

Home Assistant integration for AC Heating XCC heat pump controllers with photovoltaic integration. Monitor and control your heat pump system directly from Home Assistant with automatic entity discovery and bilingual support.

Inspired by work in https://github.com/Pdobry/xcc-graph.

## 🏠 Home Assistant Integration Features

- 🔧 **470+ settable fields** automatically discovered across 8 configuration pages
- 📊 **Live data monitoring** with real-time sensor values
- 🌐 **Bilingual support** (English/Czech with auto-detection)
- 📋 **Organized by device** (heating, PV, hot water, auxiliary source, etc.)

## 📦 HACS Installation

1. **Add Custom Repository**:
   - Open HACS in Home Assistant
   - Click the 3 dots (⋮) → "Custom repositories"
   - Add repository: `https://github.com/pvyleta/xcc-integration`
   - Category: `Integration`

2. **Install Integration**:
   - Go to HACS > Integrations
   - Search for "XCC Heat Pump Controller"
   - Click "Download" and restart Home Assistant

3. **Configure Integration**:
   - Settings > Devices & Services > "Add Integration"
   - Search for "XCC Heat Pump Controller"
   - Enter your XCC controller details

## 🔧 Development & Testing

### Optional read-only Modbus telemetry

Version 1.15.30 targets Home Assistant 2026.10 or newer and uses its compatible
PyModbus dependency (minimum 3.13.1), allowing Home Assistant to update it.
Modbus telemetry is **off by default**. Enable it in the XCC integration's
Configure options (or during initial setup). The polling interval is independent
of web polling: default 15 seconds, configurable from 10 to 3600 seconds.
It uses the configured controller IP, TCP port 502, and fixed unit ID 1.

**The controller supports one active Modbus TCP connection. Stop any existing
YAML hub or other Modbus client for this controller before enabling this option.**
Web access is separate and can remain in use.

The initial sensor set is:

| Suggested entity ID | Holding register | Decode |
| --- | --- | --- |
| `sensor.xcc_modbus_flow_temperature` | 1 | signed 16-bit / 100, °C |
| `sensor.xcc_modbus_return_temperature` | 284 | signed 16-bit / 100, °C |
| `sensor.xcc_modbus_water_flow_rate` | 360 | unsigned 16-bit / 100, m³/h |

Entities use measurement state class and belong to the existing XCC device.
They use raw readings: no temperature offsets, inferred heat output, or COP
corrections are applied. Register availability and physical probe installation
depend on the controller firmware and installation.

Web and Modbus use separate coordinators, availability states, connections and
polling intervals. A failed Modbus read does not block web controls. If the web
interface is unavailable during startup, Modbus entities still load and the web
platforms are added when web discovery recovers, without replacing the Modbus
connection. With Modbus enabled, initial web discovery is bounded to 60 seconds;
web-only startup retains its existing timeout behaviour.

#### One-off read diagnostics

The administrator-only `xcc.read_modbus` action returns a response through the
**existing** serialized connection. It cannot write registers or coils and does
not create permanent entities. Telemetry must be enabled first.

For example, to inspect the documented DHW return probe:

```yaml
action: xcc.read_modbus
data:
  entry_id: YOUR_XCC_CONFIG_ENTRY_ID
  register_type: holding
  address: 285
  count: 1
  signed: true
  scale: 100
response_variable: dhw_probe
```

The response includes raw words and decoded values. `scale` is a divisor, not an
offset. Diagnostic addresses are zero-based. Reads support holding/input
registers and coil/discrete-input bits, with at most 32 values per request.
Multi-register values are returned as individual 16-bit words; 32-bit word order
must be interpreted using the device documentation. Arbitrary addresses may be
unsupported. A failed optional diagnostic read does not mark regular telemetry
unavailable. No automatic sweeping of all register addresses is performed.

#### Migrating an existing YAML hub without splitting history

Migration is deliberate; the integration does not remove YAML, delete registry
entries, or edit recorder data automatically.

1. Record the existing entity IDs, units/state classes and all consumers. Keep a
   copy of the old hub configuration and a recorder backup for recovery.
2. Leave XCC Modbus telemetry disabled while installing the integration update.
3. Remove only the old controller hub from the YAML configuration and reload
   Modbus. Confirm its connection is closed and the old entities are no longer
   provided. Do not remove unrelated hubs or purge recorder/history.
4. If the old integration still reserves the entity IDs, remove only those
   unloaded entity-registry entries using HA's supported UI/API. This operation
   requires user confirmation. Do not delete historical recorder/statistics data.
5. Enable XCC Modbus telemetry, then verify the new sensors have exactly the old
   entity IDs (not `_2` suffixes) and matching units/state classes. The new unique
   IDs identify the XCC integration as owner; recorder continuity relies on the
   retained entity IDs. Check history across the handover, including long-term
   statistics, before considering migration complete.
6. Verify existing consumers still work. On failure, disable the new Modbus
   option before restoring the old YAML hub. Never enable both clients at once.

Multiple XCC controllers need distinct entity IDs; the registry may suffix the
suggested IDs for later controllers. Do not overwrite an unrelated entity to
claim an ID. Installing this update by itself does not migrate the YAML sensors.

### Development Setup

1. **Clone the repository:**
   ```bash
   git clone https://github.com/pvyleta/xcc-integration
   cd xcc-integration
   ```

2. **Create virtual environment:**
   ```bash
   python -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   ```

3. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

### Running Tests

The integration includes comprehensive tests to ensure reliability:

```bash
# Run all tests
python -m pytest tests/ -v
```

## 📚 Configuration Pages

The integration automatically discovers entities from these XCC pages:

| Page | Description | Typical Entities |
|------|-------------|------------------|
| **Heating Circuits** | Temperature control, schedules. Every circuit the controller reports as enabled is polled; the first keeps bare `xcc_to_*` names, further circuits are namespaced `xcc_okruh<n>_*` | Temperature sensors, setpoint controls |
| **Photovoltaics** | Battery management, export limits | Power sensors, battery controls |
| **PV Inverter** | Inverter configuration and telemetry | String/phase sensors, inverter settings |
| **Hot Water** | Sanitization, circulation | Water temperature, heating controls |
| **Auxiliary Source** | Backup heating system | Status sensors, operation controls |
| **Spot Pricing** | Dynamic pricing optimization | Price sensors, optimization switches |
| **System Status** | Overall system information | Status sensors, diagnostic data |
| **Heat Pump Settings** | Advanced configuration (discovered dynamically) | Configuration switches, numbers |
| **PV Battery SOC** | Monthly battery state-of-charge target curve | 12 monthly setpoint numbers (%) |

## 🧰 Standalone Tools

The repo root ships a few helper scripts, separate from the integration in `custom_components/xcc/`. They do **not** share code with the integration (auth and page lists are duplicated). Current status:

| Tool | Purpose | Status |
|------|---------|--------|
| `find_hidden_switches.py` | Offline analysis of scraped XML to list hidden `_BOOL_i` switch fields | ✅ Works (needs `fresh_tuv_data/` or `tests/sample_data/`) |
| `xcc_scraper.py` | Download all controller pages to disk | ⚠️ Partially broken — only the inline fallback client path works; the `custom_components/xcc` import path is API-incompatible |
| `xcc_cli.py` | Interactive CLI to browse/search controller fields | ❌ Broken — depends on `field_database.json` and `scripts/analyze_known_pages.py`, neither of which exists in the repo |

These are kept for reference/backup workflows. See [XCC_SCRAPER_README.md](XCC_SCRAPER_README.md) for scraper usage and caveats.

