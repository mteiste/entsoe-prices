"""ENTSO-E Transparency Platform API client."""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from xml.etree import ElementTree as ET

import aiohttp

API_URL = "https://web-api.tp.entsoe.eu/api"
DOCUMENT_TYPE_DAY_AHEAD_PRICES = "A44"
REQUEST_TIMEOUT = aiohttp.ClientTimeout(total=30)

UTC = timezone.utc

_RESOLUTION_RE = re.compile(r"^PT(\d+)M$")


class EntsoeError(Exception):
    """Base error for the ENTSO-E API client."""


class EntsoeAuthError(EntsoeError):
    """Raised when the API key is rejected."""


class EntsoeNoDataError(EntsoeError):
    """Raised when the platform has no data for the requested window."""


class EntsoeApiError(EntsoeError):
    """Raised for network errors, unexpected statuses, or malformed responses."""


@dataclass(frozen=True)
class PricePoint:
    """One priced interval, in UTC."""

    start: datetime
    end: datetime
    price_eur_per_mwh: float


def _strip_ns(tag: str) -> str:
    return tag.split("}", 1)[1] if "}" in tag else tag


def _find(elem: ET.Element, tag: str) -> ET.Element | None:
    return elem.find(f"{{*}}{tag}")


def _findall(elem: ET.Element, tag: str) -> list[ET.Element]:
    return elem.findall(f"{{*}}{tag}")


def _findtext(elem: ET.Element, tag: str) -> str | None:
    found = _find(elem, tag)
    return found.text if found is not None else None


def _parse_resolution_minutes(resolution: str) -> int:
    match = _RESOLUTION_RE.match(resolution)
    if not match:
        raise EntsoeApiError(f"Unsupported resolution: {resolution}")
    return int(match.group(1))


def _parse_iso_instant(value: str) -> datetime:
    # ENTSO-E timestamps look like "2026-10-05T22:00Z".
    return datetime.strptime(value, "%Y-%m-%dT%H:%MZ").replace(tzinfo=UTC)


def _parse_period(period_elem: ET.Element) -> list[PricePoint]:
    time_interval = _find(period_elem, "timeInterval")
    period_start = _parse_iso_instant(_findtext(time_interval, "start"))
    period_end = _parse_iso_instant(_findtext(time_interval, "end"))
    resolution = _findtext(period_elem, "resolution")
    minutes = _parse_resolution_minutes(resolution)
    step = timedelta(minutes=minutes)

    raw_points: dict[int, float] = {}
    for point_elem in _findall(period_elem, "Point"):
        position = int(_findtext(point_elem, "position"))
        price = float(_findtext(point_elem, "price.amount"))
        raw_points[position] = price

    if not raw_points:
        return []

    # ENTSO-E omits a Point whenever its price repeats the previous
    # position's price — including trailing positions up to the end of the
    # period — so missing positions must forward-fill to the period end
    # rather than be skipped, otherwise prices silently vanish.
    total_slots = int((period_end - period_start) / step)
    points: list[PricePoint] = []
    last_price: float | None = None
    for position in range(1, total_slots + 1):
        if position in raw_points:
            last_price = raw_points[position]
        if last_price is None:
            continue
        start = period_start + step * (position - 1)
        points.append(
            PricePoint(start=start, end=start + step, price_eur_per_mwh=last_price)
        )
    return points


def _parse_response(xml_text: str) -> list[PricePoint]:
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as err:
        raise EntsoeApiError(f"Malformed XML response: {err}") from err

    root_tag = _strip_ns(root.tag)

    if root_tag == "Acknowledgement_MarketDocument":
        reason = _find(root, "Reason")
        text = (_findtext(reason, "text") or "") if reason is not None else ""
        lowered = text.lower()
        if "security token" in lowered or "unauthorized" in lowered:
            raise EntsoeAuthError(text or "Invalid API key")
        if "no matching data" in lowered:
            raise EntsoeNoDataError(text or "No data available for the requested period")
        raise EntsoeApiError(text or "ENTSO-E API returned an error")

    if root_tag != "Publication_MarketDocument":
        raise EntsoeApiError(f"Unexpected response document: {root_tag}")

    try:
        points: list[PricePoint] = []
        for timeseries in _findall(root, "TimeSeries"):
            for period in _findall(timeseries, "Period"):
                points.extend(_parse_period(period))
        points.sort(key=lambda p: p.start)
    except (AttributeError, TypeError, ValueError) as err:
        raise EntsoeApiError(f"Malformed price data in response: {err}") from err

    if not points:
        raise EntsoeNoDataError("No price points in response")
    return points


class EntsoeApiClient:
    """Thin async client for the ENTSO-E Transparency Platform API."""

    def __init__(self, session: aiohttp.ClientSession, api_key: str) -> None:
        self._session = session
        self._api_key = api_key

    async def async_get_prices(
        self, area_code: str, period_start: datetime, period_end: datetime
    ) -> list[PricePoint]:
        params = {
            "securityToken": self._api_key,
            "documentType": DOCUMENT_TYPE_DAY_AHEAD_PRICES,
            "in_Domain": area_code,
            "out_Domain": area_code,
            "periodStart": period_start.strftime("%Y%m%d%H%M"),
            "periodEnd": period_end.strftime("%Y%m%d%H%M"),
        }
        try:
            async with self._session.get(
                API_URL, params=params, timeout=REQUEST_TIMEOUT
            ) as response:
                text = await response.text()
        except (aiohttp.ClientError, TimeoutError) as err:
            raise EntsoeApiError(f"Network error contacting ENTSO-E: {err}") from err

        if response.status in (401, 403):
            raise EntsoeAuthError("ENTSO-E rejected the API key")
        return _parse_response(text)
