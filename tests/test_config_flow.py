"""Tests for the ENTSO-E config flow."""
from unittest.mock import patch

from homeassistant import config_entries
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.entsoe_prices.api import EntsoeAuthError, EntsoeNoDataError
from custom_components.entsoe_prices.const import CONF_API_KEY, CONF_AREA, CONF_VAT, DOMAIN


async def test_user_flow_creates_entry_on_valid_credentials(hass):
    with patch(
        "custom_components.entsoe_prices.config_flow.EntsoeApiClient.async_get_prices",
        return_value=[],
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": config_entries.SOURCE_USER}
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {CONF_API_KEY: "fake-key", CONF_AREA: "Finland (FI)", CONF_VAT: 24.0},
        )

    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_API_KEY] == "fake-key"
    assert result["data"][CONF_AREA] == "Finland (FI)"


async def test_user_flow_shows_invalid_auth_error(hass):
    with patch(
        "custom_components.entsoe_prices.config_flow.EntsoeApiClient.async_get_prices",
        side_effect=EntsoeAuthError("bad key"),
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": config_entries.SOURCE_USER}
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {CONF_API_KEY: "bad-key", CONF_AREA: "Finland (FI)", CONF_VAT: 0.0},
        )

    assert result["type"] == FlowResultType.FORM
    assert result["errors"]["base"] == "invalid_auth"


async def test_user_flow_shows_cannot_connect_on_no_data_error(hass):
    # A validation call that fails with "no data" (e.g. a bad area code)
    # must not crash the flow with an unhandled exception.
    with patch(
        "custom_components.entsoe_prices.config_flow.EntsoeApiClient.async_get_prices",
        side_effect=EntsoeNoDataError("no data"),
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": config_entries.SOURCE_USER}
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {CONF_API_KEY: "fake-key", CONF_AREA: "Finland (FI)", CONF_VAT: 0.0},
        )

    assert result["type"] == FlowResultType.FORM
    assert result["errors"]["base"] == "cannot_connect"


async def test_options_flow_updates_vat(hass):
    with patch(
        "custom_components.entsoe_prices.config_flow.EntsoeApiClient.async_get_prices",
        return_value=[],
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": config_entries.SOURCE_USER}
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {CONF_API_KEY: "fake-key", CONF_AREA: "Finland (FI)", CONF_VAT: 0.0},
        )
    entry = hass.config_entries.async_entries(DOMAIN)[0]

    options_result = await hass.config_entries.options.async_init(entry.entry_id)
    options_result = await hass.config_entries.options.async_configure(
        options_result["flow_id"], {CONF_VAT: 25.5}
    )

    assert options_result["type"] == FlowResultType.CREATE_ENTRY
    assert options_result["data"][CONF_VAT] == 25.5


def _reauth_entry(hass) -> MockConfigEntry:
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Finland (FI)",
        data={CONF_API_KEY: "old-key", CONF_AREA: "Finland (FI)", CONF_VAT: 24.0},
    )
    entry.add_to_hass(hass)
    return entry


async def test_reauth_flow_updates_api_key_and_keeps_other_data(hass):
    entry = _reauth_entry(hass)

    with patch(
        "custom_components.entsoe_prices.config_flow.EntsoeApiClient.async_get_prices",
        return_value=[],
    ) as mock_get_prices:
        result = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={
                "source": config_entries.SOURCE_REAUTH,
                "entry_id": entry.entry_id,
            },
            data=entry.data,
        )
        assert result["type"] == FlowResultType.FORM
        assert result["step_id"] == "reauth_confirm"

        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_API_KEY: "new-key"}
        )
        await hass.async_block_till_done()

    assert result["type"] == FlowResultType.ABORT
    assert result["reason"] == "reauth_successful"
    assert entry.data == {
        CONF_API_KEY: "new-key",
        CONF_AREA: "Finland (FI)",
        CONF_VAT: 24.0,
    }
    # Validation must use the existing entry's area, not prompt for it.
    assert mock_get_prices.call_args_list[0].args[0] == "10YFI-1--------U"


async def test_reauth_flow_shows_invalid_auth_and_keeps_old_key(hass):
    entry = _reauth_entry(hass)

    with patch(
        "custom_components.entsoe_prices.config_flow.EntsoeApiClient.async_get_prices",
        side_effect=EntsoeAuthError("still bad"),
    ):
        result = await entry.start_reauth_flow(hass)
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_API_KEY: "another-bad-key"}
        )

    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "reauth_confirm"
    assert result["errors"]["base"] == "invalid_auth"
    assert entry.data[CONF_API_KEY] == "old-key"


def _reconfigure_entry(hass) -> MockConfigEntry:
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Finland (FI)",
        data={CONF_API_KEY: "old-key", CONF_AREA: "Finland (FI)", CONF_VAT: 24.0},
    )
    entry.add_to_hass(hass)
    return entry


async def test_reconfigure_flow_updates_api_key_area_and_vat(hass):
    entry = _reconfigure_entry(hass)

    with patch(
        "custom_components.entsoe_prices.config_flow.EntsoeApiClient.async_get_prices",
        return_value=[],
    ) as mock_get_prices:
        result = await entry.start_reconfigure_flow(hass)
        assert result["type"] == FlowResultType.FORM
        assert result["step_id"] == "reconfigure"

        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {
                CONF_API_KEY: "new-key",
                CONF_AREA: "Sweden 3 (SE3)",
                CONF_VAT: 25.5,
            },
        )
        await hass.async_block_till_done()

    assert result["type"] == FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"
    assert entry.data == {
        CONF_API_KEY: "new-key",
        CONF_AREA: "Sweden 3 (SE3)",
        CONF_VAT: 25.5,
    }
    # Validation must use the newly submitted area, not the old one.
    assert mock_get_prices.call_args_list[0].args[0] == "10Y1001A1001A46L"


async def test_reconfigure_flow_shows_invalid_auth_and_keeps_old_data(hass):
    entry = _reconfigure_entry(hass)

    with patch(
        "custom_components.entsoe_prices.config_flow.EntsoeApiClient.async_get_prices",
        side_effect=EntsoeAuthError("bad key"),
    ):
        result = await entry.start_reconfigure_flow(hass)
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {CONF_API_KEY: "bad-key", CONF_AREA: "Finland (FI)", CONF_VAT: 24.0},
        )

    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "reconfigure"
    assert result["errors"]["base"] == "invalid_auth"
    assert entry.data[CONF_API_KEY] == "old-key"
