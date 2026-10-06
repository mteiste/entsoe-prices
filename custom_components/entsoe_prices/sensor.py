"""Sensor platform for the ENTSO-E integration."""
from __future__ import annotations

from datetime import datetime, timedelta
from statistics import mean

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import async_track_utc_time_change
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from .api import PricePoint
from .const import CONF_VAT, DOMAIN
from .coordinator import EntsoeDataUpdateCoordinator


def _to_ct_per_kwh(eur_per_mwh: float, vat_percent: float) -> float:
    return eur_per_mwh / 10 * (1 + vat_percent / 100)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinator: EntsoeDataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([EntsoePriceSensor(coordinator, entry)])


class EntsoePriceSensor(CoordinatorEntity[EntsoeDataUpdateCoordinator], SensorEntity):
    """Current ENTSO-E day-ahead electricity price, in c/kWh."""

    _attr_native_unit_of_measurement = "c/kWh"
    _attr_name = "Electricity price"
    # At 15-minute resolution the curves exceed the recorder's attribute
    # size limit; they are only useful live, not in history.
    _unrecorded_attributes = frozenset({"raw_today", "raw_tomorrow"})

    def __init__(
        self, coordinator: EntsoeDataUpdateCoordinator, entry: ConfigEntry
    ) -> None:
        super().__init__(coordinator)
        self._vat_percent = entry.options.get(CONF_VAT, entry.data.get(CONF_VAT, 0))
        self._attr_unique_id = f"{entry.entry_id}_price"

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        # The current price changes at slot boundaries, not when the
        # coordinator refreshes, so re-render on every quarter hour.
        self.async_on_remove(
            async_track_utc_time_change(
                self.hass, self._async_slot_boundary, minute=[0, 15, 30, 45], second=0
            )
        )

    @callback
    def _async_slot_boundary(self, _now: datetime) -> None:
        self.async_write_ha_state()

    def _points(self) -> list[PricePoint]:
        return self.coordinator.data or []

    def _point_at(self, when: datetime) -> PricePoint | None:
        for point in self._points():
            if point.start <= when < point.end:
                return point
        return None

    @property
    def native_value(self) -> float | None:
        point = self._point_at(dt_util.utcnow())
        if point is None:
            return None
        return round(_to_ct_per_kwh(point.price_eur_per_mwh, self._vat_percent), 4)

    def _day_points(self, day_offset: int) -> list[PricePoint]:
        target_date = (dt_util.now() + timedelta(days=day_offset)).date()
        return [
            point
            for point in self._points()
            if dt_util.as_local(point.start).date() == target_date
        ]

    @property
    def extra_state_attributes(self) -> dict:
        today_points = self._day_points(0)
        tomorrow_points = self._day_points(1)

        def _curve(points: list[PricePoint]) -> list[dict]:
            return [
                {
                    "start": point.start.isoformat(),
                    "end": point.end.isoformat(),
                    "price_eur_mwh": point.price_eur_per_mwh,
                    "price_ct_kwh": round(
                        _to_ct_per_kwh(point.price_eur_per_mwh, self._vat_percent), 4
                    ),
                }
                for point in points
            ]

        today_prices = [point.price_eur_per_mwh for point in today_points]
        next_hour_point = self._point_at(dt_util.utcnow() + timedelta(hours=1))

        return {
            "raw_today": _curve(today_points),
            "raw_tomorrow": _curve(tomorrow_points),
            "tomorrow_valid": self.coordinator.tomorrow_valid,
            "next_hour_price": (
                round(
                    _to_ct_per_kwh(next_hour_point.price_eur_per_mwh, self._vat_percent),
                    4,
                )
                if next_hour_point
                else None
            ),
            "today_min": (
                round(_to_ct_per_kwh(min(today_prices), self._vat_percent), 4)
                if today_prices
                else None
            ),
            "today_max": (
                round(_to_ct_per_kwh(max(today_prices), self._vat_percent), 4)
                if today_prices
                else None
            ),
            "today_average": (
                round(_to_ct_per_kwh(mean(today_prices), self._vat_percent), 4)
                if today_prices
                else None
            ),
        }
