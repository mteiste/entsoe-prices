"""Constants for the ENTSO-E integration."""
from __future__ import annotations

from datetime import timedelta

DOMAIN = "entsoe_prices"

CONF_API_KEY = "api_key"
CONF_AREA = "area"
CONF_VAT = "vat"

DEFAULT_VAT = 0.0
DEFAULT_SCAN_INTERVAL = timedelta(hours=1)

# Human-readable bidding zone name -> ENTSO-E EIC area code.
# "Finland (FI)" was verified live against the ENTSO-E API on 2026-10-06.
# Verify/extend the rest against ENTSO-E's published area list before
# relying on a zone other than Finland.
AREA_CODES: dict[str, str] = {
    "Austria (AT)": "10YAT-APG------L",
    "Belgium (BE)": "10YBE----------2",
    "Czech Republic (CZ)": "10YCZ-CEPS-----N",
    "Denmark 1 (DK1)": "10YDK-1--------W",
    "Denmark 2 (DK2)": "10YDK-2--------M",
    "Estonia (EE)": "10Y1001A1001A39I",
    "Finland (FI)": "10YFI-1--------U",
    "France (FR)": "10YFR-RTE------C",
    "Germany-Luxembourg (DE-LU)": "10Y1001A1001A82H",
    "Latvia (LV)": "10YLV-1001A00074",
    "Lithuania (LT)": "10YLT-1001A0008Q",
    "Netherlands (NL)": "10YNL----------L",
    "Norway 1 (NO1)": "10YNO-1--------2",
    "Norway 2 (NO2)": "10YNO-2--------T",
    "Norway 3 (NO3)": "10YNO-3--------J",
    "Norway 4 (NO4)": "10YNO-4--------9",
    "Norway 5 (NO5)": "10Y1001A1001A48H",
    "Poland (PL)": "10YPL-AREA-----S",
    "Portugal (PT)": "10YPT-REN------W",
    "Spain (ES)": "10YES-REE------0",
    "Sweden 1 (SE1)": "10Y1001A1001A44P",
    "Sweden 2 (SE2)": "10Y1001A1001A45N",
    "Sweden 3 (SE3)": "10Y1001A1001A46L",
    "Sweden 4 (SE4)": "10Y1001A1001A47J",
    "Switzerland (CH)": "10YCH-SWISSGRIDZ",
}
