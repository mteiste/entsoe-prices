"""Tests for the ENTSO-E price sensor."""
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest

from custom_components.entsoe_prices.api import PricePoint
from custom_components.entsoe_prices.const import CONF_VAT
from custom_components.entsoe_prices.sensor import EntsoePriceSensor

UTC = timezone.utc


class _FakeCoordinator:
    def __init__(self, data: list[PricePoint], tomorrow_valid: bool = True) -> None:
        self.data = data
        self.tomorrow_valid = tomorrow_valid


def _point(start: datetime, price: float) -> PricePoint:
    return PricePoint(start=start, end=start + timedelta(hours=1), price_eur_per_mwh=price)


def _make_entry(vat: float = 0.0):
    entry = type("Entry", (), {})()
    entry.data = {}
    entry.options = {CONF_VAT: vat}
    entry.entry_id = "test-entry"
    return entry


def test_raw_curves_are_excluded_from_recorder():
    # The curves exceed the recorder's 16 KiB attribute limit at PT15M.
    assert EntsoePriceSensor._unrecorded_attributes == frozenset(
        {"raw_today", "raw_tomorrow"}
    )


def test_native_value_converts_eur_mwh_to_ct_kwh_with_vat():
    now = datetime(2026, 10, 6, 12, 30, tzinfo=UTC)
    points = [_point(datetime(2026, 10, 6, 12, tzinfo=UTC), 100.0)]
    sensor = EntsoePriceSensor(_FakeCoordinator(points), _make_entry(vat=24.0))

    with patch("custom_components.entsoe_prices.sensor.dt_util.utcnow", return_value=now):
        # 100 EUR/MWh = 10 c/kWh; with 24% VAT = 12.4 c/kWh.
        assert sensor.native_value == 12.4


def test_native_value_handles_negative_prices():
    now = datetime(2026, 10, 6, 12, 30, tzinfo=UTC)
    points = [_point(datetime(2026, 10, 6, 12, tzinfo=UTC), -23.0)]
    sensor = EntsoePriceSensor(_FakeCoordinator(points), _make_entry(vat=0.0))

    with patch("custom_components.entsoe_prices.sensor.dt_util.utcnow", return_value=now):
        assert sensor.native_value == -2.3


def test_native_value_returns_none_when_no_point_covers_now():
    now = datetime(2026, 10, 6, 23, 30, tzinfo=UTC)
    points = [_point(datetime(2026, 10, 6, 12, tzinfo=UTC), 100.0)]
    sensor = EntsoePriceSensor(_FakeCoordinator(points), _make_entry(vat=0.0))

    with patch("custom_components.entsoe_prices.sensor.dt_util.utcnow", return_value=now):
        assert sensor.native_value is None


def test_today_min_max_average_with_negative_prices():
    base = datetime(2026, 10, 6, 0, tzinfo=UTC)
    points = [
        _point(base + timedelta(hours=h), price)
        for h, price in enumerate([-10.0, 0.0, 20.0])
    ]
    sensor = EntsoePriceSensor(_FakeCoordinator(points), _make_entry(vat=0.0))

    now = base + timedelta(hours=1)
    with patch("custom_components.entsoe_prices.sensor.dt_util.utcnow", return_value=now), patch(
        "custom_components.entsoe_prices.sensor.dt_util.now", return_value=now
    ), patch(
        "custom_components.entsoe_prices.sensor.dt_util.as_local", side_effect=lambda dt: dt
    ):
        attrs = sensor.extra_state_attributes

    # A falsy 0.0 price, or a negative min, must not be treated as "missing".
    assert attrs["today_min"] == -1.0
    assert attrs["today_max"] == 2.0
    assert attrs["today_average"] == pytest.approx(0.3333, rel=1e-3)


def test_extra_state_attributes_splits_today_and_tomorrow():
    today = datetime(2026, 10, 6, 10, tzinfo=UTC)
    tomorrow = datetime(2026, 10, 7, 10, tzinfo=UTC)
    points = [_point(today, 50.0), _point(tomorrow, 60.0)]
    sensor = EntsoePriceSensor(
        _FakeCoordinator(points, tomorrow_valid=True), _make_entry(vat=0.0)
    )

    with patch(
        "custom_components.entsoe_prices.sensor.dt_util.utcnow", return_value=today
    ), patch("custom_components.entsoe_prices.sensor.dt_util.now", return_value=today), patch(
        "custom_components.entsoe_prices.sensor.dt_util.as_local", side_effect=lambda dt: dt
    ):
        attrs = sensor.extra_state_attributes

    assert len(attrs["raw_today"]) == 1
    assert len(attrs["raw_tomorrow"]) == 1
    assert attrs["raw_today"][0]["price_eur_mwh"] == 50.0
    assert attrs["raw_tomorrow"][0]["price_eur_mwh"] == 60.0
    assert attrs["tomorrow_valid"] is True
    # The only "today" point covers 10:00-11:00; now+1h = 11:00 is not
    # covered by any point in this fixture.
    assert attrs["next_hour_price"] is None
