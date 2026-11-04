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
- **Data problems.** Each update flags records that NetBox accepts but that are most likely wrong: an IP mask that differs from its subnet, IPs in a container outside its subnets, network and broadcast addresses recorded as IPs, prefixes recorded twice in a VRF. The prefix summary lists them, the map outlines them, the VRF page counts them.

## Install

On the NetBox host, with Docker:

1. Create a read-only API token in NetBox and write `.env` in the project directory:

   ```ini
   NETBOX_API_URL=https://netbox.example.com
   NETBOX_API_TOKEN=<token>
   WEBHOOK_SECRET=<any random string>
   PUBLISH_ADDR=127.0.0.1
   NETBOX_SESSION_AUTH=1
   ```

2. Start it: `make up`.
3. Apache, in the NetBox virtual host:

   ```apache
   ProxyPass        /prefix-map http://127.0.0.1:5000/prefix-map
   ProxyPassReverse /prefix-map http://127.0.0.1:5000/prefix-map
   ```

4. NetBox, Operations › Integrations:
   - Webhooks › Add: URL `http://127.0.0.1:5000/prefix-map/webhook`, secret from `.env`.
   - Event Rules › Add: object types Prefix, IP Address, IP Range, VRF, Tenant; events created, updated, deleted; action: that webhook.

Open `https://netbox.example.com/prefix-map/`. The maps appear when the first update ends. They open to users signed in to NetBox who may view prefixes there; others get the NetBox login page or "Access Denied".

Optional: a Map button on prefix pages. Customization › Custom Links › Add, object type IPAM › Prefix, link text `Map`, link URL:

```
/prefix-map/map/{{ object.vrf.pk if object.vrf else 'None' }}/{{ (object.prefix | string).replace('.', '_').replace('/', '_') }}
```

## Details

### Requirements

- NetBox 4.x (access through NetBox accounts: written against 4.6). The token reads IPAM (prefixes, IP addresses, VRFs; roles, IP ranges and VLANs optional), Tenancy (tenants) and optionally DCIM (sites, locations, regions, site groups); objects it cannot read are skipped with a warning.
- Docker with Compose, or Python 3.13.

### Settings

Read from the environment or from `.env` in the project directory.

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
| `NETBOX_SESSION_AUTH` | `0` | `1`: open the maps only to users signed in to NetBox who may view prefixes there |
| `NETBOX_SESSION_COOKIE` | `sessionid` | Name of the NetBox session cookie (`SESSION_COOKIE_NAME` in NetBox) |
| `NETBOX_LOGIN_URL` | `/login/` | NetBox login page for users without a session |
| `NETBOX_AUTH_CACHE_SECONDS` | `300` | How long the answer of NetBox about a session is kept |
| `TRUSTED_PROXIES` | `1` | Reverse proxies in front of the app; the client address in the logs is taken from `X-Forwarded-For` accordingly; `0` ignores the header |
| `PUBLISH_ADDR` | `0.0.0.0` | Docker Compose: host address the port is published on |

### Access

The maps show every prefix, IP address, DNS name, tenant and description that the API token can read.

- Keep port 5000 closed to the network (`PUBLISH_ADDR=127.0.0.1`): Docker publishes ports past the host firewall, and the port bypasses the reverse proxy.
- `NETBOX_SESSION_AUTH=1` needs the app on the NetBox host, so that the browser sends it the NetBox session cookie. The app asks the NetBox API with that cookie whether the user may view prefixes, and keeps the answer per session for `NETBOX_AUTH_CACHE_SECONDS`. Constraints of object permissions are not applied: a user who may view some prefixes sees all maps. `/static`, `/healthz`, `/metrics` and `/webhook` are open without a session. When NetBox does not answer, pages give 503.
- Without it, the app has no login of its own: restrict `/prefix-map` at the reverse proxy, e.g. Apache `AuthType Basic` with `Require valid-user`, and let the NetBox host reach `/prefix-map/webhook`.
- Without `WEBHOOK_SECRET`, anyone who can reach `/webhook` can trigger a full refetch from NetBox (at most one per `UPDATE_DEBOUNCE_SECONDS`).
- `/healthz` and `/metrics` carry no inventory data; `/errors` shows log lines.

### Webhook

Optionally add IPAM › Role, IPAM › VLAN, DCIM › Site, Location, Region, Site Group to the event rule, so that renames show up at once. When NetBox runs on another host, use an address where it reaches the app.

Where IP addresses change often and in batches, leave IP Address out of the event rule: NetBox queues one webhook job per changed object. Set `UPDATE_INTERVAL_SECONDS` (e.g. `900`) instead; the maps then pick up address changes within that interval, and webhooks for the other objects still update them at once.

### Without Docker

```bash
pip install -r requirements.txt
python -m app.cli       # one-off update
python -m app.webapp    # development server
```

The container serves requests at once and draws the maps in the background. Generated files are kept in the `output` volume.

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
