"""End-to-end test: config entry setup produces a working sensor."""
from datetime import datetime, timezone
from unittest.mock import patch

from homeassistant.const import STATE_UNAVAILABLE
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
)

from custom_components.entsoe_prices.api import PricePoint
from custom_components.entsoe_prices.const import CONF_API_KEY, CONF_AREA, CONF_VAT, DOMAIN

UTC = timezone.utc


async def test_setup_entry_creates_working_sensor(hass, freezer):
    # Freeze the whole clock (not just sensor.dt_util.utcnow) so the
    # coordinator's own window/clipping logic, which reads the real clock,
    # agrees with these hard-coded 2026-10-06 fixture points regardless of
    # what day it actually is when this test runs.
    freezer.move_to(datetime(2026, 10, 6, 12, 30, tzinfo=UTC))
    points = [
        PricePoint(
            start=datetime(2026, 10, 6, 12, tzinfo=UTC),
            end=datetime(2026, 10, 6, 13, tzinfo=UTC),
            price_eur_per_mwh=100.0,
        )
    ]
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_API_KEY: "fake-key", CONF_AREA: "Finland (FI)", CONF_VAT: 24.0},
    )
    entry.add_to_hass(hass)

    with patch(
        "custom_components.entsoe_prices.api.EntsoeApiClient.async_get_prices",
        return_value=points,
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    state = hass.states.get("sensor.electricity_price")
    assert state is not None
    assert state.state == "12.4"


async def test_sensor_state_advances_at_slot_boundary_without_refresh(hass, freezer):
    # Uses HA's real time-tracking machinery: the coordinator refreshes
    # hourly, but the price must still change at each 15-minute slot.
    freezer.move_to(datetime(2026, 10, 6, 12, 10, tzinfo=UTC))
    points = [
        PricePoint(
            start=datetime(2026, 10, 6, 12, 0, tzinfo=UTC),
            end=datetime(2026, 10, 6, 12, 15, tzinfo=UTC),
            price_eur_per_mwh=100.0,
        ),
        PricePoint(
            start=datetime(2026, 10, 6, 12, 15, tzinfo=UTC),
            end=datetime(2026, 10, 6, 12, 30, tzinfo=UTC),
            price_eur_per_mwh=200.0,
        ),
    ]
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_API_KEY: "fake-key", CONF_AREA: "Finland (FI)", CONF_VAT: 24.0},
    )
    entry.add_to_hass(hass)

    with patch(
        "custom_components.entsoe_prices.api.EntsoeApiClient.async_get_prices",
        return_value=points,
    ) as mock_get_prices:
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
        assert hass.states.get("sensor.electricity_price").state == "12.4"
        calls_after_setup = mock_get_prices.call_count

        boundary = datetime(2026, 10, 6, 12, 15, tzinfo=UTC)
        freezer.move_to(boundary)
        async_fire_time_changed(hass, boundary)
        await hass.async_block_till_done()

        assert mock_get_prices.call_count == calls_after_setup
        assert hass.states.get("sensor.electricity_price").state == "24.8"


async def test_unload_entry_removes_sensor(hass):
    # Unloading must not wipe the entity registry: the registry exists
    # specifically to preserve user customizations (renamed entity_id,
    # custom name/icon/area) across reloads, e.g. every time the VAT
    # options flow reloads this entry. The correct, idiomatic behavior is
    # the entity goes unavailable, not that it vanishes from hass.states.
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_API_KEY: "fake-key", CONF_AREA: "Finland (FI)", CONF_VAT: 0.0},
    )
    entry.add_to_hass(hass)

    with patch(
        "custom_components.entsoe_prices.api.EntsoeApiClient.async_get_prices",
        return_value=[],
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

        assert await hass.config_entries.async_unload(entry.entry_id)
        await hass.async_block_till_done()

    state = hass.states.get("sensor.electricity_price")
    assert state is not None
    assert state.state == STATE_UNAVAILABLE
