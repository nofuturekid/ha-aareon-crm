# Aareon Mieterportal for Home Assistant

Imports the monthly Techem consumption (heating and hot water, in kWh) shown in an
Aareon CRM tenant portal into Home Assistant as long-term statistics, including the
full history the portal offers (for example back to 2022). The portal's
"standardized user" comparison values are imported as well.

The only tenant-specific input is the portal URL (for example
`https://example-town-crm.aareon.com`).

**Disclaimer:** this is an unofficial, community-made integration. It is not
affiliated with, endorsed by or supported by Aareon or Techem; use it at your own risk.

## Installation

HACS: add `https://github.com/nofuturekid/ha-aareon-crm` as a custom repository
(category "Integration"), install, restart Home Assistant. Manual: copy `custom_components/aareon_crm` to
`<config>/custom_components/`.

Then add the integration under Settings, Devices & services, enter portal URL,
username and password, and pick the contracts to import (contracts with consumption
data are preselected). Contracts can be changed later in the integration options.

## What you get

Statistics (usable in the Energy dashboard as a data source or in statistics graph
cards), unit kWh, one row per month at the first hour of the month in the local time
zone, cumulative `sum`, `state` = monthly amount:

| Statistic id | Content |
| --- | --- |
| `aareon_crm:<contract number>_heating` | heating |
| `aareon_crm:<contract number>_hot_water` | hot water |
| `aareon_crm:<contract number>_heating_standardized` | heating of the portal's standardized user |
| `aareon_crm:<contract number>_hot_water_standardized` | hot water of the standardized user |

Only services a contract actually has data for are created. The full history is
recomputed and re-imported on every update, so the import is idempotent.

Sensors (one device per contract, value of the last complete month, attribute `period`):
heating, hot water, and the standardized values, plus a diagnostic sensor "Last
successful update".

## Naming

On setup (and later in the options) you choose a device name prefix, preset from the
portal's company name (for example "Acme"), and a short name per contract, preset from
the usage category (for example "Wohnung" or "Gewerbe"). The device is called
"prefix name" and entity ids follow from it. Renaming in the options renames the
devices; existing entity ids and unique ids are not touched.

## Icon

`custom_components/aareon_crm/brand/` holds `icon.png` and `icon@2x.png`; Home Assistant
2026.10 serves brand images of custom integrations from there, so no extra step is needed
locally. The artwork (source: `assets/icon.svg`) is neutral and contains no third-party
marks. To show the icon in HACS and on brands.home-assistant.io for everybody, add the
same two files under `custom_integrations/aareon_crm/` in a pull request to
`home-assistant/brands`.

## Behaviour and limits

- Polls every 6 hours (the data changes monthly). Every update logs in freshly and logs
  out again; credentials are stored in the config entry only.
- The portal sometimes lists a month twice per service (two meter ids, identical
  values); only the first row is used.
- Rows flagged `estimated` are imported (they are the portal's own figure) and marked
  in the sensor attribute `estimated`. Rows flagged as not tracked or without an amount
  are skipped; the cumulative sum simply carries over.
- Wrong credentials start the reauthentication flow; no automatic retries, to avoid
  locking the account.
- A selected contract that disappears from the portal raises a repair issue.
- Diagnostics download contains no credentials, contract numbers, names or addresses.

## Development

```
uv venv .venv && uv pip install -r requirements-test.txt
.venv/bin/ruff check . && .venv/bin/pytest
```

Tests use recorded, anonymised fixtures (`tests/fixtures`); the live portal is never
contacted.

## Releasing

HACS installs from GitHub releases. Set `version` in `manifest.json`, merge to `main`,
then push a matching tag (`git tag -s v0.1.1 && git push origin v0.1.1`). The `release`
workflow checks that tag and manifest version agree and creates the GitHub release with
generated notes.

## License

MIT
