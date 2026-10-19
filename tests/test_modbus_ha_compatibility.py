"""Compatibility checks against real HA, in addition to offline transport tests."""

from types import SimpleNamespace

import pytest

pytest.importorskip("homeassistant")

from custom_components.xcc import async_setup
from custom_components.xcc.config_flow import XCCOptionsFlowHandler


def test_options_constructor_respects_ha_read_only_config_entry():
    """Modern OptionsFlow.config_entry is managed by HA, not writable by us."""
    entry = SimpleNamespace(data={}, options={})
    handler = XCCOptionsFlowHandler(entry)
    assert handler._entry is entry


async def test_diagnostic_service_registers_with_real_ha(hass):
    """Validate the admin/response registration API, without connecting to XCC."""
    assert await async_setup(hass, {})
    assert hass.services.has_service("xcc", "read_modbus")
