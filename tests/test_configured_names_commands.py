"""Offline regressions: controller names and HA service failure boundaries."""
import ast
import asyncio
import logging
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from tests.test_circuit_namespacing import _entity_helpers as helpers
from tests.test_circuit_namespacing import _load_module, parse_xml_entities

ROOT = Path(__file__).parents[1] / "custom_components" / "xcc"


class HomeAssistantError(Exception):
    pass


def method(filename, name, **extras):
    tree = ast.parse((ROOT / filename).read_text(encoding="utf-8"))
    # Multiple number classes now implement the same API. Keep testing the
    # original platform rather than accidentally extracting the duration API.
    scope = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "XCCNumber") if filename == "number.py" else tree
    node = next(n for n in ast.walk(scope) if isinstance(n, ast.AsyncFunctionDef) and n.name == name)
    namespace = {"HomeAssistantError": HomeAssistantError, "_LOGGER": logging.getLogger(__name__), **extras}
    exec(compile(ast.Module(body=[node], type_ignores=[]), filename, "exec"), namespace)
    return namespace[name]


@pytest.mark.parametrize("index,name", [(0, "Ground floor"), (1, "Bedrooms"), (12, "Annexe")])
def test_page_names_not_block_indices(index, name):
    prop = "TO-TEP" if index == 0 else f"OKRUH{index}-TO-TEP"
    config = {"friendly_name_en": "Temperature"}
    result = helpers.configured_name_config(prop, f"OKRUH1{index}.XML", config,
        {f"PAGE-OKRUH1{index}-PAGENAME": name, f"B{index}-CONFIG-NAZEV": "Wrong block"})
    assert result["friendly_name_en"] == f"{name} — Temperature"
    assert config == {"friendly_name_en": "Temperature"}


def test_block_reference_and_missing_name():
    config = {"friendly_name_en": "Pool room", "name_reference": "B4-CONFIG-NAZEV"}
    assert helpers.configured_name_config("H4", "NAST.XML", config,
        {"B4-CONFIG-NAZEV": "Bedrooms"})["friendly_name_en"] == "Bedrooms — Power restriction enabled"
    assert helpers.configured_name_config("E4", "NAST.XML", config, {})["friendly_name_en"] == "Block 4 — Power limit"
    ordinary = {"friendly_name_en": "Outdoor temperature"}
    assert helpers.configured_name_config("OUTDOOR", "STAVJED.XML", ordinary, {}) is ordinary


def test_descriptor_and_data_pipeline():
    parser = _load_module("descriptor_parser", "descriptor_parser.py").XCCDescriptorParser()
    configs = parser._parse_single_descriptor('<page><row prop="B4-CONFIG-NAZEV"><choice prop="H4"><option value="0" text_en="Disabled"/><option value="1" text_en="Enabled"/></choice></row></page>', "nast.xml")
    assert configs["H4"]["name_reference"] == "B4-CONFIG-NAZEV"
    raw = parse_xml_entities('<root><INPUT P="B4-CONFIG-NAZEV" VALUE="Bedrooms"/><INPUT P="H4" VALUE="1"/></root>', "NAST1.XML")
    _, metadata = helpers.process_entities(raw, configs, language="english")
    assert metadata["xcc_h4"]["descriptor_config"]["friendly_name_en"] == "Bedrooms — Power restriction enabled"
    assert metadata["xcc_h4"]["prop"] == "H4"


@pytest.mark.parametrize("existing,expected", [(None, False), ("My custom label", False), ("Old generated", True)])
def test_registry_custom_names_preserved(existing, expected):
    registry = SimpleNamespace(async_get=Mock(return_value=SimpleNamespace(name=existing)), async_update_entity=Mock())
    entity = SimpleNamespace(hass=None, entity_id="sensor.stable_id",
        _entity_data={"descriptor_config": {"configured_name": True, "legacy_generated_names": ["Old generated"]}})
    asyncio.run(method("entity.py", "_update_entity_registry_name", er=SimpleNamespace(async_get=lambda _: registry))(entity))
    assert registry.async_update_entity.called == expected
    if expected:
        registry.async_update_entity.assert_called_once_with("sensor.stable_id", name=None)


@pytest.mark.parametrize("filename,name,args", [
    ("number.py", "async_set_native_value", (20.5,)),
    ("select.py", "async_select_option", ("Enabled",)),
    ("switch.py", "_async_set_state", (True,)),
    ("button.py", "async_press", ()),
])
@pytest.mark.parametrize("outcome", [False, True, OSError("offline"), asyncio.CancelledError()])
def test_command_outcomes(filename, name, args, outcome):
    command = AsyncMock()
    if isinstance(outcome, BaseException):
        command.side_effect = outcome
    else:
        command.return_value = outcome
    coordinator = SimpleNamespace(async_set_entity_value=command, async_set_value=command, async_request_refresh=AsyncMock())
    entity = SimpleNamespace(name="Test", _prop="H4", _entity_data={"entity_id": "xcc_h4", "prop": "H4"},
        _option_to_value={"Enabled": "1"}, _button_value="1", coordinator=coordinator,
        _attr_is_on=False, async_write_ha_state=Mock())
    call = method(filename, name)(entity, *args)
    if outcome is True:
        asyncio.run(call)
    else:
        error = asyncio.CancelledError if isinstance(outcome, asyncio.CancelledError) else HomeAssistantError
        with pytest.raises(error):
            asyncio.run(call)
        coordinator.async_request_refresh.assert_not_called()
        entity.async_write_ha_state.assert_not_called()
        assert entity._attr_is_on is False
    command.assert_awaited_once()
