# Controller/HA parity fixes

Based on the September 2026 read-only comparison of controller descriptors,
live registers and HA entities. These changes build on 1.15.20, preserving
the earlier English names, sanitation status, circuit activity, half-degree
setpoints, pump names and separate room/weather influence fixes.

## Review group 1: status versus control

Expose the following indicator-only properties as read-only binary sensors:

| Previous entity suffix | New domain | Meaning |
| --- | --- | --- |
| `xcc_tcrvystup` | `binary_sensor` | DHW circulation running |
| `xcc_bivalence` | `binary_sensor` | Auxiliary source active |
| `xcc_alternativnirezimaktivni` | `binary_sensor` | Alternative mode active |
| `xcc_to_natop_stat_run` and circuit equivalents | `binary_sensor` | Slow heating up active |
| `xcc_tuvexternivystup` | `binary_sensor` | DHW external heating active |

The first four were exposed as switches; external heating was a sensor with
an erroneous hours unit. Actual enable/mode controls are not reclassified.
This is intentionally a verified-property allowlist, not a blanket assumption
that every BOOL register is read-only. In particular MZ and cooling configuration
retain their existing control classification.

Resolved descriptor metadata now survives secondary-circuit processing. This
fixes missing names and prevents raw-register inference overriding a read-only
descriptor inherited from the shared circuit template.

## Review group 2: independent circuit and schedule registers

Namespace the additional circuit-local prioritizer BOOST/ECO/OFF/IGNORED flags,
MZ, room influence options, adaptive min/max and temporary sensor bypass
properties. Circuit zero retains its existing suffix; secondary circuits use
the established `OKRUH<n>-` convention. Global measurements remain shared.

Weekly US/CS/CT schedule snapshots and page identity fields use a distinct
`PAGE-<data page>-<property>` namespace, including circuit zero. For example:

- `sensor.xcc_page_okruh10_us_mon_ton1`
- `sensor.xcc_page_okruh11_us_mon_ton1`
- `sensor.xcc_page_tuv11_us_mon_ton1`
- `sensor.xcc_page_tuv21_us_mon_ton1`

The old bare schedule could contain data from different consumers depending
on discovery order. Its history is not silently assigned to any one circuit.
These new schedule entities remain read-only; schedule editing is not added.

## Review group 3: units, classes and names

- Honour explicit empty units instead of guessing from adjacent fields.
- Do not borrow units from another field or a previous row used for naming.
- Remove blanket percentage-to-power-factor mapping; forecast humidity gets
  humidity class, while unclassified demand/limit percentages remain generic.
- Use protocol numeric types for measurement state class, including unitless
  influence diagnostics. Strings, times, enums and booleans are not numeric
  measurements even if their values look numeric.
- Resolve the adaptive-band number's unit from its own circuit's live selector:
  0 = degrees Celsius, 1 = percent. Unknown selectors leave the unit unset.
- Do not invent a replacement unit for PV temperature uplift where its own
  descriptor omits one. The incorrect inferred watts are removed.

## Migration and deployment

No automatic registry deletion, history rewrite, controller settings change,
dashboard edit or restart is performed by this patch.

Before deployment, search consumers of the old domains/suffixes. Update any
references to the new binary sensors and page-specific schedule entities.
Stale registry entries may remain unavailable after upgrading; remove them
only after checking references and retaining any needed history. Additional
circuit properties now have separate identities; old merged history may have
contained values from another circuit and cannot be reliably repaired.

For the audited installation, HA-MCP config search completed without partial
results across automations, scripts, scenes, helpers and dashboards. No
references to the domain-changing statuses or renamed schedule/identity
entities were found. Existing house-card entities are unchanged. YAML files
outside that search are not covered by this statement.

## Validation

- 134 focused offline tests pass, including the earlier regression tests for
  English names, sanitation, circuit routing, setpoints and influence units.
- The sensor metadata tests execute the real description builder with minimal
  HA type stand-ins; they are not full HA runtime/registry tests.
- A read-only live XML dry run processed 870 entities from ten selected data
  pages and five descriptors, verified all five corrected status types and
  retained four distinct Monday schedule values (08:00, 08:00, 09:00, 00:00).
- That dry run caught a previous-row unit inference path; the correction is
  covered by a regression fixture. A final live repeat hit the controller's
  session limit before reading data, so it was not retried.
- Full HA runtime setup, upgraded registry behaviour and live control writes
  have not been tested. No release has been installed or restart performed.

Suggested PR title: **Fix controller status classification, circuit collisions
and sensor metadata**. Keep the three review groups above as separate sections
or split group 2 into a follow-up PR because of its entity-ID migration impact.
