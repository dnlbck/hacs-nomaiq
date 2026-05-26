# Noma IQ HACS integration

[![HACS Custom](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=mnfjorge&repository=https%3A%2F%2Fgithub.com%2Fmnfjorge%2Fhacs-nomaiq&category=integration)
[![Validate](https://github.com/mnfjorge/hacs-nomaiq/actions/workflows/validate.yml/badge.svg)](https://github.com/mnfjorge/hacs-nomaiq/actions/workflows/validate.yml)
[![Lint](https://github.com/mnfjorge/hacs-nomaiq/actions/workflows/lint.yml/badge.svg)](https://github.com/mnfjorge/hacs-nomaiq/actions/workflows/lint.yml)

## About

This integration exposes devices from the Noma IQ app as Home Assistant entities, talking to the Ayla IoT cloud that backs the Noma IQ mobile app.

## Supported devices

| Device                                               | Entity types                                                    |
| ---------------------------------------------------- | --------------------------------------------------------------- |
| Garage Door Opener (`gdo`)                           | `cover` (open / close / stop) and `light` for the opener's bulb |
| Water Controller / Hose Control (`water-controller`) | One `switch` per paired hose unit                               |

Other Noma IQ devices are not implemented yet — open an issue with the device's `oem_model_number` and property dump if you want one added.

## Requirements

- Home Assistant **2024.10.0** or newer
- A working Noma IQ account (the same credentials you use in the mobile app)

## Installation

### HACS (recommended)

[![Open your Home Assistant instance and open a repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=mnfjorge&repository=https%3A%2F%2Fgithub.com%2Fmnfjorge%2Fhacs-nomaiq&category=integration)

Or, in HACS, search for "Noma IQ". If it doesn't appear, [add this repository URL as a HACS custom repository](https://hacs.xyz/docs/faq/custom_repositories) under the Integration category.

### Manual

1. Copy `custom_components/nomaiq/` into your Home Assistant `config/custom_components/` directory.
2. Restart Home Assistant.

## Configuration

[![Open your Home Assistant instance and start setting up a new integration of a specific brand.](https://my.home-assistant.io/badges/brand.svg)](https://my.home-assistant.io/redirect/brand/?brand=+Noma+IQ)

After installation, set up the integration via **Settings → Devices & Services → Add Integration → Noma IQ**. Provide:

- **Username** — the email used to sign into the Noma IQ app
- **Password** — your Noma IQ password

Entities for each device on the account are created automatically. For the Water Controller, only paired hose units get a switch entity.

## Troubleshooting

| Problem                       | Fix                                                                                                                              |
| ----------------------------- | -------------------------------------------------------------------------------------------------------------------------------- |
| **Authentication fails**      | Confirm the credentials work in the Noma IQ mobile app, then re-authenticate via the integration's *Reconfigure* flow.           |
| **Entities stuck unavailable**| The Ayla cloud or the device may be offline. Check the device in the Noma IQ app, then reload the integration.                   |
| **Need debug logs**           | In `configuration.yaml`, add `logger:` with `custom_components.nomaiq: debug` and `ayla_iot_unofficial: debug`, then restart.    |
| **A device isn't showing up** | The integration only exposes devices it knows how to model. Open an issue with the device's `oem_model_number` and property dump.|

## Contributions

Contributions are welcome — please open an issue first for non-trivial changes. The lint and validate workflows must pass on PRs.
