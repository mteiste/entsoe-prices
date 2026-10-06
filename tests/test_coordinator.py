"""Tests for the ENTSO-E data update coordinator."""
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch
from zoneinfo import ZoneInfo

import pytest
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import UpdateFailed

from custom_components.entsoe_prices.api import (
    EntsoeApiError,
    EntsoeAuthError,
    EntsoeNoDataError,
    PricePoint,
)
from custom_components.entsoe_prices.coordinator import (
    EntsoeDataUpdateCoordinator,
    _compute_window,
)

UTC = timezone.utc
HELSINKI = ZoneInfo("Europe/Helsinki")
NOW_PATCH = "custom_components.entsoe_prices.coordinator.dt_util.now"


@pytest.fixture(autouse=True)
def fixed_now():
    # Pin "now" so today = 2026-10-06 and tomorrow = 2026-10-07 (UTC days),
    # matching the _point() fixtures below.
    with patch(NOW_PATCH, return_value=datetime(2026, 10, 6, 12, tzinfo=UTC)) as mock:
        yield mock


def _point(hour: int, price: float) -> PricePoint:
    start = datetime(2026, 10, 6, hour % 24, tzinfo=UTC) + timedelta(days=hour // 24)
    return PricePoint(start=start, end=start + timedelta(hours=1), price_eur_per_mwh=price)


def test_compute_window_spans_full_calendar_days_across_dst_change():
    # 2026-10-25 is the EU DST end date (last Sunday of October): Helsinki
    # falls back from EEST (UTC+3) to EET (UTC+2) at local 04:00, making
    # the local day 25 hours.
    helsinki = ZoneInfo("Europe/Helsinki")
    now_local = datetime(2026, 10, 25, 10, 0, tzinfo=helsinki)

    today_start, tomorrow_start, tomorrow_end = _compute_window(now_local)

    assert today_start == datetime(2026, 10, 24, 21, 0, tzinfo=UTC)
    assert tomorrow_start == datetime(2026, 10, 25, 22, 0, tzinfo=UTC)
    assert tomorrow_end == datetime(2026, 10, 26, 22, 0, tzinfo=UTC)
    assert tomorrow_start - today_start == timedelta(hours=25)
    assert tomorrow_end - today_start == timedelta(hours=49)


def test_compute_window_spans_full_calendar_days_across_spring_forward():
    # 2026-03-29 is the EU DST start date (last Sunday of March): Helsinki
    # springs forward from EET (UTC+2) to EEST (UTC+3) at local 03:00,
    # making the local day 23 hours.
    now_local = datetime(2026, 3, 29, 10, 0, tzinfo=HELSINKI)

    today_start, tomorrow_start, tomorrow_end = _compute_window(now_local)

    assert today_start == datetime(2026, 3, 28, 22, 0, tzinfo=UTC)
    assert tomorrow_start == datetime(2026, 3, 29, 21, 0, tzinfo=UTC)
    assert tomorrow_end == datetime(2026, 3, 30, 21, 0, tzinfo=UTC)
    assert tomorrow_start - today_start == timedelta(hours=23)
    assert tomorrow_end - today_start == timedelta(hours=47)


async def test_update_raises_auth_failed_on_bad_key(hass):
    client = AsyncMock()
    client.async_get_prices.side_effect = EntsoeAuthError("bad key")
    coordinator = EntsoeDataUpdateCoordinator(hass, client, "10YFI-1--------U")

    with pytest.raises(ConfigEntryAuthFailed):
        await coordinator._async_update_data()


async def test_update_raises_update_failed_when_today_fetch_fails(hass):
    client = AsyncMock()
    client.async_get_prices.side_effect = EntsoeApiError("network down")
    coordinator = EntsoeDataUpdateCoordinator(hass, client, "10YFI-1--------U")

    with pytest.raises(UpdateFailed):
        await coordinator._async_update_data()


async def test_update_succeeds_when_tomorrow_not_yet_published(hass):
    today_points = [_point(h, 10.0) for h in range(24)]
    client = AsyncMock()
    client.async_get_prices.side_effect = [today_points, EntsoeNoDataError("not published")]
    coordinator = EntsoeDataUpdateCoordinator(hass, client, "10YFI-1--------U")

    result = await coordinator._async_update_data()

    assert result == today_points
    assert coordinator.tomorrow_valid is False


async def test_update_includes_tomorrow_when_published(hass):
    today_points = [_point(h, 10.0) for h in range(24)]
    tomorrow_points = [_point(h, 12.0) for h in range(24, 48)]
    client = AsyncMock()
    client.async_get_prices.side_effect = [today_points, tomorrow_points]
    coordinator = EntsoeDataUpdateCoordinator(hass, client, "10YFI-1--------U")

    result = await coordinator._async_update_data()

    assert result == today_points + tomorrow_points
    assert coordinator.tomorrow_valid is True


async def test_transient_tomorrow_failure_preserves_todays_data(hass):
    # A transient error fetching tomorrow's (not-yet-guaranteed) data must
    # not take down an otherwise-successful update for today.
    today_points = [_point(h, 10.0) for h in range(24)]
    client = AsyncMock()
    client.async_get_prices.side_effect = [today_points, EntsoeApiError("timeout")]
    coordinator = EntsoeDataUpdateCoordinator(hass, client, "10YFI-1--------U")

    result = await coordinator._async_update_data()

    assert result == today_points
    assert coordinator.tomorrow_valid is False


async def test_update_raises_auth_failed_if_tomorrow_fetch_hits_auth_error(hass):
    # The key can be revoked after setup, not only be wrong at setup time;
    # the periodic refresh must still trigger HA's reauth flow.
    today_points = [_point(h, 10.0) for h in range(24)]
    client = AsyncMock()
    client.async_get_prices.side_effect = [today_points, EntsoeAuthError("revoked")]
    coordinator = EntsoeDataUpdateCoordinator(hass, client, "10YFI-1--------U")

    with pytest.raises(ConfigEntryAuthFailed):
        await coordinator._async_update_data()


async def test_tomorrow_not_valid_when_fetch_only_overlaps_todays_market_day(
    hass, fixed_now
):
    # Helsinki is UTC+3 in October: local "tomorrow" starts 2026-10-06T21:00Z,
    # but ENTSO-E's CET-aligned market day for 10-06 runs until 22:00Z. Before
    # tomorrow's auction is published, the "tomorrow" fetch still returns that
    # already-published tail hour — that must not count as tomorrow's prices.
    fixed_now.return_value = datetime(2026, 10, 6, 15, tzinfo=HELSINKI)
    today_points = [_point(h, 10.0) for h in range(-3, 21)]
    overlap_tail = [_point(21, 11.0)]
    client = AsyncMock()
    client.async_get_prices.side_effect = [today_points, overlap_tail]
    coordinator = EntsoeDataUpdateCoordinator(hass, client, "10YFI-1--------U")

    result = await coordinator._async_update_data()

    assert result == today_points + overlap_tail
    assert coordinator.tomorrow_valid is False


async def test_tomorrow_valid_when_fetch_covers_full_local_tomorrow(hass, fixed_now):
    fixed_now.return_value = datetime(2026, 10, 6, 15, tzinfo=HELSINKI)
    today_points = [_point(h, 10.0) for h in range(-3, 21)]
    tomorrow_points = [_point(h, 12.0) for h in range(21, 45)]
    client = AsyncMock()
    client.async_get_prices.side_effect = [today_points, tomorrow_points]
    coordinator = EntsoeDataUpdateCoordinator(hass, client, "10YFI-1--------U")

    result = await coordinator._async_update_data()

    assert result == today_points + tomorrow_points
    assert coordinator.tomorrow_valid is True


async def test_tomorrow_not_valid_when_cached_fallback_only_partially_covers_tomorrow(
    hass, fixed_now
):
    # Same overlap as the primary-path test, but reached via the cached-data
    # fallback after a transient tomorrow-fetch failure.
    fixed_now.return_value = datetime(2026, 10, 6, 15, tzinfo=HELSINKI)
    today_points = [_point(h, 10.0) for h in range(-3, 21)]
    cached_tail = [_point(21, 11.0)]
    client = AsyncMock()
    client.async_get_prices.side_effect = [today_points, EntsoeApiError("timeout")]
    coordinator = EntsoeDataUpdateCoordinator(hass, client, "10YFI-1--------U")
    coordinator.data = today_points + cached_tail
    coordinator.tomorrow_valid = True

    result = await coordinator._async_update_data()

    assert result == today_points + cached_tail
    assert coordinator.tomorrow_valid is False


async def test_update_clips_and_deduplicates_overlapping_fetches(hass):
    # If ENTSO-E returns whole market-day documents spilling past the
    # requested window, the today and tomorrow fetches can overlap.
    today_points = [_point(h, 10.0) for h in range(25)]
    tomorrow_points = [_point(h, 12.0) for h in range(23, 48)]
    tomorrow_points.append(_point(30, 99.0))
    client = AsyncMock()
    client.async_get_prices.side_effect = [today_points, tomorrow_points]
    coordinator = EntsoeDataUpdateCoordinator(hass, client, "10YFI-1--------U")

    result = await coordinator._async_update_data()

    starts = [point.start for point in result]
    assert len(starts) == len(set(starts)) == 48
    by_start = {point.start: point for point in result}
    # 23:00 on 10-06 belongs to today's window, 00:00 on 10-07 to tomorrow's.
    assert by_start[_point(23, 0).start].price_eur_per_mwh == 10.0
    assert by_start[_point(24, 0).start].price_eur_per_mwh == 12.0
    assert by_start[_point(30, 0).start].price_eur_per_mwh == 99.0
    assert coordinator.tomorrow_valid is True
