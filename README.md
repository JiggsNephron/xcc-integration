# AC Heating XCC for Home Assistant — combined fork

Monitor and control an AC Heating XCC heat-pump controller locally from Home
Assistant, with separate heating-circuit entities, native controls and optional
read-only Modbus measurements.

This is the **JiggsNephron community fork** of
[pvyleta/xcc-integration](https://github.com/pvyleta/xcc-integration), based on
upstream **1.16.2** with the additions below. It is not an AC Heating/Teco
vendor-supported integration. Credit to the upstream contributors and the
earlier [xcc-graph project](https://github.com/Pdobry/xcc-graph).

**Current integration release: [v1.16.2.post2](https://github.com/JiggsNephron/xcc-integration/releases/tag/v1.16.2.post2).**
See the [release history](https://github.com/JiggsNephron/xcc-integration/releases)
and [integration changelog](INTEGRATION_CHANGELOG.md) for exact changes.

## What this fork adds

- **Native schedule controls:** edit verified weekly zone/DHW attenuation
  periods, sanitation start time and scheduled DHW temperature-raising times
  using HA time entities. Existing schedule sensors remain available.
- **Heating-curve controls:** per-circuit shift and twelve outside/water
  temperature pairs, with writes routed to the correct curve page.
- **Better numeric controls:** descriptor-aware steps and limits, including
  0.1°C room/DHW targets and supported temperature/hysteresis fields; minute-based
  editors for selected durations rather than treating them as clock times.
- **Independent circuit status:** separate demand/activity, attenuation and
  influence readings for each enabled circuit, without merging similarly named
  registers from different circuits.
- **DHW sanitation visibility:** a read-only active-cycle indicator and an
  explicit Stop action alongside the existing Run action.
- **Controller fault diagnostics:** named current faults and a fault count,
  with observed activation/clearance logged. Notifications remain your own
  automations; this does not import the controller's historical error log.
- **Optional read-only Modbus:** flow temperature, return temperature and water
  flow rate on an independent polling loop, plus a bounded diagnostic-read action
  using the same connection. No Modbus writes are exposed.
- **Clearer names and grouping:** English/Czech support, names taken from each
  circuit's controller configuration, logical device groups, and corrections to
  units and status-versus-control classification.
- **Visible command failures:** unsuccessful writes raise HA errors rather than
  appearing successful. A communication error means the command was not
  confirmed, not proof that the controller did not apply it.
- **Current login-page compatibility:** recognise both legacy XML and modern
  HTML login forms, recover expired sessions, and reject authentication failures
  instead of parsing login HTML as measurements.

The fork also retains upstream fixes for deterministic discovery, circuit
namespacing, per-page polling timeouts and current HA device-parent links.
The available entities depend on the pages/features enabled on your controller;
not every installation exposes every control.

Details: [web controls](docs/web-control-parity.md),
[fault diagnostics](docs/system-faults.md),
[names and command errors](docs/names-and-command-errors.md), and
[earlier parity/migration fixes](docs/audit-fixes.md). These documents include
dated implementation notes; use the release changelog for the current version.

## Requirements

- **Home Assistant 2026.10 or newer.** The store metadata declares this minimum;
  the integration uses a compatible PyModbus dependency (minimum 3.13.1).
- A locally reachable XCC controller, its IP address and web credentials.
  A stable address/DHCP reservation is useful. Do not expose the controller's
  HTTP interface directly to the internet.
- Supported controller pages/firmware. Start with web access; Modbus is optional
  and disabled by default.

## Install this fork

### New installations

1. In **Marketplace** (current HA) or **HACS** (older installations), add
   `https://github.com/JiggsNephron/xcc-integration` as a **custom repository**,
   category **Integration**. Accept the store warning if prompted.
2. Find **AC Heating XCC Heat Pump Controller** and check that the repository
   owner is **JiggsNephron**. Download a tagged release, not an experimental branch.
3. Restart Home Assistant to load the integration.
4. Go to **Settings → Devices & Services → Add Integration**, search for
   **XCC Heat Pump Controller**, and enter the controller IP and credentials.
5. Choose English or Czech and a web polling interval (default **120 seconds**).
   Leave **entity-ID regeneration off** unless deliberately migrating legacy IDs.
6. Check the readings before using controls. If enabling Modbus, read the
   single-connection warning below first. Verify schedules and curves against
   the controller UI before changing heating settings.

### Existing XCC users: read before switching

**The upstream integration and this fork both use domain `xcc` and folder
`custom_components/xcc`. They are alternatives, not integrations to install
side by side.** Two store records do not mean two independent installations.

- Back up HA and record your existing entity IDs and important consumers before
  switching repositories or updating from an older version.
- Keep the existing XCC config entry. Do not delete/re-add it as a routine update,
  enable ID regeneration, or delete registry entries to make an update install.
- If the store reports a repository/folder ownership conflict, stop and resolve
  ownership first. Blindly uninstalling either repository can remove the shared
  integration files. There is no universal automatic repository-switch procedure
  provided by this fork.
- After installation and restart, check the store's installed version, entity
  availability/IDs, schedules and existing automations. Do not overwrite this
  fork with an update from an old upstream store record.
- Current fork updates are designed to retain established entity identities.
  Older releases did correct some domains and page-specific schedule identities;
  a switch from another version is **not** a blanket guarantee of identical IDs.
  Review the [changelog](INTEGRATION_CHANGELOG.md) and
  [migration notes](docs/audit-fixes.md) for your starting version.

### Versions and upstream relationship

Fork releases use **`<upstream baseline>.post<N>`**: `1.16.2.post2` is this fork's
second post-release based on upstream 1.16.2. The post number advances for fork
changes; the baseline advances when newer upstream changes are incorporated.
These are regular Python/HA post-release versions, not prereleases. The manifest
and release tag match. Documentation-only commits on `main` do not imply a new
integration release or require an HA update.

Use the [upstream repository](https://github.com/pvyleta/xcc-integration) for the
original project and this fork's [issues](https://github.com/JiggsNephron/xcc-integration/issues)
for fork-specific problems. Clean upstream contributions are kept separate from
the combined fork changes.

## Optional read-only Modbus telemetry

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

Entities use measurement state class and are grouped under the controller's
**Unit Status** device.
The sensors expose raw controller-register values. Register availability and
interpretation depend on the controller firmware.

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

## Development and testing

### Development setup

1. **Clone the repository:**
   ```bash
   git clone https://github.com/JiggsNephron/xcc-integration.git
   cd xcc-integration
   ```

2. **Create virtual environment:**
   ```bash
   python -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   ```

3. **Install dependencies:**
   ```bash
   pip install -r tests/requirements-test.txt
   ```

### Running Tests

The lightweight suite runs without Home Assistant; HA-dependent tests are
skipped. Use UTF-8 mode on Windows for the non-ASCII XML fixtures:

```bash
# Run all tests
python -X utf8 -m pytest tests/ -q
```

For the full suite, use a Python version supported by the pinned Home Assistant
in `requirements-dev.txt`, install that file, and run the same tests. CI runs
lightweight Python 3.11/3.12/3.13 jobs and a full HA job on Python 3.14. Tagged
releases are published only after the core CI jobs pass.

For `v1.16.2.post2`, full HA CI passed **554 tests** (7 skipped). Regression tests
cover session handling, circuit/page routing, entity metadata, native controls,
fault decoding and Modbus isolation. Tests use fixtures/mocked writes, not live
heating commands; passing tests does not establish compatibility with every
controller firmware or prove measurement accuracy.

## Limitations and troubleshooting

- Web data is polled, not pushed. Short-lived controller faults between polls
  can be missed; the fault sensor is not a replacement for controller protections.
- Native attenuation schedules describe **attenuation start/end**, not direct
  heating-on/off periods. Selected duration editors support 0–1439 minutes; this
  is an editor limit, not a claim about the PLC's hardware limit.
- Some entities may be unavailable when their feature/page is unsupported or
  disabled. Do not interpret missing diagnostics as a clear fault state.
- A known deprecation warning remains in the optional Modbus parent-device
  lookup on current HA; HA reports a removal deadline of 2027.8. The modern
  web-device `via_device_id` links are already supported.
- The separate HACS publication validator currently flags the repository's
  missing `LICENSE` file. Do not confuse that catalogue/publication check with
  the core test suite or claim that this fork is an officially approved listing.

When reporting a problem, include the exact fork version, HA version, controller
firmware (if known), whether web/Modbus is affected and relevant sanitised logs.
Never post passwords, cookies, session files or an unsanitised controller scrape.

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

