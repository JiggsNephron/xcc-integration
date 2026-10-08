# Web-interface control parity

This additive update starts from the tested 1.15.27 combined branch. It does not
rename/delete the existing diagnostic sensors or change controller settings on
startup. New controls are populated from live controller values.

## Native controls

- `time.xcc_page_okruh10_us_mon_ton1` (and equivalent weekdays/periods/circuits):
  attenuation start; TOFF is attenuation end, not a heating activation schedule.
  Cross-midnight periods remain valid; no time ordering is imposed.
- `time.xcc_tsc_cas`: sanitation start time.
- `time.xcc_tuvtps_day10_ontime` (when supplied by the controller): timed DHW
  temperature-raising start. Its enable switches/settings are on TUV13.XML.
- `number.xcc_to_adaptace_docasnebezcidlacas_minutes` and secondary-circuit
  equivalents: elapsed minutes, not a wall-clock time.
- `number.xcc_tuvmaximalnidobanatapeni_minutes` and
  `number.xcc_tuvdobaklidu_minutes`: elapsed minutes. These editors conservatively
  support 0–1439 minutes; old duration sensors remain available for readings
  outside this range. This is an editor restriction, not a discovered PLC limit.
- `number.xcc_to_posun`, `number.xcc_to_ek00` / `number.xcc_to_ek01`, etc.:
  curve shift and outside/water pairs. The second circuit uses `okruh1_`.
- `button.xcc_main_priorizatorspotreby_prituv_sanitace_stop`: explicit Stop.
  The original button remains Run. Neither action is executed by setup/tests.

## Routing and compatibility

Curve pages OKRUH2&lt;index&gt;.XML share a circuit identity with
OKRUH1&lt;index&gt;.XML. Only curve fields are admitted from group 2, avoiding
unexpected floor-curing controls. Circuit 0 keeps bare TO fields; higher circuits
keep OKRUH&lt;index&gt; namespacing. Current circuit names come from group 1.

Existing PAGE schedule sensors stay read-only. New time controls use the
same qualified property and register address, resolving PAGE aliases back to
the owning data page only for verified US weekday/period fields. PAGENAME and
unverified PAGE aliases cannot be written.

Precision comes from explicit descriptor step/digits first, then the native
REAL format for verified temperature fields. Existing 0.1°C primary targets
remain supported. Missing bounds are not guessed.

## Validation / installation

Offline regression tests use mocked POSTs for each zone/page and action value.
The local lightweight suite skips tests requiring Home Assistant; full HA CI
must run before a published release. No live command is used as a test.

Install through a versioned HACS release, then reload/restart the integration
with user approval. Confirm the new controls read correctly before editing them.
Rollback target is v1.15.27; old sensors, automations and history are retained.
