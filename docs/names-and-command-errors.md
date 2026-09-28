# Controller names and command failures

Two independently reviewable fixes, based on 1.15.22:

## Configured display names

Use already-fetched page-local PAGENAME values for heating-circuit entities.
Preserve descriptor row references to B<n>-CONFIG-NAZEV for shared block
settings. Block indices and circuit indices are not interchangeable.
No installation-specific Upstairs/Downstairs names are hardcoded. Missing
names fall back to a circuit/block identifier. H/E power-restriction columns
receive explicit feature names instead of the incorrect Pool room label.

Entity IDs, unique IDs and write targets are unchanged. Existing custom HA
registry names are retained. Only registry names exactly matching recognised
legacy generated names are cleared so HA can use the new original name.
A user override identical to an old generated name cannot be distinguished.
Reload the integration after changing controller names to refresh all platform
display names. No additional controller requests are introduced.

## Failed command reporting

Number, select, switch and button service handlers raise HomeAssistantError
when the coordinator returns false or raises an exception, rather than logging
and returning apparent success. Cancellation propagates. Failed switch writes
do not update the displayed state optimistically. Errors deliberately say the
command was not confirmed: a network failure cannot prove it was not applied.

Verification: 160 offline tests passed, including captured descriptor/data
regressions and isolated execution of the actual platform command methods.
No heating commands were sent. Live HA runtime/deployment testing is pending.
