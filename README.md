# Noma IQ HACS integration

[![HACS Custom](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=mnfjorge&repository=https%3A%2F%2Fgithub.com%2Fmnfjorge%2Fhacs-nomaiq&category=integration)
[![Validate](https://github.com/mnfjorge/hacs-nomaiq/actions/workflows/validate.yml/badge.svg)](https://github.com/mnfjorge/hacs-nomaiq/actions/workflows/validate.yml)
[![Lint](https://github.com/mnfjorge/hacs-nomaiq/actions/workflows/lint.yml/badge.svg)](https://github.com/mnfjorge/hacs-nomaiq/actions/workflows/lint.yml)

## About

This integration exposes devices from the Noma IQ app as Home Assistant entities, talking to the Ayla IoT cloud that backs the Noma IQ mobile app.

## Supported devices

| Device                                               | Entity types                                                                                                                                                  |
| ---------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Garage Door Opener (`gdo`)                           | `cover` (open / close / stop) and `light` for the opener's bulb                                                                                               |
| Water Controller / Hose Control (`water-controller`) | One `switch` per paired hose unit                                                                                                                             |
| Dehumidifier (`dehum`)                               | `humidifier`, `number` (target humidity), `sensor` (indoor humidity), `select` (mode, fan speed), and `binary_sensor` (water bucket full, filter clean alarm) |

Other Noma IQ devices can be **adopted** (below): they appear under **Settings → System → Repairs**, where an AI Task of your choice analyzes the device's cloud properties and proposes entities for you to review and apply. You can also still open an issue with the device's `oem_model_number` and property dump if you want native support added.

## Requirements

- Home Assistant **2025.8.0** or newer (the device-adoption feature is built on [AI Task](https://www.home-assistant.io/integrations/ai_task/), introduced in 2025.8)
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

## Adopting unknown devices

Devices whose `oem_model_number` the integration doesn't natively support can be **adopted** using any [AI Task](https://www.home-assistant.io/integrations/ai_task/) entity you have configured (Google, OpenAI, Mistral, local models — anything that supports data generation). Every AI run is user-initiated and reviewed before anything is created. With no AI Task entity configured, the integration still works exactly as before.

### How it works

1. Unknown devices are detected deterministically — no AI involved. Each one immediately gets read-only **diagnostic sensors** (one per cloud property) so it's inspectable, plus a fixable entry under **Settings → System → Repairs**: *"Unknown NomaIQ device: \<model\>"*, including a property triage (how many properties, how many writable).
2. Clicking the Repairs entry starts the adoption flow: confirm → the AI Task runs in full view (progress dialog) → the proposed mapping is shown (entity summary + raw JSON) → **Apply** or **Discard**. Nothing is stored or created until you apply.
3. The proposal is validated against the device's real properties before you ever see it: commands must target writable properties, invented property names are dropped, and per-unit fanout ranges are shrunk to units that actually exist.
4. Applied mappings are stored per model in `.storage/nomaiq_mappings` — the AI is consulted **once per model**, restarts reuse the stored mapping with zero AI calls. Discarding keeps the Repairs entry around so you can adopt later.

### Options (Settings → Devices & Services → NomaIQ → Configure)

| Option | Description |
| ------ | ----------- |
| **AI Task entity** | Preferred AI Task for adoptions. Leave empty to pick one during each adoption. |
| **Offer AI adoption** | Creates the Repairs entry per unknown model (default on). Nothing runs automatically either way. |
| **Diagnostic property sensors** | One sensor per unmapped property on adoptable devices (default on). |
| **Treat these models as unknown (debug)** | Comma-separated models (e.g. `water-controller`) routed through the adoption path even though natively supported. Their native entities go unavailable while forced and return when un-forced. Useful for validating your AI Task against a known-good device. |

### Services

| Service | What it does |
| ------- | ------------ |
| `nomaiq.unadopt_device` | Delete the stored mapping for an `oem_model` and reload. The adoption offer reappears under Repairs. |

### Notes and caveats

- Adopted entities can be `sensor`, `binary_sensor`, `switch`, `light`, `cover`, and `number`. `select`/`humidifier`/`valve` kinds are not generated yet.
- Forcing `dehum` through the adoption path loses the native `humidifier` and `select` entities for as long as it's forced.
- Forced models get different entity unique IDs than their native entities; the native IDs are restored when un-forced.
- After adopting, diagnostic sensors for properties now covered by the mapping are no longer created; their old registry entries may linger as unavailable until you remove them (cosmetic).
- Small local models may struggle with devices that expose very many properties; the preview step always lets you inspect the proposal before applying.

## Troubleshooting

| Problem                       | Fix                                                                                                                              |
| ----------------------------- | -------------------------------------------------------------------------------------------------------------------------------- |
| **Authentication fails**      | Confirm the credentials work in the Noma IQ mobile app, then re-authenticate via the integration's *Reconfigure* flow.           |
| **Entities stuck unavailable**| The Ayla cloud or the device may be offline. Check the device in the Noma IQ app, then reload the integration.                   |
| **Need debug logs**           | In `configuration.yaml`, add `logger:` with `custom_components.nomaiq: debug` and `ayla_iot_unofficial: debug`, then restart.    |
| **A device isn't showing up** | The integration only exposes devices it knows how to model. Open an issue with the device's `oem_model_number` and property dump.|

## Contributions

Contributions are welcome — please open an issue first for non-trivial changes. The lint and validate workflows must pass on PRs.

## Credits

- Originally forked from [mnfjorge/hacs-nomaiq](https://github.com/mnfjorge/hacs-nomaiq).
- Dehumidifier support adapted from [gravyflex/noma-iq-homeassistant](https://github.com/gravyflex/noma-iq-homeassistant) (NOMA iQ dehumidifier property mapping and entity layout).
