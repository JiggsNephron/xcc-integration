"""Backported upstream 1.15.18/1.16.0/1.16.1 guarantees plus fork ID parity.

Use the upstream simultaneous capture without replacing the fork's established
PAGE-* schedule identities, group-2 curve routing or read-only status overrides.
"""

import random
import re
from unittest.mock import AsyncMock, MagicMock

import pytest

from tests.sample_io import read_sample_xml
from tests.test_circuit_namespacing import (
    SAMPLE_DIR, _entity_helpers as helpers, _xcc_client as client_module,
)

PAGES = ("OKRUH10.XML", "OKRUH11.XML", "OKRUH12.XML")


def registers(page):
    return dict(re.findall(
        r'<INPUT P="([^"]+)" NAME="(__R[^\"]+)"',
        read_sample_xml(SAMPLE_DIR / page),
    ))


def test_global_whitelist_matches_simultaneous_capture():
    regs = [registers(page) for page in PAGES]
    shared = set.intersection(*(set(r) for r in regs))
    for prop in shared:
        # Compare register identity only, not the formatting/type suffix.
        addresses = {re.match(r"__R([\d.]+)", r[prop]).group(1) for r in regs}
        assert (len(addresses) == 1) == (prop in client_module.CIRCUIT_GLOBAL_PROPS), prop


def test_page_order_is_stable_and_both_discovery_paths_use_it():
    pages = [*PAGES, "STATUS.XML", "OKRUH11.XML", "FVE4.XML"]
    expected = sorted(set(pages))
    rng = random.Random(0)
    for _ in range(50):
        rng.shuffle(pages)
        assert client_module.ordered_unique_pages(pages) == expected
    source = (SAMPLE_DIR.parent.parent / "custom_components/xcc/xcc_client.py").read_text(encoding="utf-8")
    assert "list(set(data_pages))" not in source
    assert source.count("ordered_unique_pages(data_pages)") == 2


def test_capture_all_local_fields_survive_with_existing_schedule_ids():
    raw = []
    for page in PAGES:
        parsed = client_module.parse_xml_entities(read_sample_xml(SAMPLE_DIR / page), page)
        raw.extend(parsed)
        for entity in parsed:
            prop = entity["attributes"]["field_name"]
            if prop in client_module.CIRCUIT_GLOBAL_PROPS:
                continue
            if prop.startswith("PAGE-"):
                assert prop.startswith(f"PAGE-{page[:-4]}-")
            elif page != PAGES[0]:
                assert prop.startswith(f"OKRUH{client_module.circuit_from_okruh_page(page)}-")
    _, metadata = helpers.process_entities(raw, {}, "english")
    for page in PAGES:
        assert metadata[f"xcc_page_{page[:-4].lower()}_us_mon_ton1"]["page"] == page
    assert metadata["xcc_svenku"]["page"] == PAGES[0]


@pytest.mark.parametrize("entity_type", ["sensor", "binary_sensor", "switch", "number", "select"])
def test_generic_bare_field_inherits_descriptor_including_read_only(entity_type):
    descriptor = {"entity_type": entity_type, "friendly_name_en": "New feature",
                  "writable": entity_type in ("switch", "number", "select"),
                  "data_type": "boolean", "unit": ""}
    raw = client_module.parse_xml_entities(
        '<ROOT><INPUT P="NEW-FEATURE" NAME="__R100_BOOL_i" VALUE="1"/></ROOT>',
        "OKRUH11.XML",
    )
    _, metadata = helpers.process_entities(raw, {"NEW-FEATURE": descriptor}, "english")
    meta = metadata["xcc_okruh1_new_feature"]
    assert meta["type"] == entity_type
    assert meta["descriptor_config"]["writable"] == descriptor["writable"]
    assert meta["descriptor_config"]["data_type"] == "boolean"


def test_new_local_feature_names_use_correct_circuit_and_fallback():
    descriptor = {"entity_type": "sensor", "friendly_name_en": "New feature"}
    for page, label in (("OKRUH11.XML", "Upstairs"), ("OKRUH12.XML", "Guest room")):
        raw = client_module.parse_xml_entities(
            f'<ROOT><INPUT P="PAGENAME" VALUE="{label}"/>'
            '<INPUT P="NEW-FEATURE" NAME="__R100_REAL_r1" VALUE="1"/></ROOT>', page,
        )
        processed, _ = helpers.process_entities(raw, {"NEW-FEATURE": descriptor}, "english")
        n = client_module.circuit_from_okruh_page(page)
        assert processed["sensors"][f"xcc_okruh{n}_new_feature"]["name"] == f"{label} — New feature"
    cfg = helpers.configured_name_config("OKRUH2-UNDESCRIBED", "OKRUH12.XML", {}, {})
    assert cfg["friendly_name_en"] == "Heating circuit 3 — UNDESCRIBED"


@pytest.mark.asyncio
@pytest.mark.parametrize(("prop", "base", "page"), [
    ("OKRUH2-KONSTANTA", "TO-KONSTANTA", "OKRUH12.XML"),
    ("OKRUH2-NEW-FEATURE", "NEW-FEATURE", "OKRUH12.XML"),
    ("PAGE-OKRUH11-US-MON-TON1", "US-MON-TON1", "OKRUH11.XML"),
    ("OKRUH1-EK01", "TO-EK01", "OKRUH21.XML"),
])
async def test_native_register_write_routing_keeps_fork_controls(prop, base, page):
    client = client_module.XCCClient("192.168.1.100")
    client.fetch_page = AsyncMock(return_value=f'<ROOT><INPUT P="{base}" NAME="__R100_REAL_r1" VALUE="1"/></ROOT>')
    response = MagicMock(status=200)
    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=response)
    cm.__aexit__ = AsyncMock(return_value=False)
    client.session = MagicMock()
    client.session.post.return_value = cm
    assert await client.set_value(prop, "2")
    client.fetch_page.assert_awaited_once_with(page)
    assert client.session.post.call_args.args == (f"http://192.168.1.100/{page}",)
    assert client.session.post.call_args.kwargs["data"] == {"__R100_REAL_r1": "2"}


def test_post_release_version_and_tag_order():
    from packaging.version import Version
    assert Version("1.16.1") < Version("1.16.1.post1") < Version("1.16.1.post2") < Version("1.16.2")
