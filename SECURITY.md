# Security Policy

## Supported Versions

This project is pre-1.0 and has no backport policy. Only the latest
release (and `master`) is supported with security fixes.

## Reporting a Vulnerability

Please report security issues privately using GitHub's [private
vulnerability reporting](https://github.com/mteiste/entsoe-prices/security/advisories/new)
rather than opening a public issue. This keeps any disclosure private
until a fix is available.

You should expect an initial response within a few days. If the issue
is confirmed, a fix will be released and the advisory published once
users have had a chance to update.

## Scope

This integration stores your ENTSO-E API key in Home Assistant's own
config entry storage, the same mechanism any other integration uses
for credentials — it isn't encrypted by this integration itself. Report
issues related to how the integration handles that key (e.g. logging
it, leaking it over the network to somewhere other than the ENTSO-E
API), or any other vulnerability in this codebase. Issues in Home
Assistant Core's config entry storage itself should be reported to the
[Home Assistant project](https://www.home-assistant.io/security/)
instead.
