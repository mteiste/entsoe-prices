"""Tests for the ENTSO-E API client and XML parsing."""
from datetime import datetime, timezone

import pytest

from custom_components.entsoe_prices.api import (
    EntsoeApiClient,
    EntsoeApiError,
    EntsoeAuthError,
    EntsoeNoDataError,
    PricePoint,
    _parse_response,
)

UTC = timezone.utc

# Shape matches the real response captured from
# https://web-api.tp.entsoe.eu/api on 2026-10-06 for Finland: ENTSO-E omits
# a Point when its price repeats the previous position's price.
DATA_DOCUMENT_SPARSE_POSITIONS = """<?xml version="1.0" encoding="utf-8"?>
<Publication_MarketDocument xmlns="urn:iec62325.351:tc57wg16:451-3:publicationdocument:7:3">
  <TimeSeries>
    <mRID>1</mRID>
    <Period>
      <timeInterval>
        <start>2026-10-05T22:00Z</start>
        <end>2026-10-06T22:00Z</end>
      </timeInterval>
      <resolution>PT15M</resolution>
      <Point><position>1</position><price.amount>-0.08</price.amount></Point>
      <Point><position>2</position><price.amount>-0.03</price.amount></Point>
      <Point><position>5</position><price.amount>-0.23</price.amount></Point>
    </Period>
  </TimeSeries>
</Publication_MarketDocument>
"""

ACK_AUTH_ERROR = """<?xml version="1.0" encoding="utf-8"?>
<Acknowledgement_MarketDocument xmlns="urn:iec62325.351:tc57wg16:451-3:acknowledgementdocument:5:0">
  <Reason>
    <code>999</code>
    <text>Invalid security token</text>
  </Reason>
</Acknowledgement_MarketDocument>
"""

ACK_NO_DATA = """<?xml version="1.0" encoding="utf-8"?>
<Acknowledgement_MarketDocument xmlns="urn:iec62325.351:tc57wg16:451-3:acknowledgementdocument:5:0">
  <Reason>
    <code>999</code>
    <text>No matching data found for Data item</text>
  </Reason>
</Acknowledgement_MarketDocument>
"""


def test_parse_response_forward_fills_sparse_positions():
    points = _parse_response(DATA_DOCUMENT_SPARSE_POSITIONS)

    # The Period spans a full 24h at PT15M, i.e. 96 slots, even though only
    # positions up to 5 are spelled out.
    assert len(points) == 96
    assert points[0] == PricePoint(
        start=datetime(2026, 10, 5, 22, 0, tzinfo=UTC),
        end=datetime(2026, 10, 5, 22, 15, tzinfo=UTC),
        price_eur_per_mwh=-0.08,
    )
    # Positions 3 and 4 were omitted in the source document; they must
    # repeat position 2's price rather than being skipped or zeroed.
    assert points[2].price_eur_per_mwh == -0.03
    assert points[3].price_eur_per_mwh == -0.03
    assert points[4].price_eur_per_mwh == -0.23


def test_parse_response_forward_fills_trailing_positions_to_period_end():
    # A03 curves carry the last specified price to the end of the period:
    # positions 6..96 were omitted because they repeat position 5's price,
    # and must not be dropped.
    points = _parse_response(DATA_DOCUMENT_SPARSE_POSITIONS)

    trailing = points[5:]
    assert len(trailing) == 91
    assert all(point.price_eur_per_mwh == -0.23 for point in trailing)
    assert points[-1] == PricePoint(
        start=datetime(2026, 10, 6, 21, 45, tzinfo=UTC),
        end=datetime(2026, 10, 6, 22, 0, tzinfo=UTC),
        price_eur_per_mwh=-0.23,
    )


def test_parse_response_auth_error():
    with pytest.raises(EntsoeAuthError):
        _parse_response(ACK_AUTH_ERROR)


def test_parse_response_no_data_error():
    with pytest.raises(EntsoeNoDataError):
        _parse_response(ACK_NO_DATA)


def test_parse_response_malformed_xml():
    with pytest.raises(EntsoeApiError):
        _parse_response("not xml")


def test_parse_response_missing_resolution():
    doc_missing_resolution = """<?xml version="1.0" encoding="utf-8"?>
<Publication_MarketDocument xmlns="urn:iec62325.351:tc57wg16:451-3:publicationdocument:7:3">
  <TimeSeries>
    <mRID>1</mRID>
    <Period>
      <timeInterval>
        <start>2026-10-05T22:00Z</start>
        <end>2026-10-06T22:00Z</end>
      </timeInterval>
      <Point><position>1</position><price.amount>-0.08</price.amount></Point>
    </Period>
  </TimeSeries>
</Publication_MarketDocument>
"""
    with pytest.raises(EntsoeApiError):
        _parse_response(doc_missing_resolution)


def test_parse_response_point_missing_price():
    doc_point_missing_price = """<?xml version="1.0" encoding="utf-8"?>
<Publication_MarketDocument xmlns="urn:iec62325.351:tc57wg16:451-3:publicationdocument:7:3">
  <TimeSeries>
    <mRID>1</mRID>
    <Period>
      <timeInterval>
        <start>2026-10-05T22:00Z</start>
        <end>2026-10-06T22:00Z</end>
      </timeInterval>
      <resolution>PT15M</resolution>
      <Point><position>1</position></Point>
    </Period>
  </TimeSeries>
</Publication_MarketDocument>
"""
    with pytest.raises(EntsoeApiError):
        _parse_response(doc_point_missing_price)


class _FakeResponse:
    def __init__(self, status: int, text: str) -> None:
        self.status = status
        self._text = text

    async def text(self) -> str:
        return self._text

    async def __aenter__(self) -> "_FakeResponse":
        return self

    async def __aexit__(self, *exc_info) -> None:
        return None


class _TimingOutResponse(_FakeResponse):
    def __init__(self) -> None:
        super().__init__(200, "")

    async def __aenter__(self) -> "_FakeResponse":
        raise TimeoutError


class _FakeSession:
    def __init__(self, response: _FakeResponse) -> None:
        self._response = response
        self.last_params: dict | None = None
        self.last_timeout = None

    def get(self, url: str, params: dict, timeout=None):
        self.last_params = params
        self.last_timeout = timeout
        return self._response


async def test_async_get_prices_returns_points():
    session = _FakeSession(_FakeResponse(200, DATA_DOCUMENT_SPARSE_POSITIONS))
    client = EntsoeApiClient(session, "fake-key")

    points = await client.async_get_prices(
        "10YFI-1--------U",
        datetime(2026, 10, 5, 22, 0, tzinfo=UTC),
        datetime(2026, 10, 6, 22, 0, tzinfo=UTC),
    )

    assert len(points) == 96
    assert session.last_params["securityToken"] == "fake-key"
    assert session.last_params["periodStart"] == "202610052200"
    assert session.last_timeout is not None
    assert session.last_timeout.total == 30


async def test_async_get_prices_wraps_timeout_in_api_error():
    # TimeoutError is not an aiohttp.ClientError; it must still surface as
    # the typed EntsoeApiError so callers' except-branches handle it.
    session = _FakeSession(_TimingOutResponse())
    client = EntsoeApiClient(session, "fake-key")

    with pytest.raises(EntsoeApiError):
        await client.async_get_prices(
            "10YFI-1--------U",
            datetime(2026, 10, 5, 22, 0, tzinfo=UTC),
            datetime(2026, 10, 6, 22, 0, tzinfo=UTC),
        )


async def test_async_get_prices_raises_auth_error_on_401():
    session = _FakeSession(_FakeResponse(401, ""))
    client = EntsoeApiClient(session, "bad-key")

    with pytest.raises(EntsoeAuthError):
        await client.async_get_prices(
            "10YFI-1--------U",
            datetime(2026, 10, 5, 22, 0, tzinfo=UTC),
            datetime(2026, 10, 6, 22, 0, tzinfo=UTC),
        )


async def test_async_get_prices_raises_no_data_error_on_ack_document():
    session = _FakeSession(_FakeResponse(400, ACK_NO_DATA))
    client = EntsoeApiClient(session, "fake-key")

    with pytest.raises(EntsoeNoDataError):
        await client.async_get_prices(
            "10YFI-1--------U",
            datetime(2026, 10, 6, 22, 0, tzinfo=UTC),
            datetime(2026, 10, 7, 22, 0, tzinfo=UTC),
        )
