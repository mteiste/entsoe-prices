"""Data update coordinator for the ENTSO-E integration."""
from __future__ import annotations

import logging
from datetime import datetime, timedelta

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .api import (
    EntsoeApiClient,
    EntsoeApiError,
    EntsoeAuthError,
    EntsoeNoDataError,
    PricePoint,
)
from .const import DEFAULT_SCAN_INTERVAL, DOMAIN

_LOGGER = logging.getLogger(__name__)


def _compute_window(now_local: datetime) -> tuple[datetime, datetime, datetime]:
    """Return UTC (today_start, tomorrow_start, tomorrow_end) for now_local's day.

    Re-normalizes to local midnight at each calendar-day step (rather than a
    flat timedelta(days=N)) so DST transition days, which are 23 or 25 hours
    long in wall-clock terms, still produce the correct UTC boundaries.
    """
    today_start_local = now_local.replace(hour=0, minute=0, second=0, microsecond=0)
    tomorrow_start_local = (today_start_local + timedelta(days=1)).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    tomorrow_end_local = (tomorrow_start_local + timedelta(days=1)).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    return (
        dt_util.as_utc(today_start_local),
        dt_util.as_utc(tomorrow_start_local),
        dt_util.as_utc(tomorrow_end_local),
    )


class EntsoeDataUpdateCoordinator(DataUpdateCoordinator[list[PricePoint]]):
    """Fetches and caches today's and tomorrow's day-ahead prices."""

    def __init__(
        self, hass: HomeAssistant, client: EntsoeApiClient, area_code: str
    ) -> None:
        super().__init__(
            hass, _LOGGER, name=DOMAIN, update_interval=DEFAULT_SCAN_INTERVAL
        )
        self._client = client
        self._area_code = area_code
        self.tomorrow_valid = False

    async def _async_update_data(self) -> list[PricePoint]:
        today_start, tomorrow_start, tomorrow_end = _compute_window(dt_util.now())

        try:
            today_points = await self._client.async_get_prices(
                self._area_code, today_start, tomorrow_start
            )
        except EntsoeAuthError as err:
            raise ConfigEntryAuthFailed(str(err)) from err
        except EntsoeApiError as err:
            raise UpdateFailed(str(err)) from err
        today_points = [
            point for point in today_points if today_start <= point.start < tomorrow_start
        ]

        try:
            tomorrow_points = await self._client.async_get_prices(
                self._area_code, tomorrow_start, tomorrow_end
            )
            tomorrow_points = [
                point
                for point in tomorrow_points
                if tomorrow_start <= point.start < tomorrow_end
            ]
            # ENTSO-E's market day is CET-aligned, so for zones east of CET
            # the start of the local "tomorrow" window overlaps today's
            # already-published market day; only full coverage means
            # tomorrow's prices are actually out.
            self.tomorrow_valid = bool(tomorrow_points) and (
                max(point.end for point in tomorrow_points) >= tomorrow_end
            )
        except EntsoeAuthError as err:
            raise ConfigEntryAuthFailed(str(err)) from err
        except EntsoeNoDataError:
            # Tomorrow's prices are typically published around 13:00 CET;
            # not having them yet is expected, not a failure.
            tomorrow_points = []
            self.tomorrow_valid = False
        except EntsoeApiError:
            # A transient failure fetching tomorrow's (not-yet-guaranteed)
            # data must not take down an otherwise-successful update.
            tomorrow_points = [
                point for point in (self.data or []) if point.start >= tomorrow_start
            ]
            self.tomorrow_valid = bool(tomorrow_points) and (
                max(point.end for point in tomorrow_points) >= tomorrow_end
            )

        by_start = {point.start: point for point in today_points + tomorrow_points}
        return sorted(by_start.values(), key=lambda p: p.start)
