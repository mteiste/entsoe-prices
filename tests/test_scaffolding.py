import json
from pathlib import Path

from custom_components.entsoe_prices.const import AREA_CODES, DOMAIN


def test_domain_constant():
    assert DOMAIN == "entsoe_prices"


def test_area_codes_include_finland():
    # Verified live against https://web-api.tp.entsoe.eu/api on 2026-10-06.
    assert AREA_CODES["Finland (FI)"] == "10YFI-1--------U"


def test_manifest_has_required_fields():
    manifest_path = (
        Path(__file__).parent.parent / "custom_components" / "entsoe_prices" / "manifest.json"
    )
    manifest = json.loads(manifest_path.read_text())

    assert manifest["domain"] == "entsoe_prices"
    assert manifest["config_flow"] is True
    assert manifest["iot_class"] == "cloud_polling"
