# NetBox Prefix Map

[![CI](https://github.com/islepnev/netbox-prefix-map/actions/workflows/ci.yml/badge.svg?branch=master)](https://github.com/islepnev/netbox-prefix-map/actions/workflows/ci.yml)
[![NetBox 4.x](https://img.shields.io/badge/NetBox-4.x-blue)](#requirements)
[![License: Apache 2.0](https://img.shields.io/badge/license-Apache%202.0-blue)](LICENSE)

**A world map of your IPv4 space.** Every address is a cell, every subnet is a rectangle, every tenant is drawn in its colour, from a /8 down to a single address. The maps are drawn from [NetBox](https://github.com/netbox-community/netbox) and redrawn when NetBox reports a change through a webhook.

![Map of a /17: tenant blocks, used addresses, a pinned free address with its prefix chain and free blocks](docs/img/hero.png)

## How to read the map

Addresses run along a Z-order (Morton) curve: the first half of a prefix is the top or left half of its map, the first quarter is the top-left quarter, and so on. Every aligned subnet is therefore a rectangle: a /24 is a 16 × 16 square on a /16 map, and a /25 is half of it. The grey numbers on the map are the octets that tell these squares apart, e.g. the third octet of each /24.

![Z-order layout of a /27: addresses 0 to 31, with a /30, a /29 and a /28 as rectangles](static/img/z-order.svg)

The same space at three levels, as printed:

| /8: one cell per /24 | /16: one cell per address | /24 |
|---|---|---|
| ![Layered map of 10.0.0.0/8](docs/img/level-8.png) | ![Map of 10.20.0.0/16](docs/img/level-16.png) | ![Map of 10.20.50.0/24](docs/img/level-24.png) |

## Search, links, print

- **Search.** Addresses and prefixes, and text in DNS names, descriptions, tenant and role names, across all VRFs. `free /26` lists free /26 blocks in all VRFs, `free /26 in 10.20.0.0/16` within a prefix.
- **Links.** The URL keeps the pinned address and the outlined tenant. `?lang=ru` opens a page in Russian; otherwise the browser language decides.
- **Print.** Ctrl+P prints the map alone as vector graphics with title and legend; in black and white, tenants are hatched.

## Requirements

- NetBox 4.x and an API token with read access to IPAM (prefixes, IP addresses, VRFs; roles, IP ranges and VLANs optional), Tenancy (tenants) and optionally DCIM (sites, locations, regions, site groups)
- Docker with Compose, or Python 3.13

## Configuration

Settings are read from the environment or from a `.env` file in the project directory.

| Variable | Default | Description |
|---|---|---|
| `NETBOX_API_URL` | | NetBox base URL, e.g. `https://netbox.example.com` |
| `NETBOX_API_TOKEN` | | API token |
| `NETBOX_TIMEOUT` | `30` | API request timeout, seconds |
| `BASE_PATH` | `/prefix-map` | URL path prefix of the web interface, so that it can share the NetBox host |
| `OUTPUT_DIR` | `output` | Generated files; relative paths are resolved against the project directory |
| `CELL_SIZE` | `4` | Cell size in image pixels |
| `WEBHOOK_SECRET` | | Shared secret of the NetBox webhook; when set, unsigned requests are rejected |
| `UPDATE_DEBOUNCE_SECONDS` | `60` | A burst of webhooks gives one update at once and at most one more after this interval |
| `UPDATE_INTERVAL_SECONDS` | `0` | Periodic full update when none has run for this long, at most once per `UPDATE_DEBOUNCE_SECONDS`; `0` turns it off |
| `INITIAL_UPDATE` | `1` | Set to `0` to skip the update at startup |
| `PORT` | `5000` | Listening port |

## Running

```bash
make up
```

The container serves requests at once and draws the maps in the background; they appear when the first update ends. Generated files are kept in the `output` volume.

Without Docker:

```bash
pip install -r requirements.txt
python -m app.cli       # one-off update
python -m app.webapp    # development server
```

## NetBox setup

### Webhook

1. Operations › Integrations › Webhooks › Add: URL `http://<host>:5000/prefix-map/webhook`, method `POST`, content type `application/json`, secret as in `WEBHOOK_SECRET`.
2. Operations › Integrations › Event Rules › Add: object types IPAM › Prefix, IPAM › IP Address, IPAM › IP Range, IPAM › VRF, Tenancy › Tenant; optionally IPAM › Role, IPAM › VLAN, DCIM › Site, Location, Region, Site Group, so that renames show up; events created, updated, deleted; action: the webhook above.

Where IP addresses change often and in batches, leave IPAM › IP Address out of the event rule: NetBox queues one webhook job per changed object. Set `UPDATE_INTERVAL_SECONDS` (e.g. `900`) instead; the maps then pick up address changes within that interval, and webhooks for the other objects still update them at once.

### Map button on prefix pages

Customization › Custom Links › Add, object type IPAM › Prefix:

- Link text: `Map`
- Link URL:

  ```
  /prefix-map/map/{{ object.vrf.pk if object.vrf else 'None' }}/{{ (object.prefix | string).replace('.', '_').replace('/', '_') }}
  ```

## Reverse proxy and access control

The maps show every prefix, IP address, DNS name, tenant and description that the API token can read. The app has no login of its own: restrict it at the reverse proxy. Apache, in the NetBox virtual host:

```apache
<Location /prefix-map>
    ProxyPass http://localhost:5000/prefix-map
    ProxyPassReverse http://localhost:5000/prefix-map
    AuthType Basic
    AuthName "Prefix Map"
    AuthUserFile /etc/apache2/prefix-map.htpasswd
    Require valid-user
</Location>
<Location /prefix-map/webhook>
    Require ip 127.0.0.1 ::1
</Location>
```

The webhook must stay reachable for NetBox: put the address of the NetBox host in `Require ip` when it is not localhost. Without `WEBHOOK_SECRET`, anyone who can reach `/webhook` can trigger a full refetch from NetBox (at most one per `UPDATE_DEBOUNCE_SECONDS`). `/healthz` and `/metrics` carry no inventory data; `/errors` shows log lines, so keep it behind the same rule as the maps.

## Endpoints

Paths are relative to `BASE_PATH`.

| Path | Description |
|---|---|
| `/map/<vrf>/<prefix>` | Map page; `<vrf>` is the VRF id or `None` for Global, `<prefix>` uses `_` for `.` and `/` |
| `/search?q=<query>` | Search as in the search box (JSON) |
| `/webhook` | NetBox webhook receiver |
| `/healthz` | Liveness and data age (JSON); used by the container healthcheck |
| `/metrics` | Prometheus metrics |
| `/errors` | Recent warnings and errors |

## Limitations

- IPv4 only; IPv6 prefixes are skipped.
- 16 tenant colours, by tenant id: tenants 16 ids apart share a colour.
- Prefixes shorter than /16 get one cell per aligned block, at most 65,536 cells.
- The updater runs inside the web process; run a single web worker.

## Development

```bash
make test    # offline, on the synthetic dataset in tests/synthetic_data.py
make lint    # flake8, also run in CI
```

Design notes: [docs/design.md](docs/design.md). UI text lives in `app/locales/<lang>.json` and `templates/_help_<lang>.html`; to add a language, translate copies of the English files and add the code to `LANGUAGES` in `app/i18n.py`.

Contributions are accepted under the Apache License 2.0, as the rest of the project.

## License

Apache License 2.0, see [LICENSE](LICENSE). Redistributions and derivative works must keep the copyright and [NOTICE](NOTICE) with the author's name, Ilia Slepnev.
