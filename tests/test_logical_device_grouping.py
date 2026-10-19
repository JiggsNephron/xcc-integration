"""Display ownership is independent of discovery order and command routing."""
import ast
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import pytest

from tests.test_circuit_namespacing import _entity_helpers as helpers


@pytest.mark.parametrize("prop,old_group,expected", [
    *[(prop, "FVEINV", None) for prop in (
        "SVENKU", "SNAZEV1", "SNAZEV2", "SCAS", "SCHYBA",
    )],
    ("VERZE", "NAST", None),
    ("SPOTOVECENYSTATS-DATA0-ACTPRICE", "TUV1", "SPOT"),
    ("SPOTOVECENYSTATS-DATA0-DATAVALID", "XCC_HIDDEN_SETTINGS", "SPOT"),
    ("SPOTOVECENY-DSMODE", "XCC_HIDDEN_SETTINGS", "SPOT"),
    ("WEB-SPOTOVEFUNKCENAKUP", "XCC_HIDDEN_SETTINGS", "SPOT"),
    ("TOPNEOKRUHYIN3-CONFIG-NAZEV", "BIV", "NAST"),
    ("REVERZACESTART", "BIV", "STAVJED"),
    ("REVERZACEPOZADAVEK0", "BIV", "STAVJED"),
    ("PAGE-OKRUH10-US-MON-TON1", "XCC_HIDDEN_SETTINGS", "OKRUH"),
    ("PAGE-OKRUH11-US-SUN-TOFF2", "XCC_HIDDEN_SETTINGS", "OKRUH"),
    ("PAGE-TUV11-US-TUE-TON2", "XCC_HIDDEN_SETTINGS", "TUV1"),
    # Genuine inverter fields and consumer-specific pricing remain local.
    ("FVESTATS-MENIC-TOTALINVPOWER", "FVEINV", "FVEINV"),
    ("TUVSPOTCONFIG-ENABLED", "TUV1", "TUV1"),
    ("MAIN-PRIORIZATORSPOTREBY-PRITUV-SPOTSTATS-BOOST", "TUV1", "TUV1"),
    ("OKRUH1-POZADOVANA", "OKRUH", "OKRUH"),
    ("VARIANTAMETEO", "XCC_HIDDEN_SETTINGS", "XCC_HIDDEN_SETTINGS"),
])
def test_logical_owner_does_not_mutate_metadata(prop, old_group, expected):
    metadata = {"prop": prop, "page": "SOURCE.XML", "device": old_group,
                "data": {"attributes": {"internal_name": "__R100_BOOL_i"}}}
    before = deepcopy(metadata)
    assert helpers.entity_device_key(metadata) == expected
    assert metadata == before


@pytest.mark.parametrize("reverse", [False, True])
def test_shared_field_display_owner_preserves_source_and_identity(reverse):
    raw = [{"state": "12.5", "attributes": {
        "field_name": "SVENKU", "page": page, "value": "12.5",
    }} for page in ("STAVJED1.XML", "FVEINV10.XML", "TUV11.XML")]
    if reverse:
        raw.reverse()
    _, metadata = helpers.process_entities(raw, {
        "SVENKU": {"entity_type": "sensor", "friendly_name_en": "Outside temperature"},
    }, "english")
    assert list(metadata) == ["xcc_svenku"]
    entry = metadata["xcc_svenku"]
    assert entry["prop"] == "SVENKU"
    assert entry["page"] == "FVEINV10.XML"  # Existing priority/value source unchanged.
    assert helpers.entity_device_key(entry) is None


def test_coordinator_applies_logical_owner_to_device_info():
    """Exercise the actual coordinator method without importing Home Assistant."""
    path = Path(__file__).parents[1] / "custom_components/xcc/coordinator.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    cls = next(node for node in tree.body if isinstance(node, ast.ClassDef)
               and node.name == "XCCDataUpdateCoordinator")
    method = next(node for node in cls.body if isinstance(node, ast.FunctionDef)
                  and node.name == "get_device_info_for_entity")
    namespace = {"Any": object, "entity_device_key": helpers.entity_device_key}
    exec(compile(ast.Module(body=[method], type_ignores=[]), str(path), "exec"), namespace)
    controller = {"identifiers": {("xcc", "192.0.2.1")}}
    spot = {"identifiers": {("xcc", "192.0.2.1_SPOT")}}
    coordinator = SimpleNamespace(
        device_info=controller, sub_device_info={"SPOT": spot},
        entities={"outside": {"prop": "SVENKU", "device": "FVEINV"},
                  "price": {"prop": "SPOTOVECENYSTATS-DATA0-ACTPRICE", "device": "TUV1"}},
    )
    resolve = namespace["get_device_info_for_entity"]
    assert resolve(coordinator, "outside") is controller
    assert resolve(coordinator, "price") is spot
    assert resolve(coordinator, "missing") is controller
