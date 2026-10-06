.PHONY: setup test clean devrun

setup:
	uv venv .venv
	uv pip install -r requirements_test.txt -p .venv/bin/python

test:
	.venv/bin/python -m pytest -v

devrun:
	mkdir -p dev_config/custom_components
	ln -sfn ../../custom_components/entsoe_prices dev_config/custom_components/entsoe_prices
	.venv/bin/hass --config dev_config --open-ui

clean:
	rm -rf .venv
	find . -name '__pycache__' -type d -exec rm -rf {} +
