# ENTSO-E Electricity Prices for Home Assistant

Fetches day-ahead electricity prices from the [ENTSO-E Transparency
Platform](https://transparency.entsoe.eu/) and exposes them as a Home
Assistant sensor, priced in c/kWh with optional VAT.

## Installation

### Via HACS (recommended)

This integration isn't in the default HACS store, so it needs to be added as
a custom repository first:

1. In Home Assistant, go to **HACS → Integrations**.
2. Click the **⋮** menu (top right) → **Custom repositories**.
3. Add `https://github.com/mteiste/entsoe-prices` as the repository, with
   category **Integration**.
4. Find "ENTSO-E Electricity Prices" in HACS and click **Download**.
5. Restart Home Assistant.

Future updates show up in HACS like any other installed integration.

### Manual install

1. Copy `custom_components/entsoe_prices` into your Home Assistant
   `config/custom_components/` directory.
2. Restart Home Assistant.

### Add the integration

1. Go to **Settings → Devices & Services → Add Integration** and search for
   "ENTSO-E".
2. Enter your ENTSO-E API key (request one from the [ENTSO-E Transparency
   Platform](https://transparency.entsoe.eu/) under your account settings),
   choose your bidding zone, and set your VAT percentage.

To change the API key, bidding zone, or VAT later, open the integration's
entry under **Settings → Devices & Services** and use **Reconfigure**.

## Entity

Each config entry creates one `sensor.electricity_price` entity:

- **State**: current hour's price in c/kWh (including VAT).
- **Attributes**: `raw_today`, `raw_tomorrow` (full price curves),
  `tomorrow_valid`, `next_hour_price`, `today_min`, `today_max`,
  `today_average`.

## Development

```bash
make setup   # create .venv and install test dependencies into it
make test    # run the test suite
make clean   # remove .venv and __pycache__ dirs
```

`make setup` creates an isolated virtual environment via
[`uv`](https://docs.astral.sh/uv/) rather than installing into your
system/user Python, which would otherwise pull in ~140 packages
(homeassistant's full dependency tree) outside any project isolation.
`uv` is used instead of the stdlib `python3 -m venv` since the latter
requires an `ensurepip`-enabled Python, which isn't always installed by
default.

`make test` runs `.venv/bin/python -m pytest -v` — always go through the
venv's own interpreter, not a bare `pytest` invocation or your system
Python; the bare console-script entry point doesn't reliably add the repo
root to `sys.path`, which this source tree relies on since it isn't
pip-installed.

No live network calls are made in the test suite; `EntsoeApiClient` is
always mocked or faked. Tests that depend on wall-clock time use the
`freezer` fixture (from `pytest-freezer`) to pin the clock rather than
partially mocking individual `dt_util` calls — partial mocks have
previously caused tests to pass only on specific calendar dates.

### Running against a real Home Assistant instance

```bash
make devrun  # launch a disposable HA instance in ./dev_config
```

This runs Home Assistant Core directly from the `hass` binary already
present in `.venv` (pulled in as a dependency of
`pytest-homeassistant-custom-component`), pointed at `dev_config/`, a
throwaway config directory with `custom_components/entsoe_prices`
symlinked in. It's a brand-new, isolated HA instance — unrelated to any
real/production Home Assistant setup — so there's no risk of touching
production state.

On first run it opens the normal onboarding wizard (create a local admin
account) at `http://localhost:8123`; after that, add the integration via
**Settings → Devices & Services → Add Integration → ENTSO-E**. `dev_config/`
is gitignored and safe to delete (`rm -rf dev_config`) to start over.

Note this runs HA Core only — no Supervisor/add-ons, so it won't fully
match a HAOS production install. If you need closer parity, run the
official `homeassistant/home-assistant` Docker image with its own
bind-mounted config directory instead.

## License

[MIT](LICENSE)
